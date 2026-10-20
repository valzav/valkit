"""Write converted threads into a folder: new messages only, appended to earlier output.

Every message already listed in the folder's processing log is skipped. New messages of a topic
(by-topic) or thread (single file) go at the end of the file that holds this input's earlier
messages, or into a new file when there is none.
"""

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import cast

from valkit.email_extractor.contacts import all_addresses
from valkit.email_extractor.files import write_text
from valkit.email_extractor.log import LOG_FILE, STRICT_EXTENSION, ProcessedLog, fits_format
from valkit.email_extractor.model import Address, Message, Participant
from valkit.email_extractor.redact import Redactor
from valkit.email_extractor.render import (
    continuation,
    date_range,
    document,
    frontmatter,
    merge_metadata,
    merge_participants,
    metadata,
    name_of,
    records_of,
    split_frontmatter,
    title_of,
    to_json,
)
from valkit.email_extractor.split import topic
from valkit.email_extractor.strict import Scrubber, first_name

METADATA_FILE = "metadata.json"
DATED_NAME_RE = re.compile(r"^(\d{8})-(\d{8})-(.+)\.md$")


class Renderer:
    """Rendering for one input: plain, or strict (first names, personal details scrubbed)."""

    def __init__(self, messages: list[Message], strict: bool) -> None:
        self.strict = strict
        # One redactor per input, so a secret keeps one placeholder across its files.
        self._redactor = Redactor()
        self._scrubber = Scrubber(all_addresses(messages)) if strict else None

    @property
    def extension(self) -> str:
        return STRICT_EXTENSION if self.strict else ".md"

    def name(self, address: Address) -> str:
        return first_name(address) if self.strict else name_of(address)

    def label(self, text: str) -> str:
        """Text as it appears in headings and file names, redacted like the body."""
        text = self._redactor.redact(text)
        return self._scrubber.scrub(text) if self._scrubber else text

    def finish(self, markdown: str) -> str:
        markdown = self._redactor.redact(markdown)
        return self._scrubber.scrub(markdown) if self._scrubber else markdown

    def data(self, data: dict[str, object]) -> dict[str, object]:
        return cast(dict[str, object], self._redactor.redact_data(data))

    def document(self, messages: list[Message], title: str) -> str:
        return self.finish(document(messages, title, self.name))

    def continuation(self, existing: str, messages: list[Message]) -> str:
        addition = continuation(existing, messages, self.name, self.label)
        return existing.rstrip("\n") + "\n\n" + self.finish(addition)


def render_single(
    messages: list[Message],
    participants: list[Participant],
    source: str,
    renderer: Renderer,
) -> str:
    """One document for the thread: JSON frontmatter in normal mode, none in strict mode."""
    body = renderer.document(messages, title_of(messages, source))
    if renderer.strict:
        return body
    return frontmatter(renderer.data(metadata(messages, participants, source))) + body


def write_single(
    messages: list[Message],
    participants: list[Participant],
    source: str,
    folder: Path,
    file_name: str,
    renderer: Renderer,
    log: ProcessedLog,
) -> list[Path]:
    output_format = "markdown-strict" if renderer.strict else "markdown"
    new = [message for message in messages if not log.file_of(output_format, message.key)]
    if not new:
        return []
    involved = involved_in(participants, new)
    earlier = _earlier_file(messages, output_format, log)
    if earlier:
        file_name = earlier
    _check_owner(folder, file_name, output_format, log)
    if earlier:
        old_meta, old_body = split_frontmatter((folder / earlier).read_text(encoding="utf-8"))
        text = renderer.continuation(old_body, new)
        if not renderer.strict:
            new_meta = renderer.data(metadata(new, involved, source))
            text = frontmatter(merge_metadata(old_meta, new_meta)) + text
    else:
        text = render_single(new, involved, source, renderer)
    write_text(folder / file_name, text)
    log.record(output_format, [message.key for message in new], file_name)
    return [folder / file_name]


def write_by_topic(
    messages: list[Message],
    participants: list[Participant],
    source: str,
    folder: Path,
    renderer: Renderer,
    log: ProcessedLog,
) -> list[Path]:
    output_format = "topics-strict" if renderer.strict else "topics"
    thread = title_of(messages, source)
    by_topic: dict[str, list[Message]] = {}
    for message in messages:
        by_topic.setdefault(topic(message.subject) or thread, []).append(message)

    written: list[Path] = []
    topic_entries: list[tuple[str | None, dict[str, object]]] = []
    # A new topic never takes the name of a file already in the folder, whoever wrote it.
    taken = _folder_names(folder)
    for subject, topic_messages in by_topic.items():
        new = [m for m in topic_messages if not log.file_of(output_format, m.key)]
        if not new:
            continue
        earlier = _earlier_file(topic_messages, output_format, log)
        if earlier:
            _check_owner(folder, earlier, output_format, log)
            text = renderer.continuation((folder / earlier).read_text(encoding="utf-8"), new)
            name = _extended_name(folder, earlier, new)
            if name != earlier:
                (folder / earlier).unlink()
                log.rename(output_format, earlier, name)
        else:
            text = renderer.document(new, subject)
            name = _new_name(
                new,
                renderer.label(subject),
                renderer.extension,
                taken | {path.name for path in written},
            )
        write_text(folder / name, text)
        log.record(output_format, [message.key for message in new], name)
        written.append(folder / name)
        topic_entries.append(
            (
                earlier,
                {
                    "file": name,
                    "subject": subject,
                    "thread": thread,
                    "sources": [source],
                    "messages": len(new),
                    "date_range": date_range(new),
                    "participants": [p.name or p.emails[0] for p in involved_in(participants, new)],
                },
            )
        )

    if written and not renderer.strict:
        involved = involved_in(participants, [m for ms in by_topic.values() for m in ms])
        written.append(_update_metadata(folder, involved, topic_entries, renderer))
    return written


def involved_in(participants: list[Participant], messages: list[Message]) -> list[Participant]:
    addresses = [a for m in messages for a in (m.sender, *m.to, *m.cc)]
    emails = {a.email for a in addresses if a.email}
    names = {a.name for a in addresses if a.name}
    return [p for p in participants if emails & set(p.emails) or p.name in names]


def default_file_name(input_path: Path, renderer: Renderer) -> str:
    """`<input>.md`; an input without an .eml extension keeps its whole name."""
    stem = input_path.stem if input_path.suffix.lower() == ".eml" else input_path.name
    return f"{renderer.label(stem)}{renderer.extension}"


def _earlier_file(messages: list[Message], output_format: str, log: ProcessedLog) -> str | None:
    """The file that already holds some of these messages, if any."""
    return next(
        (name for message in messages if (name := log.file_of(output_format, message.key))),
        None,
    )


def _new_name(messages: list[Message], subject: str, extension: str, taken: set[str]) -> str:
    dates = [message.date for message in messages if message.date]
    span = f"{min(dates):%Y%m%d}-{max(dates):%Y%m%d}" if dates else "undated"
    slug = re.sub(r"[\W_]+", "-", subject.lower()).strip("-") or "untitled"
    name = f"{span}-{slug}{extension}"
    suffix = 2
    # Compared in any case: a case-insensitive disk would open "Draft.md" for "draft.md".
    taken = {entry.casefold() for entry in taken}
    while name.casefold() in taken:
        name = f"{span}-{slug}-{suffix}{extension}"
        suffix += 1
    return name


def _folder_names(folder: Path) -> set[str]:
    return {path.name for path in folder.iterdir()} if folder.is_dir() else set()


def _check_owner(folder: Path, file_name: str, output_format: str, log: ProcessedLog) -> None:
    """Refuse to write a file that holds another format's output, or the tool's own files.

    Writing normal output into a strict file would silently put full personal details into a
    file meant for sharing.
    """
    if not fits_format(file_name, output_format):
        kind = (
            "strict output needs" if output_format.endswith("-strict") else "normal output avoids"
        )
        raise ValueError(f"{folder / file_name}: {kind} names ending in {STRICT_EXTENSION}")
    others = sorted(log.owners(file_name) - {output_format})
    if others or file_name in {METADATA_FILE, LOG_FILE}:
        holder = f"{', '.join(others)} output" if others else "the tool's own data"
        raise ValueError(f"{folder / file_name} holds {holder}; choose another name with -o")


def _extended_name(folder: Path, name: str, messages: list[Message]) -> str:
    """The file name with its date range widened to cover the appended messages."""
    found = DATED_NAME_RE.match(name)
    dates = [f"{message.date:%Y%m%d}" for message in messages if message.date]
    if not found or not dates:
        return name
    start, end = min(found.group(1), *dates), max(found.group(2), *dates)
    extended = f"{start}-{end}-{found.group(3)}.md"
    # Never overwrite another file; keep the old name if the new one is taken.
    return extended if extended == name or not (folder / extended).exists() else name


def _update_metadata(
    folder: Path,
    participants: list[Participant],
    topic_entries: list[tuple[str | None, dict[str, object]]],
    renderer: Renderer,
) -> Path:
    """Merge this run into the folder's metadata.json: participants and one entry per topic."""
    path = folder / METADATA_FILE
    data: dict[str, object] = (
        cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        if path.exists()
        else {}
    )
    records = [
        renderer.data({key: value for key, value in asdict(p).items() if value})
        for p in participants
    ]
    data["participants"] = merge_participants(records_of(data.get("participants")), records)
    topics = records_of(data.get("topics"))
    for earlier, entry in topic_entries:
        entry = renderer.data(entry)
        match = next((t for t in topics if earlier and t.get("file") == earlier), None)
        if match is None:
            topics.append(entry)
        else:
            merged = merge_metadata(match, entry)
            merged["file"] = entry["file"]
            merged["participants"] = list(dict.fromkeys([*_names(match), *_names(entry)]))
            topics[topics.index(match)] = merged
    data["topics"] = topics
    write_text(path, to_json(data) + "\n")
    return path


def _names(entry: dict[str, object]) -> list[str]:
    value = entry.get("participants")
    return [str(item) for item in cast(list[object], value)] if isinstance(value, list) else []
