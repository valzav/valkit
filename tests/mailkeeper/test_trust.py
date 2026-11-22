import pytest

from valkit.mailkeeper.config import Config
from valkit.mailkeeper.message import read_header
from valkit.mailkeeper.trust import authenticated, covers, trusted

from .conftest import AUTHSERV, make_email

S = AUTHSERV


@pytest.mark.parametrize(
    ("header", "from_domain", "expected"),
    [
        (f"{S}; dmarc=pass (p=NONE) header.from=shop.test", "shop.test", True),
        # Gmail names the parent domain for mail from a subdomain.
        (f"{S}; dmarc=pass (p=NONE) header.from=shop.test", "mail.shop.test", True),
        (f"{S}; dmarc=pass (p=NONE) header.from=other.test", "shop.test", False),
        (
            f"{S}; dkim=pass header.i=@shop.test; dmarc=fail header.from=shop.test",
            "shop.test",
            False,
        ),
        # No DMARC record: DKIM signed by the From domain or a parent passes.
        (f"{S}; dkim=pass header.i=@shop.test; spf=softfail", "shop.test", True),
        (f"{S}; dkim=pass header.d=shop.test header.s=sel", "news.shop.test", True),
        (f"{S}; dkim=pass header.i=@sender.example; spf=pass", "shop.test", False),
        (f"{S}; spf=pass smtp.mailfrom=shop.test", "shop.test", False),
        (f"{S}; dkim=pass (good; signature) header.i=@shop.test", "shop.test", True),
        ("other.server; dmarc=pass header.from=shop.test", "shop.test", False),
        (f"{S} 1; dmarc=pass header.from=shop.test", "shop.test", True),
        (f"{S.upper()}; DMARC=PASS header.from=SHOP.TEST", "shop.test", True),
    ],
)
def test_authenticated(header: str, from_domain: str, expected: bool) -> None:
    assert authenticated([header], from_domain, AUTHSERV) is expected


def test_only_the_first_header_counts() -> None:
    forged = f"{S}; dmarc=pass header.from=shop.test"
    assert not authenticated([f"{S}; spf=none", forged], "shop.test", AUTHSERV)


def test_no_header_or_no_domain_is_not_authenticated() -> None:
    assert not authenticated([], "shop.test", AUTHSERV)
    assert not authenticated([f"{S}; dmarc=pass header.from=shop.test"], "", AUTHSERV)


def test_covers_needs_a_dot_before_the_parent() -> None:
    assert covers("shop.test", "mail.shop.test")
    assert not covers("shop.test", "fakeshop.test")


def trust_of(data: bytes, config: Config, sent_to: frozenset[str] = frozenset()) -> bool:
    return trusted(read_header(1, data, config.authserv_id), config, sent_to.__contains__)


def test_own_address_own_domain_and_people_written_to_are_trusted(config: Config) -> None:
    partner = frozenset({"partner@fund.test"})
    assert trust_of(make_email("Me <owner@example.test>", "Note"), config)
    assert trust_of(make_email("info@club.example", "Club news"), config)
    assert trust_of(make_email("partner@fund.test", "Re: call"), config, partner)
    assert not trust_of(make_email("partner@fund.test", "Re: call"), config)


def test_a_forged_own_address_is_not_trusted(config: Config) -> None:
    forged = make_email("Me <owner@example.test>", "Invoice", auth=f"{S}; spf=none")
    no_header = make_email("Me <owner@example.test>", "Invoice", auth=None)

    assert not trust_of(forged, config)
    assert not trust_of(no_header, config)


def test_a_subdomain_of_an_own_domain_is_not_an_own_domain(config: Config) -> None:
    assert not trust_of(make_email("news@mail.example.test", "News"), config)


def test_an_address_in_the_display_name_is_not_the_sender(config: Config) -> None:
    # Anyone on a shared mail domain could otherwise pose as a person the owner wrote to.
    data = make_email('"partner@fund.test" <attacker@fund.test>', "Re: call")

    header = read_header(1, data, config.authserv_id)

    assert header.sender == "attacker@fund.test"
    assert not trust_of(data, config, frozenset({"partner@fund.test"}))


def test_an_encoded_display_name_is_not_the_sender(config: Config) -> None:
    # Built as bytes: EmailMessage would decode the name before sending it.
    data = make_email("attacker@fund.test", "Re: call").replace(
        b"From: attacker@fund.test", b"From: =?utf-8?q?partner=40fund.test?= <attacker@fund.test>"
    )

    assert read_header(1, data, config.authserv_id).sender == "attacker@fund.test"


def test_an_unquoted_address_before_the_mailbox_leaves_no_sender(config: Config) -> None:
    data = make_email("attacker@fund.test", "Re: call").replace(
        b"From: attacker@fund.test", b"From: partner@fund.test <attacker@fund.test>"
    )

    assert read_header(1, data, config.authserv_id).sender == ""


def test_an_email_with_two_from_headers_has_no_sender(config: Config) -> None:
    data = b"From: other@fund.test\n" + make_email("partner@fund.test", "Re: call")

    header = read_header(1, data, config.authserv_id)

    assert header.sender == ""
    assert not trust_of(data, config, frozenset({"partner@fund.test", "other@fund.test"}))


def test_a_from_header_with_two_mailboxes_has_no_sender(config: Config) -> None:
    data = make_email("partner@fund.test, other@fund.test", "Re: call")

    assert read_header(1, data, config.authserv_id).sender == ""
