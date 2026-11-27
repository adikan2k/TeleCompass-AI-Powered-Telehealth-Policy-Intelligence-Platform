"""Fetch the law that in-scope entries cite and turn it into plain text (D7).

Only sites whose robots.txt allows it are fetched. A site that forbids fetching is recorded
as `forbidden` and never worked around. Fetched documents are untrusted data.
"""

import io
import re
import tomllib
from importlib import resources
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel
from pypdf import PdfReader

from telecompass import store
from telecompass.db import Connection
from telecompass.fetch import Fetcher, FetchRefused, RobotsForbid
from telecompass.models import FetchedPage, SourceText, StoredEntry
from telecompass.scope import rule_type_for

FETCHED = "fetched"
FORBIDDEN = "forbidden"
FAILED = "failed"
UNREADABLE = "unreadable"

_BLOCK_TAGS = [
    "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt", "footer", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "ol", "p", "pre", "section", "table",
    "td", "th", "tr", "ul",
]  # fmt: skip
_DROP_TAGS = ["script", "style", "noscript", "template"]


class Override(BaseModel):
    """An official copy of a document whose cited link we may not fetch.

    It is used only once a person has opened both links, seen that they are the same document,
    and written their name in `confirmed_by`.
    """

    cited_url: str
    official_url: str
    document: str
    found_on: str = ""
    confirmed_by: str = ""
    confirmed_on: str = ""


def load_overrides(text: str | None = None) -> dict[str, Override]:
    """Confirmed overrides by cited link. Unconfirmed ones are left out."""
    if text is None:
        path = resources.files("telecompass") / "data" / "source_overrides.toml"
        text = path.read_text(encoding="utf-8")
    rows = [Override.model_validate(row) for row in tomllib.loads(text).get("override", [])]
    return {row.cited_url: row for row in rows if row.confirmed_by.strip()}


def html_to_text(html: str) -> str:
    """Readable text of an HTML page: one line per block, whitespace collapsed."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()
    for line_break in soup.find_all("br"):
        line_break.replace_with("\n")
    for block in soup.find_all(_BLOCK_TAGS):
        block.insert_before("\n")
        block.insert_after("\n")
    return _tidy(soup.get_text())


def pdf_to_text(data: bytes) -> str | None:
    """Text of a PDF, page by page, or None if it cannot be read."""
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception:  # noqa: BLE001 - a broken PDF must not stop the run
        return None
    return _tidy("\n".join(pages))


def _tidy(text: str) -> str:
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def extract_text(page: FetchedPage) -> str | None:
    """Plain text of a fetched document, or None for a type we cannot read."""
    if page.content.startswith(b"%PDF") or "pdf" in page.content_type:
        return pdf_to_text(page.content)
    if "html" in page.content_type:
        return html_to_text(page.body)
    if page.content_type.startswith("text/"):
        return _tidy(page.body)
    return None


def flrules_document_link(html: str, base_url: str) -> str | None:
    """On a Florida Administrative Code rule page, the link to the rule's own text.

    The page lists the versions of a rule, newest first, each with a "View Rule" style link
    to `readFile.asp`. This returns the first such link on the same site, or None.
    """
    soup = BeautifulSoup(html, "lxml")
    for anchor in soup.find_all("a", href=True):
        target = urljoin(base_url, str(anchor["href"]))
        same_site = urlsplit(target).netloc.removeprefix("www.") == urlsplit(
            base_url
        ).netloc.removeprefix("www.")
        if same_site and "readfile.asp" in target.lower():
            return target
    return None


# Doorway pages: a cited page that only points to the document. One hand-written step per site.
DOORWAYS = {"flrules.org": flrules_document_link}


def scoped_entries(entries: list[StoredEntry]) -> list[tuple[StoredEntry, str]]:
    """The entries that feed one of the five rule types, each with its rule type."""
    pairs = [(entry, rule_type_for(entry.category, entry.topic)) for entry in entries]
    return [(entry, rule_type) for entry, rule_type in pairs if rule_type]


def cited_urls(entries: list[StoredEntry]) -> list[str]:
    """Every distinct link the in-scope entries cite, in first-seen order."""
    seen: dict[str, None] = {}
    for entry, _ in scoped_entries(entries):
        for link in entry.source_links:
            seen.setdefault(link.url)
    return list(seen)


def fetch_source(
    conn: Connection, fetcher: Fetcher, url: str, overrides: dict[str, Override]
) -> SourceText:
    """Get one cited document, or record why we could not. One attempt, never a retry loop."""
    existing = store.latest_source_text(conn, url)
    if existing is not None and existing.outcome == FETCHED:
        return existing
    override = overrides.get(url)
    fetch_url = override.official_url if override else url

    def record(outcome: str, note: str, page: FetchedPage | None = None, text: str | None = None):
        return store.save_source_text(
            conn,
            url=url,
            fetch_url=fetch_url,
            fetched_at=page.fetched_at if page else fetcher.now(),
            outcome=outcome,
            final_url=page.url if page else None,
            http_status=page.status if page else None,
            content_type=page.content_type if page else None,
            sha256=page.sha256 if page else None,
            raw_body=page.content if page else None,
            text=text,
            note=note,
        )

    try:
        page = _fetch_following_doorway(fetcher, fetch_url)
    except RobotsForbid as error:
        return record(FORBIDDEN, str(error))
    except (FetchRefused, httpx.HTTPError) as error:
        return record(FAILED, f"{type(error).__name__}: {error}"[:500])
    text = extract_text(page)
    if not text:
        return record(UNREADABLE, f"No text could be read from type '{page.content_type}'.", page)
    note = f"Official copy confirmed by {override.confirmed_by}." if override else ""
    return record(FETCHED, note, page, text)


def _fetch_following_doorway(fetcher: Fetcher, url: str) -> FetchedPage:
    """Fetch a link and, on a known doorway page, the one document it points to."""
    fetcher.check_robots(url)
    page = fetcher.fetch(url)
    find_document = DOORWAYS.get(urlsplit(page.url).netloc.removeprefix("www."))
    if find_document is None or "html" not in page.content_type:
        return page
    target = find_document(page.body, page.url)
    if target is None:
        return page
    fetcher.check_robots(target)
    return fetcher.fetch(target)


def fetch_sources(
    conn: Connection, fetcher: Fetcher, urls: list[str], overrides: dict[str, Override]
) -> list[SourceText]:
    """Fetch every cited document once, in order."""
    return [fetch_source(conn, fetcher, url, overrides) for url in urls]
