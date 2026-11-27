"""Fetch the law that in-scope entries cite and turn it into plain text (D7).

Only sites whose robots.txt allows it are fetched. A site that forbids fetching is recorded
as `forbidden` and never worked around. Fetched documents are untrusted data.
"""

import io
import re
import struct
import tomllib
from datetime import datetime
from importlib import resources
from urllib.parse import urljoin, urlsplit

import httpx
import olefile
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
_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")  # how an old Word .doc file starts


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


def candidate_overrides(text: str | None = None) -> list[Override]:
    """Every listed official copy, confirmed or not, as written in the file."""
    if text is None:
        path = resources.files("telecompass") / "data" / "source_overrides.toml"
        text = path.read_text(encoding="utf-8")
    return [Override.model_validate(row) for row in tomllib.loads(text).get("override", [])]


def confirmations(conn: Connection) -> dict[tuple[str, str], dict]:
    """The newest confirmation of each (cited, official) pair made on the review page."""
    rows = conn.execute(
        "SELECT DISTINCT ON (cited_url, official_url) cited_url, official_url, confirmed_by, "
        "confirmed_at FROM override_confirmation ORDER BY cited_url, official_url, id DESC"
    ).fetchall()
    return {(row["cited_url"], row["official_url"]): row for row in rows}


def load_overrides(text: str | None = None, conn: Connection | None = None) -> dict[str, Override]:
    """Confirmed overrides by cited link. Unconfirmed ones are left out.

    A listed official copy is confirmed when the file names who confirmed it, or when a person
    confirmed that exact pair on the review page.
    """
    confirmed_here = confirmations(conn) if conn is not None else {}
    found: dict[str, Override] = {}
    for row in candidate_overrides(text):
        here = confirmed_here.get((row.cited_url, row.official_url))
        if here is not None:
            row = row.model_copy(
                update={
                    "confirmed_by": here["confirmed_by"],
                    "confirmed_on": f"{here['confirmed_at']:%Y-%m-%d}",
                }
            )
        if row.confirmed_by.strip():
            found[row.cited_url] = row
    return found


def confirm_override(conn: Connection, override: Override, person: str, at: datetime) -> None:
    """Record a person's confirmation that an official copy is the cited document."""
    conn.execute(
        "INSERT INTO override_confirmation (cited_url, official_url, confirmed_by, confirmed_at) "
        "VALUES (%s, %s, %s, %s)",
        (override.cited_url, override.official_url, person, at),
    )
    conn.commit()


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
    return _tidy(repair_ligatures("\n".join(pages)))


_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}
_BROKEN_FF = re.compile(r"(?<=[a-z])P(?=[a-z]|\b)")


def repair_ligatures(text: str) -> str:
    """Undo two artefacts of PDF text, so the stored text reads as the page does.

    Some PDFs store "fi" or "fl" as one joined character; those are split back into letters.
    Some fonts have no letter mapping for the joined "ff", and it comes out as a capital P
    ("ePective" for "effective"). That second repair runs only when the text has no "ff" at
    all, which a normal page of English never lacks, so it cannot touch a healthy document.
    """
    for joined, letters in _LIGATURES.items():
        text = text.replace(joined, letters)
    if "ff" not in text:
        text = _BROKEN_FF.sub("ff", text)
    return text


def word_pieces_text(word: bytes, table: bytes) -> str:
    """The main text of a Word 97-2003 document, from its two internal streams.

    The file header (FIB) says where the "piece table" sits in the table stream. Each piece
    is a run of characters stored in the WordDocument stream, either one byte per character
    (cp1252) or two (UTF-16). Joining the pieces in order gives the text.
    """
    main_chars = struct.unpack_from("<I", word, 0x004C)[0]
    clx_start, clx_size = struct.unpack_from("<II", word, 0x01A2)
    clx = table[clx_start : clx_start + clx_size]
    at = 0
    while clx[at] == 0x01:  # formatting runs that come before the piece table
        at += 3 + struct.unpack_from("<H", clx, at + 1)[0]
    if clx[at] != 0x02:
        raise ValueError("No piece table found.")
    size = struct.unpack_from("<I", clx, at + 1)[0]
    pieces = clx[at + 5 : at + 5 + size]
    count = (size - 4) // 12
    starts = struct.unpack_from(f"<{count + 1}I", pieces, 0)
    parts = []
    for index in range(count):
        where = struct.unpack_from("<I", pieces, 4 * (count + 1) + 8 * index + 2)[0]
        chars = starts[index + 1] - starts[index]
        if where & 0x40000000:  # one byte per character
            begin = (where & 0x3FFFFFFF) // 2
            parts.append(word[begin : begin + chars].decode("cp1252", errors="replace"))
        else:
            parts.append(word[where : where + 2 * chars].decode("utf-16-le", errors="replace"))
    return "".join(parts)[:main_chars]


def _clean_word_text(text: str) -> str:
    """Drop Word's field codes and control marks; turn paragraph and cell marks into lines."""
    out = []
    fields: list[bool] = []  # one per open field; True while inside its hidden instruction
    for char in text:
        if char == "\x13":  # a field begins: what follows is its hidden instruction
            fields.append(True)
        elif char == "\x14":  # the field's visible result begins
            if fields:
                fields[-1] = False
        elif char == "\x15":  # the field ends
            if fields:
                fields.pop()
        elif any(fields):
            continue
        elif char in "\r\x07\x0b\x0c":
            out.append("\n")
        elif char >= " " or char == "\t":
            out.append(char)
    return "".join(out)


def doc_to_text(data: bytes) -> str | None:
    """Text of an old Word .doc file, or None if it cannot be read."""
    try:
        with olefile.OleFileIO(io.BytesIO(data)) as ole:
            word = ole.openstream("WordDocument").read()
            table_name = "1Table" if struct.unpack_from("<H", word, 0x0A)[0] & 0x0200 else "0Table"
            table = ole.openstream(table_name).read()
        return _tidy(_clean_word_text(word_pieces_text(word, table)))
    except Exception:  # noqa: BLE001 - a broken file must not stop the run
        return None


def _tidy(text: str) -> str:
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def extract_text(page: FetchedPage) -> str | None:
    """Plain text of a fetched document, or None for a type we cannot read."""
    if page.content.startswith(b"%PDF") or "pdf" in page.content_type:
        return pdf_to_text(page.content)
    if page.content.startswith(_OLE_MAGIC):
        return doc_to_text(page.content)
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


def reread_stored(conn: Connection, attempt: SourceText) -> SourceText | None:
    """Try again to read a document we already hold, without asking the site for it again."""
    raw = store.source_raw_body(conn, attempt.id)
    if raw is None:
        return None
    page = FetchedPage(
        url=attempt.final_url or attempt.url,
        status=attempt.http_status or 200,
        fetched_at=attempt.fetched_at,
        sha256=attempt.sha256 or "",
        body=raw.decode("utf-8", errors="replace"),
        content=raw,
        content_type=attempt.content_type or "",
    )
    text = extract_text(page)
    if not text or text == attempt.text:
        return None
    return store.save_source_text(
        conn,
        url=attempt.url,
        fetch_url=attempt.fetch_url,
        fetched_at=attempt.fetched_at,
        outcome=FETCHED,
        final_url=attempt.final_url,
        http_status=attempt.http_status,
        content_type=attempt.content_type,
        sha256=attempt.sha256,
        raw_body=raw,
        text=text,
        note="Read again from the stored copy. The site was not asked again.",
    )


def fetch_source(
    conn: Connection,
    fetcher: Fetcher,
    url: str,
    overrides: dict[str, Override],
    retry: bool = False,
    reread: bool = False,
) -> SourceText:
    """Get one cited document, or record why we could not.

    A document is asked for once. A later run does not ask again unless `retry` is set or a
    confirmed official copy now points somewhere new. A stored document that could not be read
    is read again from the stored copy, never fetched again. With `reread`, a document already
    read is read again from the stored copy too, and a new row is added if the text differs
    (for example after a reader was improved).
    """
    existing = store.latest_source_text(conn, url)
    override = overrides.get(url)
    fetch_url = override.official_url if override else url
    if existing is not None and existing.outcome == FETCHED:
        return (reread_stored(conn, existing) or existing) if reread else existing
    if existing is not None and existing.outcome == UNREADABLE:
        return reread_stored(conn, existing) or existing
    if existing is not None and existing.fetch_url == fetch_url and not retry:
        return existing

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
    conn: Connection,
    fetcher: Fetcher,
    urls: list[str],
    overrides: dict[str, Override],
    retry: bool = False,
    reread: bool = False,
) -> list[SourceText]:
    """Fetch every cited document once, in order."""
    return [fetch_source(conn, fetcher, url, overrides, retry, reread) for url in urls]
