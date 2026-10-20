"""Read an .eml file: top-level headers plus the text body. Attachments and images are ignored."""

import email
import email.policy
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

from valkit.email_extractor.addresses import parse_addresses
from valkit.email_extractor.model import Address, Message


@dataclass
class Source:
    top: Message
    html: str | None
    text: str | None


class NotAnEmailError(ValueError):
    """The file has no email headers: an output file, a log, or an unrelated file."""


def load(path: Path) -> Source:
    message = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    assert isinstance(message, EmailMessage)
    if not message.get("From"):
        raise NotAnEmailError(f"{path} is not an email (no From header)")
    return Source(
        top=_top_message(message),
        html=_body(message, "html"),
        text=_body(message, "plain"),
    )


def _body(message: EmailMessage, subtype: str) -> str | None:
    part = message.get_body(preferencelist=(subtype,))
    if part is None:
        return None
    content = part.get_content()
    return content if isinstance(content, str) else None


def _top_message(message: EmailMessage) -> Message:
    senders = parse_addresses(str(message.get("From", "")))
    date_text = str(message.get("Date", ""))
    try:
        # Quoted messages carry no timezone, so drop it here too to keep dates comparable.
        date = parsedate_to_datetime(date_text).replace(tzinfo=None)
    except TypeError, ValueError:
        date = None
    return Message(
        sender=senders[0] if senders else Address("", ""),
        to=parse_addresses(str(message.get("To", ""))),
        cc=parse_addresses(str(message.get("Cc", ""))),
        date=date,
        date_text=date_text,
        subject=str(message.get("Subject", "")),
        body="",
    )
