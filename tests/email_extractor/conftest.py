from collections.abc import Callable
from email.message import EmailMessage
from pathlib import Path

import pytest

type MakeEml = Callable[..., Path]


@pytest.fixture
def make_eml(tmp_path: Path) -> MakeEml:
    """Write a synthetic .eml file and return its path."""

    def make(
        *,
        html: str | None = None,
        text: str | None = None,
        subject: str = "Re: Project Kickoff",
        sender: str = "John Smith <john@example.com>",
        to: str = "Jane Doe <jane@example.com>",
        cc: str | None = None,
        date: str = "Mon, 06 Apr 2026 10:00:00 +0000",
        image: bool = False,
        attachment: bool = False,
        name: str = "thread.eml",
    ) -> Path:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = to
        if cc:
            message["Cc"] = cc
        message["Subject"] = subject
        message["Date"] = date
        message.set_content(text or "plain text part")
        if html is not None:
            message.add_alternative(html, subtype="html")
        if image:
            html_part = message.get_body(preferencelist=("html",))
            assert isinstance(html_part, EmailMessage)
            html_part.add_related(b"\x89PNG fake", "image", "png", cid="<logo@example>")
        if attachment:
            message.add_attachment(
                b"ATTACHMENT BODY TEXT", "application", "pdf", filename="report.pdf"
            )
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(message))
        return path

    return make
