"""Merge everyone in the thread into participants, with details found in their signatures."""

import re
from collections.abc import Iterator

import phonenumbers

from valkit.email_extractor.addresses import EMAIL_RE
from valkit.email_extractor.model import Address, Message, Participant
from valkit.email_extractor.signature import SIGN_OFF_RE

TEL_LINK_RE = re.compile(r"\[([^\]]+)\]\(tel:[^)]*\)")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
BARE_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]|]+")


def all_addresses(messages: list[Message]) -> Iterator[Address]:
    for message in messages:
        yield message.sender
        yield from message.to
        yield from message.cc


def resolve(messages: list[Message]) -> None:
    """Fill in a missing email or name from other headers that show the same person."""
    email_by_name: dict[str, str] = {}
    name_by_email: dict[str, str] = {}
    for address in all_addresses(messages):
        if address.name and address.email:
            email_by_name.setdefault(address.name.lower(), address.email)
            if len(address.name) > len(name_by_email.get(address.email, "")):
                name_by_email[address.email] = address.name
    for address in all_addresses(messages):
        address.email = address.email or email_by_name.get(address.name.lower(), "")
        address.name = name_by_email.get(address.email, address.name)


def collect(messages: list[Message]) -> list[Participant]:
    participants: dict[str, Participant] = {}
    for address in all_addresses(messages):
        participant = participants.setdefault(address.key, Participant(name=address.name))
        _add(participant.emails, [address.email] if address.email else [])
    for message in messages:
        if message.signature:
            _add_signature(participants[message.sender.key], message.signature, message.sender)
    return list(participants.values())


def _add_signature(participant: Participant, signature: str, sender: Address) -> None:
    _add(participant.phones, TEL_LINK_RE.findall(signature))
    text = TEL_LINK_RE.sub("", signature)
    _add(
        participant.phones,
        [match.raw_string for match in phonenumbers.PhoneNumberMatcher(text, None)],
    )
    _add(
        participant.links,
        [url for _, url in MD_LINK_RE.findall(text)],
    )
    text = MD_LINK_RE.sub("", text)
    _add(participant.links, BARE_URL_RE.findall(text))
    _add(participant.emails, [email.lower() for email in EMAIL_RE.findall(text)])
    _add(participant.details, _details(signature, sender))


def _details(signature: str, sender: Address) -> list[str]:
    """Plain-text signature lines such as a job title or company name."""
    details: list[str] = []
    for raw in signature.splitlines():
        line = re.sub(r"[*_]+", "", raw).strip(" |")
        if (
            not line
            or line.endswith(":")
            or "](" in raw
            or BARE_URL_RE.search(line)
            or EMAIL_RE.search(line)
            or SIGN_OFF_RE.match(line)
            or line.strip(",.!").lower() in {sender.name.lower(), sender.name.split(" ")[0].lower()}
            or any(phonenumbers.PhoneNumberMatcher(line, None))
        ):
            continue
        details.append(line)
    return details


def _add(values: list[str], new: list[str]) -> None:
    for value in new:
        value = value.strip().rstrip(".,;")
        if value and value not in values:
            values.append(value)
