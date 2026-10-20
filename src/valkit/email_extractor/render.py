"""Render a thread as Markdown, and its participants and dates as JSON metadata."""

import json
import re
from collections.abc import Callable
from dataclasses import asdict
from typing import cast

from valkit.email_extractor.contacts import TEL_LINK_RE
from valkit.email_extractor.model import Address, Message, Participant
from valkit.email_extractor.split import topic


def title_of(messages: list[Message], fallback: str) -> str:
    return topic(messages[-1].subject) if messages else fallback


def date_range(messages: list[Message]) -> list[str]:
    dates = [message.date for message in messages if message.date]
    return [min(dates).date().isoformat(), max(dates).date().isoformat()] if dates else []


def metadata(
    messages: list[Message], participants: list[Participant], source: str
) -> dict[str, object]:
    data: dict[str, object] = {
        "subject": title_of(messages, source),
        "sources": [source],
        "messages": len(messages),
    }
    if dates := date_range(messages):
        data["date_range"] = dates
    data["participants"] = [
        {key: value for key, value in asdict(participant).items() if value}
        for participant in participants
    ]
    return data


def frontmatter(data: object) -> str:
    return f"---\n{to_json(data)}\n---\n\n"


FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n\n", re.DOTALL)


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """The JSON frontmatter of a rendered document, and the rest of it."""
    found = FRONTMATTER_RE.match(text)
    if not found:
        return {}, text
    return cast(dict[str, object], json.loads(found.group(1))), text[found.end() :]


def merge_metadata(old: dict[str, object], new: dict[str, object]) -> dict[str, object]:
    """Combine the metadata of a document with that of messages appended to it."""
    merged = dict(old)
    merged["sources"] = _union(_strings(old.get("sources")), _strings(new.get("sources")))
    merged["messages"] = _number(old.get("messages")) + _number(new.get("messages"))
    if dates := sorted([*_strings(old.get("date_range")), *_strings(new.get("date_range"))]):
        merged["date_range"] = [dates[0], dates[-1]]
    merged["participants"] = merge_participants(
        records_of(old.get("participants")), records_of(new.get("participants"))
    )
    return merged


def merge_participants(
    old: list[dict[str, object]], new: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Union of participant records, matched by email address or else by name."""
    merged = [dict(record) for record in old]
    for record in new:
        match = next((m for m in merged if _same_person(m, record)), None)
        if match is None:
            merged.append(dict(record))
            continue
        for field, value in record.items():
            if isinstance(value, list):
                match[field] = _union(_strings(match.get(field)), _strings(cast(object, value)))
            elif not match.get(field):
                match[field] = value
    return merged


def _same_person(a: dict[str, object], b: dict[str, object]) -> bool:
    emails = set(_strings(a.get("emails"))) & set(_strings(b.get("emails")))
    names = {str(a.get("name", "")).lower(), str(b.get("name", "")).lower()}
    return bool(emails) or (len(names) == 1 and "" not in names)


def _union(first: list[str], second: list[str]) -> list[str]:
    return [*first, *(value for value in second if value not in first)]


def _strings(value: object) -> list[str]:
    return [str(item) for item in cast(list[object], value)] if isinstance(value, list) else []


def records_of(value: object) -> list[dict[str, object]]:
    items = cast(list[object], value) if isinstance(value, list) else []
    return [cast(dict[str, object], item) for item in items if isinstance(item, dict)]


def _number(value: object) -> int:
    return value if isinstance(value, int) else 0


def to_json(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def name_of(address: Address) -> str:
    return address.name or address.email or "Unknown sender"


def document(messages: list[Message], title: str, name: Callable[[Address], str] = name_of) -> str:
    parts = [f"# {title}"]
    # Topic headings only help when the document holds more than one topic.
    single_topic = len({topic(message.subject) or title for message in messages}) == 1
    current_topic: str | None = None
    for index, message in enumerate(messages):
        message_topic = topic(message.subject) or title
        if message_topic != current_topic and not single_topic:
            parts.append(f"## {message_topic}")
        elif index:
            parts.append("---")
        current_topic = message_topic
        parts.append(_message(message, name))
    return "\n\n".join(parts) + "\n"


def continuation(
    existing: str,
    messages: list[Message],
    name: Callable[[Address], str] = name_of,
    label: Callable[[str], str] = lambda text: text,
) -> str:
    """Markdown for messages added at the end of a rendered document.

    It continues the document's topic headings: a message on the current topic follows a
    separator, a new topic gets its own heading. `label` turns a topic into heading text the way
    the document did (strict mode scrubs it).
    """
    headings = re.findall(r"^## (.*)$", existing, re.MULTILINE)
    current = (headings or re.findall(r"^# (.*)$", existing, re.MULTILINE) or [""])[-1]
    parts: list[str] = []
    for message in messages:
        message_topic = label(topic(message.subject)) or current
        if message_topic != current:
            parts.append(f"## {message_topic}")
            current = message_topic
        else:
            parts.append("---")
        parts.append(_message(message, name))
    return "\n\n".join(parts) + "\n"


def _message(message: Message, name: Callable[[Address], str]) -> str:
    when = message.date.strftime("%Y-%m-%d %H:%M") if message.date else message.date_text
    heading = f"### {name(message.sender)}" + (f" · {when}" if when else "")
    recipients = [
        f"**{label}:** {', '.join(name(address) for address in addresses)}"
        for label, addresses in (("To", message.to), ("Cc", message.cc))
        if addresses
    ]
    body = join_paragraph_lines(TEL_LINK_RE.sub(r"\1", message.body))
    return "\n\n".join([heading, *([" · ".join(recipients)] if recipients else []), body])


LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
# Lines that are blocks of their own: headings, quotes, table rows and horizontal rules.
BLOCK_LINE_RE = re.compile(r"^\s*(?:#|>|\|)|^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
FENCE_RE = re.compile(r"^\s*(?:```|~~~)")


def join_paragraph_lines(text: str) -> str:
    """Join the lines of each paragraph into one line; a blank line separates paragraphs.

    Headings, quotes, tables, rules and code blocks keep their line structure. List items start a
    new line, and a plain line after one joins it, as Markdown reads it anyway.
    """
    out: list[str] = []
    joinable = False
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
        if FENCE_RE.match(line) or in_fence or not line.strip() or BLOCK_LINE_RE.match(line):
            out.append(line)
            joinable = False
        elif joinable and not LIST_ITEM_RE.match(line):
            out[-1] = f"{out[-1].rstrip()} {line.strip()}"
        else:
            out.append(line)
            joinable = True
    return "\n".join(out)
