from datetime import UTC, datetime
from pathlib import Path

from valkit.mailkeeper.model import Header
from valkit.mailkeeper.report import markdown, plain, render_report, write_report
from valkit.mailkeeper.run import Failed, Result, Returned
from valkit.mailkeeper.state import State

WHEN = datetime(2026, 11, 22, 14, 30, 5, tzinfo=UTC)


def header(subject: str) -> Header:
    return Header(
        uid=1,
        message_id="<1@mail.test>",
        sender="sam@friend.test",
        from_text="Sam <sam@friend.test>",
        subject=subject,
        date="Sat, 21 Nov 2026 15:00:00 +0000",
        authentic=True,
    )


def test_plain_removes_control_and_invisible_characters() -> None:
    zero_width, right_to_left = chr(0x200B), chr(0x202E)
    text = f"Pay\x1b[31m now{zero_width}!\n{right_to_left}gnp.exe"

    assert plain(text) == "Pay [31m now ! gnp.exe"


def test_markdown_escapes_its_marks() -> None:
    assert markdown("[click](https://x.test) *now* <b>") == (
        "\\[click\\](https://x.test) \\*now\\* \\<b\\>"
    )


def test_the_report_lists_returns_marks_and_failures() -> None:
    result = Result(
        state=State(),
        returned=[
            Returned(header("Dinner on Friday?"), "personal"),
            Returned(header("Your invoice"), "transactional", "mark refused"),
        ],
        failed=[Failed(header("Re: call"), "move refused")],
    )

    text = render_report(WHEN, "[Gmail]/Spam", "unspam", result)

    assert text.startswith("# mailkeeper, 2026-11-22 14:30 UTC\n")
    assert "marked `unspam`" in text
    assert "- **personal** · Sat, 21 Nov 2026 15:00:00 +0000 · Sam \\<sam@friend.test\\>" in text
    assert "Your invoice · not marked: mark refused" in text
    assert "## Not returned" in text
    assert "Re: call · move refused" in text


def test_the_report_is_written_whole(tmp_path: Path) -> None:
    path = write_report(tmp_path, WHEN, "# report\n")

    assert path.name == "mailkeeper-20261122T143005Z.md"
    assert path.read_text() == "# report\n"
    assert [p.name for p in tmp_path.iterdir()] == [path.name]
