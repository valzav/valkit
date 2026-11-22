"""Read the raw bytes that the mailbox returns."""

import email
import email.policy
from email.message import EmailMessage

from bs4 import BeautifulSoup

from valkit.email_extractor.addresses import parse_addresses
from valkit.email_extractor.parse import source_of
from valkit.mailkeeper.model import EmailText, Header
from valkit.mailkeeper.trust import authenticated

# Tags that end a line of visible text.
BLOCK_TAGS = [
    "address", "blockquote", "div", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "li", "ol", "p", "pre", "table", "td", "th", "tr", "ul",
]  # fmt: skip


def _parse(data: bytes) -> EmailMessage:
    message = email.message_from_bytes(data, policy=email.policy.default)
    assert isinstance(message, EmailMessage)
    return message


def _header(message: EmailMessage, name: str) -> str:
    return " ".join(str(message.get(name, "")).split())


def read_header(uid: int, data: bytes, authserv_id: str) -> Header:
    message = _parse(data)
    from_text = _header(message, "From")
    senders = parse_addresses(from_text)
    sender = senders[0].email if len(senders) == 1 else ""
    results = [str(value) for value in message.get_all("Authentication-Results") or []]
    return Header(
        uid=uid,
        message_id=str(message.get("Message-ID", "")).strip(),
        sender=sender,
        from_text=from_text,
        subject=_header(message, "Subject"),
        date=_header(message, "Date"),
        authentic=authenticated(results, sender.rpartition("@")[2], authserv_id),
    )


def read_text(data: bytes) -> EmailText:
    message = _parse(data)
    source = source_of(message)
    text = source.text if source.text and source.text.strip() else ""
    if not text and source.html:
        text = visible_text(source.html)
    return EmailText(
        sender=_header(message, "From"),
        to=_header(message, "To"),
        cc=_header(message, "Cc"),
        date=_header(message, "Date"),
        subject=_header(message, "Subject"),
        text=text.strip(),
    )


def visible_text(html: str) -> str:
    """The text a reader sees, without link addresses or markup.

    The detector was tested on text in this form. Given the same email as Markdown with its
    link addresses, it judged a phishing email as a service notice.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["style", "script", "head", "title"]):
        tag.decompose()
    for line_break in soup("br"):
        line_break.replace_with("\n")
    for block in soup(BLOCK_TAGS):
        block.append("\n")
    lines = (" ".join(line.split()) for line in soup.get_text().splitlines())
    return "\n".join(line for line in lines if line)
