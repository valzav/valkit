import email
import email.policy
from email.message import EmailMessage

from valkit.email_extractor.parse import source_of

UNKNOWN_CHARSET = (
    b"From: deals@shop.test\n"
    b"To: owner@example.test\n"
    b"Subject: Sale\n"
    b"Content-Type: text/plain; charset=x-no-such-charset\n"
    b"\n"
    b"Save today\n"
)


def test_a_body_in_an_unknown_charset_is_read_as_utf8() -> None:
    message = email.message_from_bytes(UNKNOWN_CHARSET, policy=email.policy.default)
    assert isinstance(message, EmailMessage)

    source = source_of(message)

    assert source.text == "Save today\n"
    assert source.top.subject == "Sale"
