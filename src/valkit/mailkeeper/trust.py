"""Which senders a run trusts: checked before the model, and never sent to it."""

import re
from collections.abc import Callable

from valkit.mailkeeper.config import Config
from valkit.mailkeeper.model import Header

COMMENT_RE = re.compile(r"\([^()]*\)")
HEADER_FROM_RE = re.compile(r"\bheader\.from=([^\s;]+)")
DKIM_DOMAIN_RE = re.compile(r"\bheader\.d=([^\s;]+)|\bheader\.i=[^\s;@]*@([^\s;]+)")


def authenticated(results: list[str], from_domain: str, authserv_id: str) -> bool:
    """Whether the receiving server vouches for the From domain.

    Only the first Authentication-Results header counts, and only when the configured server
    wrote it: the receiving server adds its header on top, and a sender can write one too.
    The domain passes on `dmarc=pass` for it or a parent domain. A domain that publishes no
    DMARC record gets no DMARC result, and then `dkim=pass` signed by it or a parent passes.
    `dmarc=fail` never passes.
    """
    if not results or not from_domain:
        return False
    first = COMMENT_RE.sub(" ", " ".join(results[0].split())).lower()
    server, _, rest = first.partition(";")
    if not server.split() or server.split()[0] != authserv_id:
        return False
    methods = [method.strip() for method in rest.split(";")]
    dmarc = next((method for method in methods if method.startswith("dmarc=")), None)
    if dmarc is not None:
        header_from = HEADER_FROM_RE.search(dmarc)
        return dmarc.startswith("dmarc=pass") and bool(
            header_from and covers(header_from.group(1), from_domain)
        )
    for method in methods:
        if method.startswith("dkim=pass"):
            signer = DKIM_DOMAIN_RE.search(method)
            if signer and covers(signer.group(1) or signer.group(2), from_domain):
                return True
    return False


def covers(domain: str, from_domain: str) -> bool:
    """Whether `domain` is the From domain or a parent of it."""
    return from_domain == domain or from_domain.endswith("." + domain)


def trusted(header: Header, config: Config, wrote_to: Callable[[str], bool]) -> bool:
    """An authenticated sender who is the owner, on an own domain, or someone the owner wrote to."""
    if not header.authentic or not header.sender:
        return False
    domain = header.sender.rpartition("@")[2]
    return (
        header.sender in config.own_addresses
        or domain in config.own_domains
        or wrote_to(header.sender)
    )
