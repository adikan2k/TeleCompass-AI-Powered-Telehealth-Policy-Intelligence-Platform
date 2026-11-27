"""The typed shapes passed between the fetcher, the parser, the store and the command line."""

from datetime import date, datetime

from pydantic import BaseModel


class FetchedPage(BaseModel):
    """One page as it came off the network, before it is stored."""

    url: str
    status: int
    fetched_at: datetime
    sha256: str
    body: str
    content: bytes = b""
    content_type: str = ""


class Snapshot(BaseModel):
    """A stored raw page. Never changed after it is written."""

    id: int
    jurisdiction: str
    url: str
    fetched_at: datetime
    sha256: str
    http_status: int
    raw_page: str


class GlanceAnswer(BaseModel):
    """One line of CCHP's "At a Glance" panel. Together they are the answer key."""

    section: str
    question: str
    answer: str


class SourceLink(BaseModel):
    """One link inside a SOURCE line."""

    label: str
    url: str


class Entry(BaseModel):
    """One CCHP entry: a passage under a category and topic, ending in a SOURCE line.

    source_name is the citation as CCHP wrote it. source_url is the first link in it, and
    source_links holds every link, because one SOURCE line can cite several documents.
    """

    category: str
    topic: str
    subtopic: str | None = None
    text: str
    no_reference_found: bool = False
    source_name: str | None = None
    source_url: str | None = None
    source_links: list[SourceLink] = []
    accessed: str | None = None
    last_updated: date | None = None


class ParsedPage(BaseModel):
    """Everything the parser read from one snapshot, plus what it could not place."""

    answers: list[GlanceAnswer]
    entries: list[Entry]
    problems: list[str]


class ParseRun(BaseModel):
    """A record of one parser pass over one snapshot."""

    id: int
    snapshot_id: int
    parser_version: str
    parsed_at: datetime
    entry_count: int
    answer_count: int
    problems: list[str]


class StoredEntry(Entry):
    """An entry as read back from the database, with its row id."""

    id: int


class SourceText(BaseModel):
    """One attempt to get a cited document. `text` is what quotes are checked against."""

    id: int
    url: str
    fetch_url: str
    final_url: str | None = None
    fetched_at: datetime
    outcome: str
    http_status: int | None = None
    content_type: str | None = None
    sha256: str | None = None
    text: str | None = None
    note: str | None = None


class Rule(BaseModel):
    """One rule row. `status` and `quote_verified` are always set by code, never by a model."""

    id: int
    extraction_run_id: int
    entry_id: int
    jurisdiction: str
    rule_type: str
    aspect: str
    effect: str
    profession: str | None = None
    payer: str | None = None
    modality: str | None = None
    service: str | None = None
    compact: str | None = None
    conditions: list[str] = []
    summary: str
    quote: str | None = None
    quote_verified: bool
    quote_note: str | None = None
    source_text_id: int | None = None
    source_url: str | None = None
    source_fetched_at: datetime | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status: str
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
