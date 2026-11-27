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
