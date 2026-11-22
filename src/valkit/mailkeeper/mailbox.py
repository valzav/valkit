"""The IMAP mailbox. Reads use EXAMINE and BODY.PEEK, so no email becomes read; the only
writes are a MOVE to the inbox and the mark on the moved email."""

import email
import email.policy
import imaplib
import re
from collections.abc import Generator
from contextlib import contextmanager
from email.message import EmailMessage
from typing import Any, Protocol, cast

from valkit.mailkeeper.message import addresses

INBOX = "INBOX"
HEADER_FIELDS = "FROM DATE SUBJECT MESSAGE-ID AUTHENTICATION-RESULTS"
# MOVE (RFC 6851): the older copy, flag deleted, and expunge can remove other emails that carry
# the deleted flag. UIDPLUS (RFC 4315): MOVE then names the email's new UID, which the mark needs.
REQUIRED = ("MOVE", "UIDPLUS")
LIST_RE = re.compile(r'^\((?P<flags>[^)]*)\) (?:"(?:[^"\\]|\\.)*"|NIL) (?P<name>.+)$')
UID_RE = re.compile(rb"\bUID (\d+)")


class MailboxError(RuntimeError):
    pass


class Mailbox(Protocol):
    """What a run needs from the mailbox. Tests pass a fake."""

    @property
    def spam(self) -> str: ...

    def uids(self, folder: str) -> tuple[int, list[int]]:
        """The folder's UIDVALIDITY and the UIDs of its emails."""
        ...

    def headers(self, folder: str, uids: list[int]) -> dict[int, bytes]: ...

    def messages(self, folder: str, uids: list[int]) -> dict[int, bytes]: ...

    def wrote_to(self, address: str) -> bool:
        """Whether an email in the sent folder went to this address."""
        ...

    def move_to_inbox(self, folder: str, uid: int) -> int | None:
        """Move one email to the inbox and return its new UID there, if the server names it."""
        ...

    def mark(self, uid: int, mark: str) -> None:
        """Mark an email of the inbox."""
        ...


@contextmanager
def _errors(what: str) -> Generator[None]:
    try:
        yield
    except (imaplib.IMAP4.error, OSError) as error:
        raise MailboxError(f"{what}: {error}") from error


def _check(result: tuple[str, list[Any]], what: str) -> list[Any]:
    status, data = result
    if status != "OK":
        raise MailboxError(f"{what} failed: {status} {data!r}")
    return data


def quote(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sequence_set(uids: list[int]) -> str:
    """UIDs as an IMAP sequence set with ranges, so one command covers them all."""
    ordered = sorted(set(uids))
    parts: list[str] = []
    start = previous = ordered[0]
    for uid in [*ordered[1:], None]:
        if uid is not None and uid == previous + 1:
            previous = uid
            continue
        parts.append(str(start) if start == previous else f"{start}:{previous}")
        if uid is not None:
            start = previous = uid
    return ",".join(parts)


def special_folders(lines: list[Any]) -> dict[str, str]:
    """Folder names by their SPECIAL-USE attribute (RFC 6154), such as \\Junk and \\Sent."""
    found: dict[str, str] = {}
    for line in lines:
        if not isinstance(line, bytes):
            continue
        match = LIST_RE.match(line.decode("utf-8", "replace"))
        if not match:
            continue
        name = match["name"]
        if name.startswith('"') and name.endswith('"'):
            name = re.sub(r"\\(.)", r"\1", name[1:-1])
        for flag in match["flags"].split():
            found.setdefault(flag, name)
    return found


class ImapMailbox:
    def __init__(self, imap: imaplib.IMAP4, spam: str, sent: str | None, labels: bool) -> None:
        self._imap = imap
        self._spam = spam
        self._sent = sent
        self._labels = labels
        """Gmail labels (X-GM-EXT-1) mark an email; elsewhere an IMAP keyword does."""
        self._selected: tuple[str, bool] | None = None
        self._uidvalidity = 0

    @classmethod
    def open(
        cls,
        imap: imaplib.IMAP4,
        user: str,
        password: str,
        spam: str | None = None,
        sent: str | None = None,
    ) -> ImapMailbox:
        """Log in, check the server, and find the spam and sent folders."""
        with _errors("IMAP login"):
            _check(imap.login(user, password), "LOGIN")
            # Servers announce some capabilities only after login.
            capabilities = set(_check(imap.capability(), "CAPABILITY")[0].decode().upper().split())
            listed = special_folders(_check(imap.list(), "LIST"))
        missing = [name for name in REQUIRED if name not in capabilities]
        if missing:
            raise MailboxError(
                f"the IMAP server lacks {', '.join(missing)}, which mailkeeper needs"
            )
        spam = spam or listed.get("\\Junk")
        if spam is None:
            raise MailboxError("the server marks no folder \\Junk; name it in folders.spam")
        mailbox = cls(imap, spam, sent or listed.get("\\Sent"), "X-GM-EXT-1" in capabilities)
        if not mailbox._labels:
            mailbox._require_keywords()
        return mailbox

    @property
    def spam(self) -> str:
        return self._spam

    def _select(self, folder: str, writable: bool) -> None:
        if self._selected == (folder, writable):
            return
        with _errors(f"opening {folder}"):
            _check(self._imap.select(quote(folder), readonly=not writable), f"SELECT {folder}")
            value = self._imap.response("UIDVALIDITY")[1][0]
        self._uidvalidity = int(value) if isinstance(value, bytes) else 0
        self._selected = (folder, writable)

    def _require_keywords(self) -> None:
        self._select(INBOX, writable=False)
        with _errors("reading PERMANENTFLAGS"):
            flags = self._imap.response("PERMANENTFLAGS")[1]
        if not any(isinstance(item, bytes) and b"\\*" in item for item in flags):
            raise MailboxError(
                "the server allows no IMAP keywords, so a returned email has no mark"
            )

    def uids(self, folder: str) -> tuple[int, list[int]]:
        self._select(folder, writable=False)
        with _errors(f"listing {folder}"):
            data = _check(self._imap.uid("SEARCH", "ALL"), f"SEARCH {folder}")
        return self._uidvalidity, [int(uid) for uid in data[0].split()]

    def _fetch(self, folder: str, uids: list[int], part: str) -> dict[int, bytes]:
        if not uids:
            return {}
        self._select(folder, writable=False)
        with _errors(f"reading {folder}"):
            data = _check(
                self._imap.uid("FETCH", sequence_set(uids), f"(BODY.PEEK[{part}])"), "FETCH"
            )
        # A fetched email arrives as (b'<n> (UID <uid> BODY[...] {<size>}', <bytes>).
        found: dict[int, bytes] = {}
        for item in data:
            if not isinstance(item, tuple):
                continue
            meta, body = cast(tuple[Any, Any], item)[:2]
            uid = UID_RE.search(meta) if isinstance(meta, bytes) else None
            if uid and isinstance(body, bytes):
                found[int(uid.group(1))] = body
        return found

    def headers(self, folder: str, uids: list[int]) -> dict[int, bytes]:
        return self._fetch(folder, uids, f"HEADER.FIELDS ({HEADER_FIELDS})")

    def messages(self, folder: str, uids: list[int]) -> dict[int, bytes]:
        return self._fetch(folder, uids, "")

    def wrote_to(self, address: str) -> bool:
        # IMAP SEARCH matches substrings, so each hit's recipients are compared exactly.
        if self._sent is None or not address.isascii():
            return False
        self._select(self._sent, writable=False)
        term = quote(address)
        with _errors(f"searching {self._sent}"):
            data = _check(
                self._imap.uid("SEARCH", "OR", "TO", term, "OR", "CC", term, "BCC", term), "SEARCH"
            )
        hits = [int(uid) for uid in data[0].split()]
        found = self._fetch(self._sent, hits, "HEADER.FIELDS (TO CC BCC)")
        return any(address in _recipients(raw) for raw in found.values())

    def move_to_inbox(self, folder: str, uid: int) -> int | None:
        self._select(folder, writable=True)
        with _errors(f"moving UID {uid} to {INBOX}"):
            _check(self._imap.uid("MOVE", str(uid), INBOX), "MOVE")
            copied = self._imap.response("COPYUID")[1]
        # COPYUID <uidvalidity> <source UIDs> <destination UIDs>
        fields = copied[-1].split() if copied and isinstance(copied[-1], bytes) else []
        if len(fields) == 3 and fields[1] == str(uid).encode() and fields[2].isdigit():
            return int(fields[2])
        return None

    def mark(self, uid: int, mark: str) -> None:
        self._select(INBOX, writable=True)
        item = "+X-GM-LABELS" if self._labels else "+FLAGS"
        with _errors(f"marking UID {uid}"):
            _check(self._imap.uid("STORE", str(uid), item, f"({mark})"), "STORE")


def _recipients(raw: bytes) -> set[str]:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    assert isinstance(message, EmailMessage)
    return addresses(message, "To") | addresses(message, "Cc") | addresses(message, "Bcc")
