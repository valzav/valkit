from valkit.email_extractor.addresses import parse_addresses
from valkit.email_extractor.cli import extract
from valkit.email_extractor.model import Address
from valkit.email_extractor.strict import Scrubber

from .conftest import MakeEml


def test_link_titles_and_angle_destinations_are_dropped() -> None:
    scrubber = Scrubber([Address("Jane Doe", "jane@example.com")])

    assert scrubber.scrub('[site](https://x.com/jd "Jane Doe profile")') == "site"
    assert scrubber.scrub("[site](<https://x.com/a b>) and [cv](https://x.com/cv 'Doe CV')") == (
        "site and cv"
    )


def test_surnames_from_email_addresses_and_any_case() -> None:
    scrubber = Scrubber([Address("Jane D.", "jane.doe@example.com"), Address("Sam Lee", "")])

    assert scrubber.scrub("Doe agreed, doe agreed, DOE agreed. lee and LEE too.") == (
        "Jane agreed, Jane agreed, Jane agreed. Sam and Sam too."
    )


def test_username_with_surname_is_replaced() -> None:
    scrubber = Scrubber([Address("Jane Doe", "jdoe@example.com")])

    assert scrubber.scrub("Ask Jdoe.") == "Ask Jane."


def test_role_address_pieces_match_only_their_written_case() -> None:
    scrubber = Scrubber([Address("", "ops.team@example.com")])

    assert scrubber.scrub("The team asked Team lead.") == "The team asked Ops lead."


def test_surname_first_names_are_one_person() -> None:
    assert parse_addresses('"Doe, Jane" <jane@example.com>, Sam Lee <sam@example.org>') == [
        Address("Jane Doe", "jane@example.com"),
        Address("Sam Lee", "sam@example.org"),
    ]
    assert parse_addresses("Doe, Jane <jane@example.com>") == [
        Address("Jane Doe", "jane@example.com")
    ]
    assert parse_addresses("Doe, Jane; Lee, Sam") == [
        Address("Jane Doe", ""),
        Address("Sam Lee", ""),
    ]
    assert parse_addresses("Jane Doe, Sam Lee") == [Address("Jane Doe", ""), Address("Sam Lee", "")]
    assert parse_addresses('"Doe, Jane <jane@example.com>, Lee, Sam <sam@example.org>') == [
        Address("Jane Doe", "jane@example.com"),
        Address("Sam Lee", "sam@example.org"),
    ]
    assert parse_addresses('"Jane Doe, Jr." <jane@example.com>') == [
        Address("Jane Doe, Jr.", "jane@example.com")
    ]
    assert parse_addresses('"Jane Doe, Example Consulting" <jane@example.com>') == [
        Address("Jane Doe, Example Consulting", "jane@example.com")
    ]


def test_strict_output_drops_surnames_written_first(make_eml: MakeEml) -> None:
    html = (
        "<div>Doe will send the budget.</div>"
        "<div>From: Lee, Sam &lt;sam@example.org&gt;<br>Sent: Sunday, April 5, 2026 9:15 AM<br>"
        "To: Doe, Jane &lt;jane@example.com&gt;<br>Subject: Budget</div>"
        "<div>Lee here, budget attached.</div>"
    )
    markdown = extract(make_eml(html=html, to='"Doe, Jane" <jane@example.com>'), strict=True)

    assert "Doe" not in markdown and "Lee" not in markdown
    assert "Jane" in markdown and "Sam" in markdown
