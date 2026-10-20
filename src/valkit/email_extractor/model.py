from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Address:
    name: str
    email: str

    @property
    def key(self) -> str:
        return (self.email or self.name).lower()

    @property
    def label(self) -> str:
        return self.name or self.email


@dataclass
class Message:
    sender: Address
    to: list[Address]
    cc: list[Address]
    date: datetime | None
    date_text: str
    subject: str
    body: str
    signature: str = ""
    # Identity across exports (see log.message_key); set before signatures are removed.
    key: str = ""


@dataclass
class Participant:
    name: str
    emails: list[str] = field(default_factory=list[str])
    phones: list[str] = field(default_factory=list[str])
    links: list[str] = field(default_factory=list[str])
    details: list[str] = field(default_factory=list[str])
