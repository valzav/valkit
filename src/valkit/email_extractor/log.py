"""The processing log: which messages were already written to this folder, and to which file.

The log holds message hashes and output file names only, never names or message text, so it is
safe next to strict-mode output.
"""

import hashlib
import json
from pathlib import Path
from typing import cast

from valkit.email_extractor.files import write_text
from valkit.email_extractor.model import Message
from valkit.email_extractor.split import fingerprint

LOG_FILE = ".email-extractor.json"
VERSION = 1
# Strict files carry their own ending, so strict and normal output never share a file name and a
# file meant for sharing can never be overwritten with full personal details.
STRICT_EXTENSION = ".strict.md"


def message_key(message: Message) -> str:
    """Identity of a message across exports: its sender and its normalised text.

    Computed before signature removal, so changes to the signature rules keep old logs valid.
    """
    text = f"{message.sender.key}\n{fingerprint(message.body)}"
    return hashlib.sha256(text.encode()).hexdigest()


class ProcessedLog:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.path = folder / LOG_FILE
        data: dict[str, object] = (
            cast(dict[str, object], json.loads(self.path.read_text(encoding="utf-8")))
            if self.path.exists()
            else {}
        )
        # Output format, then message key, then the file name it was written to.
        self._formats = cast(dict[str, dict[str, str]], data.get("formats", {}))

    def file_of(self, output_format: str, key: str) -> str | None:
        """The file holding this message, if it still exists; a deleted file means "not done".

        The log is a plain file in a folder others may share, so a name from it is used only if
        it is a Markdown file directly inside this folder and not a symlink, and its ending fits the
        format: strict output only in strict files, normal output never in one. Anything else
        counts as "not done" rather than letting the log point the tool at another file.
        """
        name = self._formats.get(output_format, {}).get(key)
        if not name or not _is_plain_name(name):
            return None
        if not fits_format(name, output_format):
            return None
        path = self.folder / name
        if path.is_symlink() or not path.is_file():
            return None
        # On a case-insensitive disk "a.STRICT.md" opens "a.strict.md"; only the exact name counts.
        if name not in {entry.name for entry in self.folder.iterdir()}:
            return None
        return name if path.resolve().parent == self.folder.resolve() else None

    def owners(self, file_name: str) -> set[str]:
        """The output formats that have written to this file, matched in any case like the disk."""
        name = file_name.casefold()
        return {
            fmt
            for fmt, entries in self._formats.items()
            if name in {entry.casefold() for entry in entries.values()}
        }

    def record(self, output_format: str, keys: list[str], file_name: str) -> None:
        entries = self._formats.setdefault(output_format, {})
        for key in keys:
            entries[key] = file_name

    def rename(self, output_format: str, old: str, new: str) -> None:
        entries = self._formats.get(output_format, {})
        for key, name in entries.items():
            if name == old:
                entries[key] = new

    def save(self) -> None:
        data = {"version": VERSION, "formats": self._formats}
        write_text(self.path, json.dumps(data, indent=1, sort_keys=True) + "\n")


def fits_format(file_name: str, output_format: str) -> bool:
    """Strict output goes only into strict files, and normal output never does."""
    return file_name.casefold().endswith(STRICT_EXTENSION) == output_format.endswith("-strict")


def _is_plain_name(name: str) -> bool:
    return name == Path(name).name and name not in {".", ".."} and name.casefold().endswith(".md")
