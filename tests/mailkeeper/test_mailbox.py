import imaplib
from typing import Any, cast

import pytest

from valkit.mailkeeper.mailbox import ImapMailbox, MailboxError, sequence_set, special_folders

from .conftest import make_email

SPAM = "[Gmail]/Spam"
SENT = "[Gmail]/Sent Mail"
LIST = [
    b'(\\HasNoChildren) "/" "INBOX"',
    b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"',
    b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
]
type Result = tuple[str, list[Any]]


def _uids(spec: str) -> list[int]:
    found: list[int] = []
    for part in spec.split(","):
        first, _, last = part.partition(":")
        found += range(int(first), int(last or first) + 1)
    return found


class FakeImap:
    """Answers the imaplib calls ImapMailbox makes, and records every command."""

    def __init__(self, capabilities: str = "IMAP4rev1 MOVE UIDPLUS SPECIAL-USE X-GM-EXT-1"):
        self.capabilities_text = capabilities
        self.permanent_flags = b"(\\Seen \\Flagged \\*)"
        self.commands: list[tuple[str, ...]] = []
        self.folders: dict[str, dict[int, bytes]] = {"INBOX": {}, SPAM: {}, SENT: {}}
        self.selected = ""
        self.readonly = True
        self._untagged: dict[str, list[Any]] = {}
        self._next_uid = 100

    def login(self, user: str, password: str) -> Result:
        self.commands.append(("LOGIN", user))
        return "OK", [b"logged in"]

    def capability(self) -> Result:
        return "OK", [self.capabilities_text.encode()]

    def list(self) -> Result:
        return "OK", list(LIST)

    def select(self, mailbox: str, readonly: bool = False) -> Result:
        name = mailbox.strip('"')
        self.selected, self.readonly = name, readonly
        self.commands.append(("EXAMINE" if readonly else "SELECT", name))
        self._untagged = {"UIDVALIDITY": [b"9"], "PERMANENTFLAGS": [self.permanent_flags]}
        return "OK", [str(len(self.folders[name])).encode()]

    def response(self, code: str) -> Result:
        return code, self._untagged.pop(code, [None])

    def uid(self, command: str, *args: str) -> Result:
        self.commands.append(("UID", command, *args))
        folder = self.folders[self.selected]
        if command == "SEARCH" and args == ("ALL",):
            return "OK", [b" ".join(str(uid).encode() for uid in sorted(folder))]
        if command == "SEARCH":
            term = args[2].strip('"').encode()
            hits = [str(uid).encode() for uid, raw in sorted(folder.items()) if term in raw]
            return "OK", [b" ".join(hits)]
        if command == "FETCH":
            assert "BODY.PEEK[" in args[1]
            data: list[Any] = []
            for uid in _uids(args[0]):
                if uid in folder:
                    data += [(f"1 (UID {uid} BODY[] {{1}}".encode(), folder[uid]), b")"]
            return "OK", data
        assert not self.readonly, f"{command} on a folder opened read-only"
        if command == "MOVE":
            uid = int(args[0])
            self._next_uid += 1
            self.folders[args[1]][self._next_uid] = folder.pop(uid)
            self._untagged["COPYUID"] = [f"9 {uid} {self._next_uid}".encode()]
            return "OK", [None]
        if command == "STORE":
            return "OK", [b"stored"]
        raise AssertionError(f"unexpected command {command}")


def open_mailbox(fake: FakeImap, spam: str | None = None) -> ImapMailbox:
    return ImapMailbox.open(cast(imaplib.IMAP4, fake), "owner@example.test", "secret", spam)


def test_the_folders_come_from_special_use_or_the_configuration() -> None:
    assert open_mailbox(FakeImap()).spam == SPAM
    assert open_mailbox(FakeImap(), spam="Bulk").spam == "Bulk"


def test_a_server_without_move_or_uidplus_is_refused() -> None:
    with pytest.raises(MailboxError, match="lacks MOVE"):
        open_mailbox(FakeImap("IMAP4rev1 UIDPLUS"))
    with pytest.raises(MailboxError, match="lacks UIDPLUS"):
        open_mailbox(FakeImap("IMAP4rev1 MOVE"))


def test_reading_examines_folders_and_peeks_at_emails() -> None:
    fake = FakeImap()
    fake.folders[SPAM] = {1: make_email("a@shop.test", "One"), 2: make_email("b@shop.test", "Two")}
    fake.folders[SENT] = {5: make_email("owner@example.test", "Hi", to="b@shop.test")}
    mailbox = open_mailbox(fake)

    assert mailbox.uids(SPAM) == (9, [1, 2])
    assert set(mailbox.headers(SPAM, [1, 2])) == {1, 2}
    assert set(mailbox.messages(SPAM, [2])) == {2}
    assert mailbox.wrote_to("b@shop.test")

    assert not any(command[0] == "SELECT" for command in fake.commands)
    assert not any(
        command[1] in {"MOVE", "STORE"} for command in fake.commands if command[0] == "UID"
    )


def test_wrote_to_compares_whole_addresses() -> None:
    fake = FakeImap()
    fake.folders[SENT] = {5: make_email("owner@example.test", "Hi", to="notbob@shop.test")}
    mailbox = open_mailbox(fake)

    assert not mailbox.wrote_to("bob@shop.test")
    assert mailbox.wrote_to("notbob@shop.test")


def test_wrote_to_ignores_addresses_in_display_names() -> None:
    fake = FakeImap()
    to = '"bob@shop.test" <alice@shop.test>'
    fake.folders[SENT] = {5: make_email("owner@example.test", "Hi", to=to)}
    mailbox = open_mailbox(fake)

    assert not mailbox.wrote_to("bob@shop.test")
    assert mailbox.wrote_to("alice@shop.test")


def test_move_names_the_new_uid_and_a_gmail_label_marks_it() -> None:
    fake = FakeImap()
    fake.folders[SPAM] = {7: make_email("a@shop.test", "One")}
    mailbox = open_mailbox(fake)

    new_uid = mailbox.move_to_inbox(SPAM, 7)
    assert new_uid is not None
    mailbox.mark(new_uid, "unspam")

    assert new_uid in fake.folders["INBOX"]
    assert ("UID", "MOVE", "7", "INBOX") in fake.commands
    assert ("UID", "STORE", str(new_uid), "+X-GM-LABELS", "(unspam)") in fake.commands


def test_without_gmail_labels_a_keyword_marks_the_email() -> None:
    fake = FakeImap("IMAP4rev1 MOVE UIDPLUS")
    mailbox = ImapMailbox.open(cast(imaplib.IMAP4, fake), "u", "p", spam=SPAM)

    mailbox.mark(3, "unspam")

    assert ("UID", "STORE", "3", "+FLAGS", "(unspam)") in fake.commands


def test_a_server_that_allows_no_keywords_is_refused() -> None:
    fake = FakeImap("IMAP4rev1 MOVE UIDPLUS")
    fake.permanent_flags = b"(\\Seen \\Flagged)"

    with pytest.raises(MailboxError, match="no IMAP keywords"):
        ImapMailbox.open(cast(imaplib.IMAP4, fake), "u", "p", spam=SPAM)


def test_sequence_set_joins_runs() -> None:
    assert sequence_set([5, 1, 2, 3, 9, 10, 3]) == "1:3,5,9:10"
    assert sequence_set([4]) == "4"


def test_special_folders_reads_quoted_names() -> None:
    lines = [*LIST, b'(\\Junk) "/" "Bulk \\"mail\\""', None]

    assert special_folders(lines) == {
        "\\HasNoChildren": "INBOX",
        "\\Junk": SPAM,
        "\\Sent": SENT,
    }
