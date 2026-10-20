from valkit.email_extractor.model import Address, Message
from valkit.email_extractor.render import join_paragraph_lines
from valkit.email_extractor.signature import strip_signatures


def message(body: str, name: str = "Jane Doe") -> Message:
    return Message(Address(name, "jane@example.com"), [], [], None, "", "Plan", body)


def stripped(body: str, name: str = "Jane Doe") -> Message:
    messages = [message(body, name)]
    strip_signatures(messages)
    return messages[0]


def test_delimiter_starts_a_signature_that_runs_to_the_end() -> None:
    result = stripped(
        "The plan is ready.\n\n--\nJane\nExample Consulting\n\n123 Main St\nSpringfield"
    )

    assert result.body == "The plan is ready."
    assert result.signature.endswith("Springfield")


def test_sign_off_with_name_removes_whole_block_but_keeps_ps() -> None:
    body = (
        "The plan is ready.\n\nBest,\n\nJane Doe\nPartner\n\nExample Consulting\n123 Main St\n\n"
        "CONFIDENTIALITY NOTICE: this email is private.\n\nPS: see you Monday."
    )
    result = stripped(body)

    assert result.body == "The plan is ready.\n\nPS: see you Monday."
    assert "123 Main St" in result.signature


def test_thanks_in_the_middle_keeps_the_rest() -> None:
    body = "Hi Sam,\n\nThanks!\n\nThe report is attached and the numbers look fine."
    assert stripped(body).body == body


def test_paragraph_lines_are_joined() -> None:
    text = "One line\nand the next.\n\nSecond paragraph\ncontinues."
    assert join_paragraph_lines(text) == "One line and the next.\n\nSecond paragraph continues."


def test_markdown_blocks_keep_their_lines() -> None:
    text = (
        "Intro line\n- first item\n  wrapped\n- second item\n#### Heading\nAfter heading\n"
        "| a | b |\n| --- | --- |\n> quoted\n```\ncode line\nmore code\n```\n---"
    )
    assert join_paragraph_lines(text) == (
        "Intro line\n- first item wrapped\n- second item\n#### Heading\nAfter heading\n"
        "| a | b |\n| --- | --- |\n> quoted\n```\ncode line\nmore code\n```\n---"
    )
