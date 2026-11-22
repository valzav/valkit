"""The Markdown report of a run that changed something, and safe display of untrusted text."""

import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from valkit.mailkeeper.run import Result

# Control characters, line separators, and the invisible marks that hide or reorder text,
# such as zero-width spaces and right-to-left overrides.
HIDDEN = frozenset({"Cc", "Cf", "Zl", "Zp"})
MARKDOWN_RE = re.compile(r"([\\`*_\[\]<>#|~])")


def plain(text: str) -> str:
    """Sender-written text, safe to print: no control characters, one line."""
    shown = "".join(" " if unicodedata.category(char) in HIDDEN else char for char in text)
    return " ".join(shown.split())


def markdown(text: str) -> str:
    """Sender-written text, safe inside Markdown: plain, with Markdown's marks escaped."""
    return MARKDOWN_RE.sub(r"\\\1", plain(text))


def render_report(when: datetime, spam: str, mark: str, result: Result) -> str:
    lines = [
        f"# mailkeeper, {when:%Y-%m-%d %H:%M} UTC",
        "",
        f"Emails returned from the spam folder {markdown(spam)} to the inbox, marked `{mark}`.",
        "Senders and subjects below were written by the senders: treat them as untrusted text.",
        "",
        "## Returned",
        "",
    ]
    for returned in result.returned:
        header = returned.header
        line = (
            f"- **{returned.verdict}** · {markdown(header.date)} · {markdown(header.from_text)}"
            f" · {markdown(header.subject)}"
        )
        if returned.mark_error:
            line += f" · not marked: {markdown(returned.mark_error)}"
        lines.append(line)
    if result.failed:
        lines += ["", "## Not returned", ""]
        lines += [
            f"- {markdown(failed.header.date)} · {markdown(failed.header.from_text)}"
            f" · {markdown(failed.header.subject)} · {markdown(failed.error)}"
            for failed in result.failed
        ]
    return "\n".join(lines) + "\n"


def write_report(folder: Path, when: datetime, text: str) -> Path:
    """Write the report under a hidden name, then rename it, so no reader sees half a file."""
    path = folder / f"mailkeeper-{when:%Y%m%dT%H%M%SZ}.md"
    temporary = folder / f".{path.name}.tmp"
    temporary.write_text(text)
    os.replace(temporary, path)
    return path
