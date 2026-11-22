import json
from email.message import EmailMessage
from pathlib import Path

import pytest

from valkit.mailkeeper.config import Config, parse_config
from valkit.mailkeeper.mailbox import MailboxError
from valkit.mailkeeper.model import EmailText

AUTHSERV = "mx.example.test"
OWNER = "owner@example.test"


def config_data(**changes: object) -> dict[str, object]:
    data: dict[str, object] = {
        "imap": {"host": "imap.example.test", "user": OWNER, "password_env": "TEST_IMAP_PASSWORD"},
        "model": {"base_url": "http://127.0.0.1:9/v1", "name": "test-model"},
        "owner": {"name": "Alex", "description": "Alex (owner@example.test), a software founder"},
        "own_addresses": [OWNER],
        "own_domains": ["example.test", "club.example"],
        "mark": "unspam",
        "report_dir": "~/reports",
        "authserv_id": AUTHSERV,
    }
    data.update(changes)
    return data


@pytest.fixture
def config() -> Config:
    return parse_config(json.dumps(config_data()))


def passing(domain: str) -> str:
    return (
        f"{AUTHSERV}; dkim=pass header.i=@{domain}; spf=pass smtp.mailfrom=bounce@{domain};"
        f" dmarc=pass (p=NONE sp=NONE dis=NONE) header.from={domain}"
    )


def make_email(
    sender: str,
    subject: str,
    *,
    auth: str | None = "pass",
    message_id: str | None = None,
    text: str = "Hello.",
    to: str = OWNER,
) -> bytes:
    """A synthetic email. `auth="pass"` adds a passing Authentication-Results header."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = "Sat, 21 Nov 2026 15:00:00 +0000"
    if message_id is None:
        message_id = f"<{abs(hash((sender, subject)))}@mail.test>"
    if message_id:
        message["Message-ID"] = message_id
    if auth is not None:
        domain = sender.rpartition("@")[2].rstrip(">")
        message["Authentication-Results"] = passing(domain) if auth == "pass" else auth
    message.set_content(text)
    return message.as_bytes()


class FakeMailbox:
    """An in-memory mailbox. `writes` records every change, in order."""

    def __init__(self) -> None:
        self.spam = "Junk"
        self.folders: dict[str, dict[int, bytes]] = {"Junk": {}, "INBOX": {}}
        self.uidvalidity = 7
        self.sent_to: set[str] = set()
        self.searched: list[str] = []
        self.writes: list[str] = []
        self.fail_moves: set[int] = set()
        self.fail_marks = False
        self._next_uid = 1

    def add(self, folder: str, data: bytes) -> int:
        uid = self._next_uid
        self._next_uid += 1
        self.folders[folder][uid] = data
        return uid

    def uids(self, folder: str) -> tuple[int, list[int]]:
        return self.uidvalidity, sorted(self.folders[folder])

    def headers(self, folder: str, uids: list[int]) -> dict[int, bytes]:
        return {uid: self.folders[folder][uid] for uid in uids if uid in self.folders[folder]}

    def messages(self, folder: str, uids: list[int]) -> dict[int, bytes]:
        return self.headers(folder, uids)

    def wrote_to(self, address: str) -> bool:
        self.searched.append(address)
        return address in self.sent_to

    def move_to_inbox(self, folder: str, uid: int) -> int | None:
        if uid in self.fail_moves:
            raise MailboxError("move refused")
        new_uid = self.add("INBOX", self.folders[folder].pop(uid))
        self.writes.append(f"move {uid} -> {new_uid}")
        return new_uid

    def mark(self, uid: int, mark: str) -> None:
        if self.fail_marks:
            raise MailboxError("mark refused")
        self.writes.append(f"mark {uid} {mark}")


class FakeDetector:
    """Answers by subject; a subject mapped to None gets a reply that breaks the schema."""

    def __init__(self, verdicts: dict[str, str | None]) -> None:
        self.verdicts = verdicts
        self.calls: list[str] = []

    def __call__(self, email: EmailText) -> str | None:
        self.calls.append(email.subject)
        return self.verdicts[email.subject]


@pytest.fixture
def mailbox() -> FakeMailbox:
    return FakeMailbox()


@pytest.fixture
def report_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "reports"
    folder.mkdir()
    return folder
