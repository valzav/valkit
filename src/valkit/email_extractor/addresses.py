import re

from valkit.email_extractor.model import Address

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def parse_addresses(text: str) -> list[Address]:
    """Parse a From/To/Cc value. Outlook separates entries with ';', other clients with ','.

    Separators inside quotes or angle brackets belong to the entry: "Doe, Jane" <jane@...> is one
    person. Outlook also writes Doe, Jane unquoted, so a lone word with no address before a comma
    is that person's surname, not a person of its own.
    """
    text = text.replace("*", "").strip()
    if not text:
        return []
    parts = _split(text, ";")
    if len(parts) == 1:
        merged: list[str] = []
        for part in _split(text, ","):
            if merged and len(merged[-1].split()) == 1 and not EMAIL_RE.search(merged[-1]):
                merged[-1] += "," + part
            else:
                merged.append(part)
        parts = merged
    addresses: list[Address] = []
    for part in parts:
        found = EMAIL_RE.search(part)
        email = found.group(0).lower() if found else ""
        name = clean_name(part)
        if name or email:
            addresses.append(Address(name=name, email=email))
    return addresses


def clean_name(text: str) -> str:
    """A display name without email addresses, brackets, quotes or stray punctuation.

    Some clients add the address to the name: "Jane Doe (jane@example.com)". A lone surname
    written first ("Doe, Jane") moves to the end, so the first word is the first name. Several
    words before the comma are a whole name followed by a suffix or company ("Jane Doe, Jr.").
    """
    name = re.sub(r"[<>\"'()\[\]]", "", EMAIL_RE.sub("", text))
    name = " ".join(name.split()).strip(" ,")
    surname, comma, given = name.partition(",")
    if comma and given.strip() and "," not in given and len(surname.split()) == 1:
        name = f"{given.strip()} {surname.strip()}"
    return name


def _split(text: str, separator: str) -> list[str]:
    """Split at separators outside quotes and angle brackets.

    A quote or bracket left open would make the rest of the header one person, so then every
    separator counts.
    """
    parts: list[str] = []
    current: list[str] = []
    quoted = bracketed = False
    for char in text:
        if char == '"':
            quoted = not quoted
        elif char in "<>" and not quoted:
            bracketed = char == "<"
        if char == separator and not quoted and not bracketed:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    if quoted or bracketed:
        parts = text.split(separator)
    return [part for part in parts if part.strip()]
