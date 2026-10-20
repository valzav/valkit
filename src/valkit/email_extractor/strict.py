"""Strict mode: strip personal details so the output is safe to share.

People keep their first names; last names, email addresses, phone numbers, URLs and dollar amounts
are removed. Only names of people on the thread (From/To/Cc) are known and shortened.
"""

import re
from collections.abc import Iterable

import phonenumbers

from valkit.email_extractor.addresses import EMAIL_RE
from valkit.email_extractor.model import Address
from valkit.email_extractor.redact import placeholder

# Numbers without a "+" prefix are read as US numbers (the operator's choice in the plan).
PHONE_REGION = "US"

# A Markdown link, with its destination in plain or <angle-bracket> form and an optional title.
# The whole link becomes its text, so neither the URL nor the title (often a full name) survives.
MD_LINK_RE = re.compile(
    r"\[([^\]]*)\]\((?:<[^>\n]*>|[^)\s]*)(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^)\n]*\)))?\s*\)"
)
# A URL never ends in sentence punctuation, so "see https://x.com/a." keeps its full stop.
URL_RE = re.compile(r"<?(?:https?://|www\.)[^\s<>()\[\]]*[^\s<>()\[\].,;:!?]>?")
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
SCALE = r"(?:\s?(?:thousand|million|billion|trillion|mn|bn|[KkMmBb])\b)?"
AMOUNT_RE = re.compile(
    rf"(?:US)?\$\s?{NUMBER}{SCALE}"
    rf"|\bUSD\s?{NUMBER}{SCALE}"
    rf"|\b{NUMBER}{SCALE}\s?(?:USD|dollars?)\b",
    re.IGNORECASE,
)


def email_name(email: str) -> tuple[str, list[str]]:
    """First name and remaining name pieces from an address: jane.doe@ gives ("Jane", ["Doe"])."""
    local = email.split("@")[0]
    pieces = [re.sub(r"\d+", "", piece) for piece in re.split(r"[._+-]", local)]
    pieces = [piece.capitalize() for piece in pieces if piece]
    return (pieces[0], pieces[1:]) if pieces else ("Unknown", [])


def first_name(address: Address) -> str:
    if address.name and "@" not in address.name:
        return address.name.split()[0]
    if address.email or address.name:
        return email_name(address.email or address.name)[0]
    return "Unknown sender"


class Scrubber:
    def __init__(self, addresses: Iterable[Address]) -> None:
        firsts: set[str] = set()
        # Last-name pieces mapped to the first name that replaces them.
        surnames: dict[str, str] = {}
        # Pieces of addresses without a display name; matched in their written case, because a role
        # address such as ops.team@ must not turn every "team" in the text into "Ops".
        email_pieces: dict[str, str] = {}
        full_names: dict[str, str] = {}
        for address in addresses:
            first = first_name(address)
            firsts.add(first.lower())
            if address.name and "@" not in address.name:
                if address.name.split()[1:]:
                    # The full name in one piece, so "Jane Doe" becomes "Jane", not "Jane Jane".
                    full_names[address.name] = first
                for piece in _pieces(address.name.split()[1:]):
                    surnames[piece] = first
            local_first, local_rest = email_name(address.email or address.name)
            if address.name and "@" not in address.name:
                # With a display name, every other piece of the address is a surname or a username
                # built from one ("jane.doe@", "jdoe@").
                for piece in _pieces([local_first, *local_rest]):
                    surnames.setdefault(piece, first)
            else:
                for piece in _pieces(local_rest):
                    email_pieces.setdefault(piece, first)

        names: dict[str, str] = dict(full_names)
        for piece, first in email_pieces.items():
            names[piece] = names[piece.upper()] = first
        for piece, first in surnames.items():
            # Surnames from display names match in any case: "Doe", "DOE", "doe".
            names[piece] = names[piece.upper()] = names[piece.lower()] = first
        # A piece that is someone's first name stays: "Thomas Lee" must not lose "Thomas" because
        # someone else is called "John Thomas".
        self._names = {
            piece: first
            for piece, first in names.items()
            if piece.lower() not in firsts or piece in full_names
        }
        alternatives = sorted(self._names, key=len, reverse=True)
        self._name_re = (
            re.compile(r"\b(?:" + "|".join(map(re.escape, alternatives)) + r")\b")
            if alternatives
            else None
        )

    def scrub(self, text: str) -> str:
        text = MD_LINK_RE.sub(lambda match: match.group(1) or placeholder("link"), text)
        text = URL_RE.sub(placeholder("link"), text)
        text = EMAIL_RE.sub(placeholder("email"), text)
        text = _scrub_phones(text)
        text = AMOUNT_RE.sub(placeholder("amount"), text)
        if self._name_re:
            text = self._name_re.sub(lambda match: self._names[match.group(0)], text)
        return text


def _pieces(words: Iterable[str]) -> list[str]:
    pieces = [word.strip(".,'\"()") for word in words]
    # An initial ("J.") is not a name to replace across the text.
    return [piece for piece in pieces if len(piece) >= 2]


def _scrub_phones(text: str) -> str:
    matches = list(phonenumbers.PhoneNumberMatcher(text, PHONE_REGION))
    for match in reversed(matches):
        text = text[: match.start] + placeholder("phone") + text[match.end :]
    return text
