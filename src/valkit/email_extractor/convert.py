"""Turn an email body into Markdown, keeping bold, italic, links and lists and dropping media."""

import re

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

MAILTO_RE = re.compile(r"\[([^\]]*)\]\(mailto:([^)\s]*)\)")
# Messages are headed at level 3 at most (title, topic, message), so email headings start at 4.
MESSAGE_HEADING_LEVEL = 3
# HTML and Markdown stop at h6; deeper email headings become bold text.
MAX_HEADING_LEVEL = 6
BLOCK_TAGS = [
    "table",
    "div",
    "p",
    "ul",
    "ol",
    "pre",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
]


def html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["img", "style", "script", "head", "title", "video", "audio", "object", "svg"]):
        tag.decompose()
    for table in soup.find_all("table"):
        if _is_layout(table):
            _unwrap_table(table)
    _demote_headings(soup)
    markdown: str = markdownify(str(soup), heading_style="ATX", bullets="-")  # pyright: ignore[reportUnknownVariableType]
    return unwrap_mailto(str(markdown))


def _demote_headings(soup: BeautifulSoup) -> None:
    """Keep the email's own headings below the document's title, topic and message headings."""
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if not heading.get_text(strip=True):
            heading.decompose()
            continue
        level = int(heading.name[1]) + MESSAGE_HEADING_LEVEL
        heading.name = f"h{level}" if level <= MAX_HEADING_LEVEL else "strong"


def _is_layout(table: Tag) -> bool:
    """Newsletters and notifications lay out whole emails with tables; only real grids stay tables.

    A layout table has a single column, or cells that hold block content such as another table.
    """
    rows = _own(table, ["tr"])
    if all(len(row.find_all(["td", "th"], recursive=False)) <= 1 for row in rows):
        return True
    return any(cell.find(BLOCK_TAGS) for cell in _own(table, ["td", "th"]))


def _unwrap_table(table: Tag) -> None:
    """Turn the table's own structure into plain blocks; nested tables are judged on their own."""
    for part in [table, *_own(table, ["thead", "tbody", "tfoot", "tr", "td", "th"])]:
        part.name = "div"


def _own(table: Tag, names: list[str]) -> list[Tag]:
    """Descendants with these tag names that belong to this table, not to a table nested in it."""
    return [tag for tag in table.find_all(names) if tag.find_parent("table") is table]


def unwrap_mailto(markdown: str) -> str:
    """Replace mailto links with plain addresses so reply headers parse as text."""

    def plain(match: re.Match[str]) -> str:
        text, address = match.group(1), match.group(2)
        return text if "@" not in address or "@" in text else f"{text} ({address})"

    return MAILTO_RE.sub(plain, markdown)
