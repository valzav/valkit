"""Split a quoted email thread into individual messages, oldest first."""

import re
from dataclasses import replace
from datetime import datetime, timedelta
from typing import cast

from dateutil import parser as dateparser
from mailparser_reply.parser import EmailMessage  # pyright: ignore[reportMissingTypeStubs]

from valkit.email_extractor.addresses import clean_name, parse_addresses
from valkit.email_extractor.model import Address, Message

QUOTE_PREFIX_RE = re.compile(r"^(?:> ?)+", re.MULTILINE)
SUBJECT_PREFIX_RE = re.compile(r"^\s*(?:(?:re|fw|fwd)\s*:\s*)+", re.IGNORECASE)
TIME = r"\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp]\.?[Mm]\.?)?"
WROTE_RE = re.compile(
    rf"On\s+(?P<date>.*?{TIME}),?\s+(?P<name>.*?),?\s*(?:<(?P<email>[^>]+)>)?\s*wrote:",
    re.IGNORECASE | re.DOTALL,
)
FIELD_RE = re.compile(r"^(From|Sent|Date|To|Cc|Subject):\s*(.*)$", re.IGNORECASE)
TRAILING_NOISE_RE = re.compile(
    r"(?:\n\s*(?:-{3,}|_{3,}|\*{3,}|-+ ?(?:Forwarded|Original) message ?-+))+\s*\Z",
    re.IGNORECASE,
)

# Gmail in Russian writes reply headers as "<weekday>, <day> <month>. <year> г. в <time>, Name <email>:".  # noqa: E501, RUF003
# The reply parser has no Russian support, so these headers are rewritten into the English
# "On <date>, Name <email> wrote:" form. The Cyrillic letters below are intentional.
RUSSIAN_HEADER_RE = re.compile(
    r"^(?P<quote>(?:> ?)*)(?:[а-я]{2},\s+)?"  # noqa: RUF001
    r"(?P<day>\d{1,2})\s+(?P<month>[а-я]+)\.?\s+(?P<year>\d{4})"  # noqa: RUF001
    r"\s+г\.\s+в\s+(?P<time>\d{1,2}:\d{2}),?\s+(?P<who>.+?):\s*$",  # noqa: RUF001
    re.MULTILINE | re.IGNORECASE,
)
RUSSIAN_MONTHS = {
    "янв": "Jan", "фев": "Feb", "мар": "Mar", "апр": "Apr", "мая": "May", "май": "May",
    "июн": "Jun", "июл": "Jul", "авг": "Aug", "сен": "Sep", "окт": "Oct", "ноя": "Nov",
    "дек": "Dec",
}  # fmt: skip

# The widest gap between two UTC offsets (UTC+14 to UTC-12). Quoted copies of one message
# show its time in each quoting client's local zone, so copies can differ by this much.
MAX_ZONE_SPREAD = timedelta(hours=26)


def topic(subject: str) -> str:
    return SUBJECT_PREFIX_RE.sub("", subject).strip()


def translate_russian_headers(markdown: str) -> str:
    def english(match: re.Match[str]) -> str:
        month = RUSSIAN_MONTHS.get(match.group("month")[:3].lower())
        if month is None:
            return match.group(0)
        date = f"{match.group('day')} {month} {match.group('year')} {match.group('time')}"
        return f"{match.group('quote')}On {date}, {match.group('who')} wrote:"

    return RUSSIAN_HEADER_RE.sub(english, markdown)


def compact_headers(markdown: str) -> str:
    """Rejoin Outlook header blocks that HTML conversion spread over blank and wrapped lines.

    The reply parser only recognises From/Sent/To/Cc/Subject when they sit on consecutive lines.
    """
    lines = [line.replace("\xa0", " ").rstrip() for line in markdown.splitlines()]
    out: list[str] = []
    in_header = False
    for index, line in enumerate(lines):
        bare = _bare(line)
        if FIELD_RE.match(bare) and (in_header or _starts_dated_header(lines, index)):
            in_header = True
            out.append(line)
        elif in_header and not bare:
            following = next((_bare(rest) for rest in lines[index + 1 :] if _bare(rest)), "")
            if not FIELD_RE.match(following):
                in_header = False
                out.append(line)
        elif in_header and (previous := FIELD_RE.match(_bare(out[-1]))):
            # Only address lists wrap; a line after Subject is already the body.
            if previous.group(1).lower() not in {"from", "to", "cc"}:
                in_header = False
                out.append(line)
                continue
            out[-1] += " " + bare
        else:
            in_header = False
            out.append(line)
    return "\n".join(out)


def _starts_dated_header(lines: list[str], start: int) -> bool:
    """Whether the field block at `start` has a Sent/Date field, as every real reply header does.

    Prose such as "From: Plan A / To: Plan B" has none and must stay untouched.
    """
    previous_field = ""
    for line in lines[start:]:
        bare = _bare(line)
        field = FIELD_RE.match(bare)
        if field:
            if field.group(1).lower() in {"sent", "date"}:
                return True
            previous_field = field.group(1).lower()
        elif not bare:
            previous_field = ""
        elif previous_field not in {"from", "to", "cc"}:
            # Text that is not a wrapped address list ends the block.
            return False
    return False


def _bare(line: str) -> str:
    return QUOTE_PREFIX_RE.sub("", line).replace("*", "").strip()


def split_thread(markdown: str, top: Message) -> list[Message]:
    markdown = compact_headers(translate_russian_headers(markdown))
    messages: list[Message] = []
    for header, text, body_text in _replies(markdown):
        content = _clean_body(text)
        body = _clean_body(body_text)
        if not header:
            messages.append(replace(top, body=body))
            continue
        message = _parse_header(header)
        if message is not None:
            messages.append(replace(message, body=body))
        elif messages:
            # A header we cannot read: keep the text with the previous message rather than lose it.
            messages[-1].body += "\n\n" + content
    messages.reverse()
    _inherit_subjects(messages)
    return _deduplicate(messages)


def _replies(markdown: str) -> list[tuple[str, str, str]]:
    """The thread cut at each reply header, newest first: (header, text, text after the header).

    `mailparser_reply` finds each header by searching for its text from one character past the
    previous header. A header such as "On ... wrote:" also occurs inside a quoted copy of itself
    ("> On ... wrote:"), so when a client repeats the oldest message after the quoted block, the
    search lands inside the quote and gives that message's text to the wrong reply. Cutting at
    the positions where the library's own header pattern matches avoids the search.
    """
    parsed = EmailMessage(text=markdown, languages=["en"])
    text = str(parsed.text)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    pattern = cast(re.Pattern[str], parsed.HEADER_REGEX)  # pyright: ignore[reportUnknownMemberType]
    matches = list(pattern.finditer(text))
    bounds = [match.start() for match in matches] + [len(text)]
    replies = [("", text[: bounds[0]], text[: bounds[0]])]
    for match, end in zip(matches, bounds[1:], strict=True):
        replies.append((match.group(0).strip(), text[match.start() : end], text[match.end() : end]))
    # Like the library, drop a part with no text, such as the empty top of a forwarded email.
    return [reply for reply in replies if reply[1].strip()]


def _clean_body(text: str) -> str:
    text = QUOTE_PREFIX_RE.sub("", text)
    text = TRAILING_NOISE_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _parse_header(header: str) -> Message | None:
    text = QUOTE_PREFIX_RE.sub("", header).replace("\u202f", " ").replace("\xa0", " ")
    wrote = WROTE_RE.search(text)
    if wrote:
        name = clean_name(wrote.group("name"))
        email = (wrote.group("email") or "").strip().lower()
        return _message(Address(name, email), [], [], wrote.group("date"), "")
    fields: dict[str, str] = {}
    current = ""
    for line in text.replace("*", "").splitlines():
        found = FIELD_RE.match(line.strip())
        if found:
            current = found.group(1).lower()
            fields[current] = found.group(2).strip()
        elif current and line.strip():
            fields[current] += " " + line.strip()
    if "from" not in fields or not (fields.get("sent") or fields.get("date")):
        # Prose such as "From: X / To: Y" also matches; a real header always carries a date.
        return None
    senders = parse_addresses(fields["from"])
    return _message(
        senders[0] if senders else Address("", ""),
        parse_addresses(fields.get("to", "")),
        parse_addresses(fields.get("cc", "")),
        fields.get("sent") or fields.get("date", ""),
        fields.get("subject", ""),
    )


def _message(
    sender: Address, to: list[Address], cc: list[Address], date_text: str, subject: str
) -> Message:
    date_text = " ".join(date_text.split())
    return Message(sender, to, cc, _parse_date(date_text), date_text, subject, body="")


def _parse_date(text: str) -> datetime | None:
    try:
        return dateparser.parse(text, fuzzy=True, ignoretz=True)
    except ValueError, OverflowError:
        return None


def _inherit_subjects(messages: list[Message]) -> None:
    """Gmail-style reply headers carry no subject.

    A reply keeps the subject of the message before it.
    """
    previous = ""
    for message in messages:
        message.subject = message.subject or previous
        previous = message.subject


def _deduplicate(messages: list[Message]) -> list[Message]:
    """Forwarded chains repeat messages already in the thread. Keep the first copy."""
    kept: list[Message] = []
    for message in messages:
        if not any(_same(message, other) for other in kept):
            kept.append(message)
    return kept


def _same(a: Message, b: Message) -> bool:
    if fingerprint(a.body) != fingerprint(b.body):
        return False
    if not _same_sender(a.sender, b.sender):
        return False
    if a.date and b.date:
        return abs(a.date - b.date) <= MAX_ZONE_SPREAD
    return True


def _same_sender(a: Address, b: Address) -> bool:
    if a.email and b.email:
        return a.email == b.email
    return a.name.lower() == b.name.lower()


def fingerprint(body: str) -> str:
    return re.sub(r"[\W_]+", "", body).lower()
