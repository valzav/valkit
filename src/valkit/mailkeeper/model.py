from dataclasses import dataclass

CLASSES = ("personal", "transactional", "newsletter", "marketing", "cold_outreach", "scam")
"""The classes the detector chooses from."""

WANTED = frozenset({"personal", "transactional"})
"""Classes of email that a run returns from the spam folder."""


@dataclass(frozen=True)
class Header:
    """What a run reads of every email in a folder."""

    uid: int
    message_id: str
    """Empty when the email has no Message-ID."""
    sender: str
    """The lowercase From address, or empty when there is none."""
    from_text: str
    subject: str
    date: str
    authentic: bool
    """Whether the receiving server's own Authentication-Results header vouches for the From
    domain; see `trust.authenticated`."""


@dataclass(frozen=True)
class EmailText:
    """What the detector sees of one email. The folder is not part of it."""

    sender: str
    to: str
    cc: str
    date: str
    subject: str
    text: str
