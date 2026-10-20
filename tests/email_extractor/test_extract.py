import json
import re
import sys
from pathlib import Path

import pytest

from valkit.email_extractor.cli import extract, main

from .conftest import MakeEml

GMAIL_THREAD = """
<div>Hi Jane,<br>The <b>budget</b> is <i>final</i>. See <a href="https://example.com/plan">the plan</a>.</div>
<div><br></div>
<div><b>Best,</b><br><b>John Smith</b><br>CTO<br>
<a href="https://example.com">www.example.com</a></div>
<div class="gmail_quote">
<div class="gmail_attr">On Sun, Apr 5, 2026 at 6:30 PM Jane Doe &lt;<a href="mailto:jane@example.com">jane@example.com</a>&gt; wrote:</div>
<blockquote>
<div>John,<br>Is the budget final?</div>
<div>Thanks,<br>Jane</div>
<div>Jane Doe<br>Managing Partner<br>Example Consulting<br>
<a href="tel:+15550100">555-0100</a></div>
<div>вс, 5 апр. 2026 г. в 09:15, John Smith &lt;<a href="mailto:john@example.com">john@example.com</a>&gt;:</div>
<blockquote>
<div>Jane,<br>Here is the first draft.</div>
<div><b>Best,</b><br><b>John Smith</b><br>CTO<br>
<a href="https://example.com">www.example.com</a></div>
</blockquote>
</blockquote>
</div>
"""  # noqa: E501, RUF001

OUTLOOK_THREAD = """
<div>Sam,<br>Sounds good.<br>From: Plan A<br>To: Plan B<br>That is the change.</div>
<div>Jane</div>
<hr>
<div><b>From:</b> Sam Lee &lt;sam@example.org&gt;<br></div>
<div>&nbsp;</div>
<div><b>Sent:</b> Friday, April 3, 2026 4:10 AM<br>
<b>To:</b> Jane Doe &lt;jane@example.com&gt;<br>
<b>Cc:</b> John Smith &lt;john@example.com&gt;;<br>Alex Roe &lt;alex@example.net&gt;<br>
<b>Subject:</b> Budget Review</div>
<div>Jane, can we move the budget to Plan B?</div>
"""


def frontmatter(markdown: str) -> dict[str, object]:
    found = re.match(r"---\n(.*?)\n---\n", markdown, re.DOTALL)
    assert found
    return json.loads(found.group(1))


def test_gmail_thread_is_split_oldest_first(make_eml: MakeEml) -> None:
    markdown = extract(make_eml(html=GMAIL_THREAD))

    headings = re.findall(r"^### (.*)$", markdown, re.MULTILINE)
    assert headings == [
        "John Smith · 2026-04-05 09:15",
        "Jane Doe · 2026-04-05 18:30",
        "John Smith · 2026-04-06 10:00",
    ]
    assert "Here is the first draft." in markdown
    assert "Is the budget final?" in markdown


def test_formatting_and_links_are_kept(make_eml: MakeEml) -> None:
    markdown = extract(make_eml(html=GMAIL_THREAD))

    assert "The **budget** is *final*. See [the plan](https://example.com/plan)." in markdown
    assert "**To:** Jane Doe" in markdown


def test_signatures_are_removed_and_become_contacts(make_eml: MakeEml) -> None:
    markdown = extract(make_eml(html=GMAIL_THREAD))
    body = markdown.split("\n---\n", 2)[2]

    for leftover in (
        "CTO",
        "Managing Partner",
        "555-0100",
        "Thanks,",
        "Best,",
        "\nJane\n",
    ):
        assert leftover not in body
    participants = frontmatter(markdown)["participants"]
    assert participants == [
        {
            "name": "John Smith",
            "emails": ["john@example.com"],
            "links": ["https://example.com"],
            "details": ["CTO"],
        },
        {
            "name": "Jane Doe",
            "emails": ["jane@example.com"],
            "phones": ["555-0100"],
            "details": ["Managing Partner", "Example Consulting"],
        },
    ]


def test_outlook_headers_topics_and_prose_lookalikes(make_eml: MakeEml) -> None:
    markdown = extract(make_eml(html=OUTLOOK_THREAD, sender="Jane Doe <jane@example.com>"))

    assert re.findall(r"^## (.*)$", markdown, re.MULTILINE) == [
        "Budget Review",
        "Project Kickoff",
    ]
    assert "### Sam Lee · 2026-04-03 04:10" in markdown
    assert "**Cc:** John Smith, Alex Roe" in markdown
    # Header-like prose without a date stays in the message body, as one paragraph.
    assert "From: Plan A To: Plan B That is the change." in markdown


def test_media_and_attachments_are_skipped(make_eml: MakeEml) -> None:
    html = '<div>See logo <img src="cid:logo@example"> below.</div>'
    markdown = extract(make_eml(html=html, image=True, attachment=True))

    assert "See logo below." in markdown
    for media in ("cid:", "![", "ATTACHMENT BODY TEXT", "report.pdf"):
        assert media not in markdown


def test_plain_text_only_email(make_eml: MakeEml) -> None:
    text = "Jane,\nThe plan is ready.\n\nOn Sun, Apr 5, 2026 at 6:30 PM Jane Doe <jane@example.com> wrote:\n> Ready?\n"  # noqa: E501
    markdown = extract(make_eml(text=text))

    assert "### Jane Doe · 2026-04-05 18:30\n\nReady?" in markdown
    assert "The plan is ready." in markdown


def test_forwarded_duplicates_are_dropped(make_eml: MakeEml) -> None:
    quoted = (
        "<div>Status is green.</div>"
        "<div>On Sun, Apr 5, 2026 at 6:30 PM Jane Doe &lt;jane@example.com&gt; wrote:</div>"
        "<blockquote><div>Any news?</div></blockquote>"
    )
    html = (
        f"<div>Forwarding.</div><div>On Sun, Apr 5, 2026 at 7:00 PM John Smith "
        f"&lt;john@example.com&gt; wrote:</div><blockquote>{quoted}</blockquote>"
        f"<div>On Sun, Apr 5, 2026 at 7:00 PM John Smith &lt;john@example.com&gt; wrote:</div>"
        f"<blockquote>{quoted}</blockquote>"
    )
    markdown = extract(make_eml(html=html))

    assert markdown.count("Status is green.") == 1
    assert markdown.count("Any news?") == 1


FIRST_DRAFT = (
    "<div>On Sun, Apr 5, 2026 at 9:15 AM John Smith &lt;john@example.com&gt; wrote:</div>"
    "<blockquote><div>Here is the first draft.</div></blockquote>"
)
QUESTION = (
    "<div>On Sun, Apr 5, 2026 at 6:30 PM Jane Doe &lt;jane@example.com&gt; wrote:</div>"
    f"<blockquote><div>Is the budget final?</div>{FIRST_DRAFT}</blockquote>"
)
ANSWER = "<div>The budget is final.</div><div>Best,<br>John Smith<br>CTO</div>"


@pytest.mark.parametrize(
    "html",
    [ANSWER + QUESTION + QUESTION, ANSWER + QUESTION + FIRST_DRAFT],
    ids=["quoted-block-repeated", "oldest-message-repeated"],
)
def test_repeated_quotes_keep_each_message_once(make_eml: MakeEml, html: str) -> None:
    # The signature moves into the frontmatter as a contact, so check the document after it.
    document = extract(make_eml(html=html)).split("\n# ", 1)[1]

    headings = re.findall(r"^### (.*)$", document, re.MULTILINE)
    assert headings == [
        "John Smith · 2026-04-05 09:15",
        "Jane Doe · 2026-04-05 18:30",
        "John Smith · 2026-04-06 10:00",
    ]
    bodies = re.split(r"^### .*$", document, flags=re.MULTILINE)[1:]
    assert ["Here is the first draft." in body for body in bodies] == [True, False, False]
    assert ["Is the budget final?" in body for body in bodies] == [False, True, False]
    assert document.count("Here is the first draft.") == 1
    assert "CTO" not in document and ">" not in document


NOTIFICATION = """
<table><tr><td>
  <h1><img src="cid:logo"></h1>
  <table><tr><td><h2>New issue</h2><p>Something broke.</p></td></tr></table>
  <table>
    <tr><td>Project</td><td>web-app</td></tr>
    <tr><td>Level</td><td>error</td></tr>
  </table>
</td></tr></table>
"""


def test_layout_tables_become_text_and_data_tables_stay(make_eml: MakeEml) -> None:
    markdown = extract(make_eml(html=NOTIFICATION, subject="Alert"))
    body = markdown.split("### John Smith", 1)[1]

    assert "Something broke." in body
    assert not re.search(r"^\|.*Something broke", body, re.MULTILINE)
    assert "| Project | web-app |" in body
    assert "| Level | error |" in body


def test_email_headings_sit_below_message_headings(make_eml: MakeEml) -> None:
    markdown = extract(make_eml(html=NOTIFICATION, subject="Alert"))

    assert re.findall(r"^#+.*$", markdown, re.MULTILINE) == [
        "# Alert",
        "### John Smith · 2026-04-06 10:00",
        "##### New issue",
    ]


STRICT_THREAD = """
<div>Hi Sam and Mary,<br>Doe here. Call me at 707-235-0660 or +44 20 7946 0958,
or write to <a href="mailto:jane.doe@example.com">jane.doe@example.com</a>.
Budget is $1.5M, then US$ 20k, USD 1,000 and 250 dollars. See
<a href="https://www.linkedin.com/in/jane-doe">my profile</a> or https://example.com/jane?id=7.
Mary Watson and Watson agree. Key: AKIAIOSFODNN7EXAMPLE</div>
<div>On Sun, Apr 5, 2026 at 6:30 PM Sam Lee &lt;sam.lee@example.org&gt; wrote:</div>
<blockquote><div>Jane, ask Lee's team.</div></blockquote>
"""


def test_strict_keeps_first_names_and_strips_personal_details(make_eml: MakeEml) -> None:
    eml = make_eml(
        html=STRICT_THREAD,
        subject="Re: Budget with Jane Doe",
        sender="Jane Doe <jane.doe@example.com>",
        to="Sam Lee <sam.lee@example.org>",
        cc="Mary Watson <mary@example.net>, ops.team@example.com",
    )
    markdown = extract(eml, strict=True)

    assert not markdown.startswith("---")
    assert markdown.startswith("# Budget with Jane\n")
    assert "### Sam · 2026-04-05 18:30" in markdown
    assert "### Jane · 2026-04-06 10:00" in markdown
    assert "**To:** Sam · **Cc:** Mary, Ops" in markdown
    assert "Jane here. Call me at `[phone]` or `[phone]`," in markdown
    assert "or write to `[email]`." in markdown
    assert "Budget is `[amount]`, then `[amount]`, `[amount]` and `[amount]`." in markdown
    assert "See my profile or `[link]`." in markdown
    assert "Mary and Mary agree." in markdown
    assert "Jane, ask Sam's team." in markdown
    assert "`[REDACTED:aws-key-1]`" in markdown
    for leaked in ("Doe", "Lee", "Watson", "@", "707", "1.5M", "linkedin", "example.com"):
        assert leaked not in markdown


def run_cli(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["email-extractor", *args])
    main()


def test_batch_expands_quoted_wildcards(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_eml(text="One.", name="mail/a.eml")
    make_eml(text="Two.", name="mail/sub/b.eml")
    make_eml(text="Ignored.", name="mail/notes.txt")

    run_cli(monkeypatch, str(tmp_path / "mail" / "**" / "*.eml"), "-o", str(tmp_path / "out"))

    assert sorted(path.name for path in (tmp_path / "out").glob("*.md")) == ["a.md", "b.md"]


def test_existing_file_with_brackets_is_taken_literally(
    make_eml: MakeEml, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_eml(text="Hello.", name="[EXT] Re: plan.eml")

    run_cli(monkeypatch, str(source))

    assert source.with_suffix(".md").exists()


def test_batch_continues_after_a_failing_file(
    make_eml: MakeEml, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = make_eml(text="Fine.", name="good.eml")
    missing = tmp_path / "missing.eml"

    with pytest.raises(SystemExit, match="1 of 2 files failed"):
        run_cli(monkeypatch, str(missing), str(good))

    assert good.with_suffix(".md").exists()


def test_pattern_without_matches_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SystemExit, match="no files match"):
        run_cli(monkeypatch, str(tmp_path / "*.eml"))
