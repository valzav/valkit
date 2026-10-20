"""Remove signatures from message bodies, keeping the removed text for contact extraction."""

import re
from collections import defaultdict

import phonenumbers

from valkit.email_extractor.addresses import EMAIL_RE
from valkit.email_extractor.model import Address, Message

SIGN_OFF_RE = re.compile(
    r"^(?:best|best regards|kind regards|warm regards|warmly|regards|thanks|thank you|many thanks"
    r"|cheers|sincerely|mahalo|all the best|br|--)[\s,.!]*$",
    re.IGNORECASE,
)
SENT_FROM_RE = re.compile(r"^(?:sent from my|get outlook for)\b", re.IGNORECASE)
PS_RE = re.compile(r"^\W*p\.?\s?s\b", re.IGNORECASE)
LINK_RE = re.compile(r"\]\(|https?://|www\.")


def strip_signatures(messages: list[Message]) -> None:
    """Remove each message's signature and keep it in `message.signature`.

    A "--" delimiter, or a sign-off followed by the sender's name, starts a signature that runs to
    the end of the message (a PS after a sign-off is kept). Without those, the cut starts at the
    sender's name line and extends over lines that look like signature material: blank, links,
    emails, phone numbers, or lines that also appear in another message from the same sender.
    Text after that stays in the body.
    """
    by_sender: defaultdict[str, list[Message]] = defaultdict(list)
    for message in messages:
        by_sender[message.sender.key].append(message)
    # Collect repeated lines before changing any body.
    seen_elsewhere = {
        id(message): {
            _normalize(line)
            for other in by_sender[message.sender.key]
            if other is not message
            for line in other.body.splitlines()
        }
        for message in messages
    }
    for message in messages:
        lines = message.body.splitlines()
        names = _names(message.sender)
        closing = _closing(lines, names)
        if closing:
            start, end = closing
        else:
            start = _name_line(lines, names)
            if start is None:
                continue
            end = start + 1
            # Lines directly under the name (title, company, phone) belong to it, up to a blank.
            while end < len(lines) and lines[end].strip() and not PS_RE.match(lines[end]):
                end += 1
            while end < len(lines) and _signature_like(lines[end], seen_elsewhere[id(message)]):
                end += 1
        start = _sign_off_start(lines, start, names)
        # A blank line keeps text after the signature (a PS) a paragraph of its own.
        kept = [*lines[:start], "", *lines[end:]] if end < len(lines) else lines[:start]
        if not "".join(kept).strip():
            # The whole body looks like a signature; keep it rather than emit an empty message.
            continue
        message.signature = "\n".join(lines[start:end]).strip()
        message.body = "\n".join(kept).strip()


def _closing(lines: list[str], names: set[str]) -> tuple[int, int] | None:
    """A signature block that runs to the end of the message, as (start, end) line indexes.

    It starts at the first "--" delimiter line (the standard signature separator) or the first
    sign-off line ("Best,", "Thanks") followed by the sender's name, whichever comes first.
    Requiring the name keeps a "Thanks!" in the middle of a message from cutting off the rest.
    A PS after the signature is kept.
    """
    starts = [
        i
        for i, line in enumerate(lines)
        if line.strip() == "--"
        or (SIGN_OFF_RE.match(_normalize(line)) and _name_follows(lines, i, names))
    ]
    if not starts:
        return None
    ps = next((j for j in range(starts[0] + 1, len(lines)) if PS_RE.match(lines[j])), len(lines))
    return starts[0], ps


def _name_follows(lines: list[str], index: int, names: set[str]) -> bool:
    """Whether the next line is the sender's name, alone or opening a signature line."""
    following = next((_bare_line(line) for line in lines[index + 1 :] if line.strip()), "")
    full = max(names, key=len, default="")
    return following in names or bool(full and following.startswith(f"{full} "))


def _normalize(line: str) -> str:
    return re.sub(r"[*_\s]+", " ", line).strip().lower()


def _signature_like(line: str, seen_elsewhere: set[str]) -> bool:
    normalized = _normalize(line)
    return (
        not normalized
        or normalized in seen_elsewhere
        or bool(LINK_RE.search(line) or EMAIL_RE.search(line))
        or any(phonenumbers.PhoneNumberMatcher(line, None))
    )


def _names(sender: Address) -> set[str]:
    """The sender's full and first name, as they appear on a sign-off line."""
    if not sender.name:
        return set()
    return {_normalize(sender.name), _normalize(sender.name.split()[0])}


def _bare_line(line: str) -> str:
    return _normalize(line).strip(",.!")


def _name_line(lines: list[str], names: set[str]) -> int | None:
    """Index of the last line that is the sender's name, or a signature marker."""
    for i in range(len(lines) - 1, -1, -1):
        line = _bare_line(lines[i])
        if line in names or SENT_FROM_RE.match(line) or line == "--":
            return i
    return None


def _sign_off_start(lines: list[str], cut: int, names: set[str]) -> int:
    """Move the cut up over sign-offs ("Best,", "Thanks", the sender's name) and blank lines."""
    while cut > 0:
        line = lines[cut - 1]
        if (
            line.strip()
            and not SIGN_OFF_RE.match(_normalize(line))
            and _bare_line(line) not in names
        ):
            break
        cut -= 1
    return cut
