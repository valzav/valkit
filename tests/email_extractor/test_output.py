import json
import re
import sys
from pathlib import Path

import pytest

from valkit.email_extractor.cli import main
from valkit.email_extractor.log import LOG_FILE

from .conftest import MakeEml

FIRST = "<div>Jane,<br>Here is the first draft.</div>"
SECOND = "<div>John,<br>Looks good, one change on page 2.</div>"
THIRD = "<div>Jane,<br>Done, see the new version.</div>"


def quote(header: str, html: str) -> str:
    return f"<div>{header}</div><blockquote>{html}</blockquote>"


def jane(day: int) -> str:
    return f"On Sun, Apr {day}, 2026 at 6:30 PM Jane Doe &lt;jane@example.com&gt; wrote:"


def john(day: int) -> str:
    return f"On Sat, Apr {day}, 2026 at 9:15 AM John Smith &lt;john@example.com&gt; wrote:"


# Two exports of one thread: the later one quotes everything and adds one message.
OLD_EXPORT = SECOND + quote(john(4), FIRST)
NEW_EXPORT = THIRD + quote(jane(5), SECOND + quote(john(4), FIRST))


def run(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["email-extractor", *args])
    main()


def export(make_eml: MakeEml, html: str, name: str, date: str, sender: str) -> Path:
    return make_eml(html=html, name=name, date=date, sender=sender, subject="Re: Draft Review")


def old(make_eml: MakeEml, name: str = "old.eml") -> Path:
    return export(
        make_eml,
        OLD_EXPORT,
        name,
        "Sun, 05 Apr 2026 18:30:00 +0000",
        "Jane Doe <jane@example.com>",
    )


def new(make_eml: MakeEml, name: str = "new.eml") -> Path:
    return export(
        make_eml,
        NEW_EXPORT,
        name,
        "Tue, 07 Apr 2026 08:00:00 +0000",
        "John Smith <john@example.com>",
    )


def headings(path: Path) -> list[str]:
    return re.findall(r"^#+ .*$", path.read_text(), re.MULTILINE)


def test_by_topic_writes_next_to_the_input(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(monkeypatch, str(old(make_eml)), "--by-topic")

    topic_file = tmp_path / "20260404-20260405-draft-review.md"
    assert headings(topic_file) == [
        "# Draft Review",
        "### John Smith · 2026-04-04 09:15",
        "### Jane Doe · 2026-04-05 18:30",
    ]
    data = json.loads((tmp_path / "metadata.json").read_text())
    assert data["topics"] == [
        {
            "file": "20260404-20260405-draft-review.md",
            "subject": "Draft Review",
            "thread": "Draft Review",
            "sources": ["old.eml"],
            "messages": 2,
            "date_range": ["2026-04-04", "2026-04-05"],
            "participants": ["John Smith", "Jane Doe"],
        }
    ]
    assert (tmp_path / LOG_FILE).exists()


def test_by_topic_appends_new_messages_and_extends_the_name(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(monkeypatch, str(old(make_eml)), "--by-topic")
    run(monkeypatch, str(new(make_eml)), "--by-topic")

    assert sorted(p.name for p in tmp_path.glob("*.md")) == ["20260404-20260407-draft-review.md"]
    topic_file = tmp_path / "20260404-20260407-draft-review.md"
    assert headings(topic_file) == [
        "# Draft Review",
        "### John Smith · 2026-04-04 09:15",
        "### Jane Doe · 2026-04-05 18:30",
        "### John Smith · 2026-04-07 08:00",
    ]
    assert topic_file.read_text().count("Here is the first draft.") == 1
    [entry] = json.loads((tmp_path / "metadata.json").read_text())["topics"]
    assert entry["file"] == "20260404-20260407-draft-review.md"
    assert entry["sources"] == ["old.eml", "new.eml"]
    assert entry["messages"] == 3
    assert entry["date_range"] == ["2026-04-04", "2026-04-07"]


def test_single_file_appends_and_merges_frontmatter(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(monkeypatch, str(old(make_eml)))
    run(monkeypatch, str(new(make_eml)))

    assert sorted(p.name for p in tmp_path.glob("*.md")) == ["old.md"]
    text = (tmp_path / "old.md").read_text()
    front = json.loads(re.match(r"---\n(.*?)\n---\n", text, re.DOTALL).group(1))  # type: ignore[union-attr]
    assert front["sources"] == ["old.eml", "new.eml"]
    assert front["messages"] == 3
    assert front["date_range"] == ["2026-04-04", "2026-04-07"]
    assert [p["name"] for p in front["participants"]] == ["John Smith", "Jane Doe"]
    assert text.count("Done, see the new version.") == 1
    assert text.count("Here is the first draft.") == 1


def test_rerun_writes_nothing(
    make_eml: MakeEml,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = old(make_eml)
    run(monkeypatch, str(source))
    before = (tmp_path / "old.md").read_text()

    run(monkeypatch, str(source))

    assert (tmp_path / "old.md").read_text() == before
    assert "no new messages" in capsys.readouterr().err


def test_all_formats_share_a_folder_without_touching_each_other(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = old(make_eml)
    run(monkeypatch, str(source), "--strict")
    run(monkeypatch, str(source), "--by-topic", "--strict")
    strict_files = {p: p.read_text() for p in tmp_path.glob("*.strict.md")}
    run(monkeypatch, str(source))
    run(monkeypatch, str(source), "--by-topic")
    run(monkeypatch, str(new(make_eml)))
    run(monkeypatch, str(new(make_eml)), "--by-topic")

    assert sorted(p.name for p in tmp_path.glob("*.md")) == [
        "20260404-20260405-draft-review.strict.md",
        "20260404-20260407-draft-review.md",
        "old.md",
        "old.strict.md",
    ]
    # Normal runs never rewrite a strict file: it keeps first names only.
    assert {p: p.read_text() for p in tmp_path.glob("*.strict.md")} == strict_files
    for text in strict_files.values():
        assert "Doe" not in text and "Smith" not in text


def test_output_owned_by_another_format_is_refused(
    make_eml: MakeEml,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = old(make_eml)
    run(monkeypatch, str(source), "--by-topic")
    target = tmp_path / "20260404-20260405-draft-review.md"
    before = target.read_text()

    with pytest.raises(SystemExit, match="1 of 1 files failed"):
        run(monkeypatch, str(source), "-o", str(target))
    with pytest.raises(SystemExit, match="1 of 1 files failed"):
        run(monkeypatch, str(source), "-o", str(tmp_path / "metadata.json"))

    assert target.read_text() == before
    err = capsys.readouterr().err
    assert "holds topics output" in err and "holds the tool's own data" in err


def test_deleted_output_is_regenerated(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = old(make_eml)
    run(monkeypatch, str(source))
    (tmp_path / "old.md").unlink()

    run(monkeypatch, str(source))

    assert "Here is the first draft." in (tmp_path / "old.md").read_text()


def test_unrelated_threads_with_one_subject_keep_separate_files(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = export(
        make_eml,
        "<div>Unrelated question.</div>",
        "other.eml",
        "Fri, 10 Apr 2026 10:00:00 +0000",
        "Sam Lee <sam@example.org>",
    )
    run(monkeypatch, str(old(make_eml)), str(other), "--by-topic")

    assert sorted(p.name for p in tmp_path.glob("*.md")) == [
        "20260404-20260405-draft-review.md",
        "20260410-20260410-draft-review.md",
    ]


def test_batch_skips_files_that_are_not_emails(
    make_eml: MakeEml,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old(make_eml, name="thread")  # no extension, as some mail apps save them
    run(monkeypatch, str(tmp_path / "thread"), "--by-topic")
    (tmp_path / "notes.txt").write_text("plain notes")

    run(monkeypatch, str(tmp_path / "*"), "--by-topic")

    err = capsys.readouterr().err
    assert "skipped" in err and "notes.txt" in err and "metadata.json" in err
    assert "failed" not in err


def test_log_entries_cannot_point_outside_the_folder(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "out"
    source = old(make_eml)
    run(monkeypatch, str(source), "-o", str(folder / "thread.md"))
    outside = tmp_path / "outside.md"
    outside.write_text("keep me")
    (folder / "link.md").symlink_to(outside)
    log = folder / LOG_FILE
    data = json.loads(log.read_text())
    keys = list(data["formats"]["markdown"])
    data["formats"]["markdown"] = {keys[0]: "../outside.md", keys[1]: "link.md"}
    log.write_text(json.dumps(data))

    run(monkeypatch, str(source), "-o", str(folder / "thread.md"))

    assert outside.read_text() == "keep me"
    assert "Here is the first draft." in (folder / "thread.md").read_text()


def test_planted_symlinks_are_replaced_not_written_through(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    folder = tmp_path / "out"
    folder.mkdir()
    planted = [
        "old.md",
        "20260404-20260405-draft-review.md",
        "metadata.json",
        LOG_FILE,
    ]
    for name in planted:
        (outside / name).write_text("{}")
        (folder / name).symlink_to(outside / name)

    run(monkeypatch, str(old(make_eml)), "-o", str(folder / "old.md"))
    run(monkeypatch, str(old(make_eml)), "-o", str(folder), "--by-topic")

    for name in planted:
        assert (outside / name).read_text() == "{}"
    # Fixed names replace the link; a new topic takes a free name and leaves the link alone.
    for name in ["old.md", "metadata.json", LOG_FILE]:
        assert not (folder / name).is_symlink()
    assert "Here is the first draft." in (folder / "old.md").read_text()
    assert (
        "Here is the first draft." in (folder / "20260404-20260405-draft-review-2.md").read_text()
    )


def test_secrets_in_subjects_never_reach_file_names(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_eml(html=FIRST, subject="Re: Rotate AKIAIOSFODNN7EXAMPLE today")

    run(monkeypatch, str(source), "--by-topic")

    names = [path.name.lower() for path in tmp_path.iterdir()]
    assert any("redacted" in name for name in names)
    assert not any("akiaiosfodnn7example" in name for name in names)


def test_a_tampered_log_cannot_send_normal_output_into_a_strict_file(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(monkeypatch, str(old(make_eml)))
    run(monkeypatch, str(old(make_eml)), "--strict")
    strict_file = tmp_path / "old.strict.md"
    shared = strict_file.read_text()
    log = tmp_path / LOG_FILE
    data = json.loads(log.read_text())
    keys = list(data["formats"]["markdown"])
    data["formats"] = {"markdown": dict.fromkeys(keys, strict_file.name)}
    log.write_text(json.dumps(data))

    run(monkeypatch, str(new(make_eml)))

    assert strict_file.read_text() == shared
    assert "Done, see the new version." in (tmp_path / "new.md").read_text()


def test_explicit_names_must_fit_the_mode(
    make_eml: MakeEml,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = old(make_eml)

    with pytest.raises(SystemExit, match="1 of 1 files failed"):
        run(monkeypatch, str(source), "-o", str(tmp_path / "shared.strict.md"))
    with pytest.raises(SystemExit, match="1 of 1 files failed"):
        run(monkeypatch, str(source), "--strict", "-o", str(tmp_path / "shared.md"))

    err = capsys.readouterr().err
    assert "normal output avoids" in err and "strict output needs" in err
    assert not (tmp_path / "shared.strict.md").exists() and not (tmp_path / "shared.md").exists()


def test_new_topics_never_overwrite_unlogged_files(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = tmp_path / "20260404-20260405-Draft-Review.md"
    notes.write_text("my own notes")

    run(monkeypatch, str(old(make_eml)), "--by-topic")

    assert notes.read_text() == "my own notes"
    assert (
        "Here is the first draft." in (tmp_path / "20260404-20260405-draft-review-2.md").read_text()
    )


def test_case_variants_of_names_cannot_bypass_the_mode_or_owner_checks(
    make_eml: MakeEml,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(monkeypatch, str(old(make_eml)))
    run(monkeypatch, str(old(make_eml)), "--strict")
    strict_file = tmp_path / "old.strict.md"
    shared = strict_file.read_text()
    log = tmp_path / LOG_FILE
    data = json.loads(log.read_text())
    keys = list(data["formats"]["markdown"])
    data["formats"] = {"markdown": dict.fromkeys(keys, "old.STRICT.md")}
    log.write_text(json.dumps(data))

    run(monkeypatch, str(new(make_eml)))
    unrelated = export(
        make_eml,
        "<div>Unrelated question.</div>",
        "other.eml",
        "Fri, 10 Apr 2026 10:00:00 +0000",
        "Sam Lee <sam@example.org>",
    )
    with pytest.raises(SystemExit, match="1 of 1 files failed"):
        run(monkeypatch, str(unrelated), "-o", str(tmp_path / "shared.Strict.MD"))
    run(monkeypatch, str(old(make_eml)), "--by-topic")
    with pytest.raises(SystemExit, match="1 of 1 files failed"):
        run(monkeypatch, str(unrelated), "-o", str(tmp_path / "20260404-20260405-Draft-Review.md"))

    assert strict_file.read_text() == shared
    err = capsys.readouterr().err
    assert "normal output avoids" in err and "holds topics output" in err
