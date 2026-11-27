"""Our own pointers to official pages, for law that CCHP's state pages do not map (D13).

For a state, CCHP's page is the map: each entry points to the law. For federal Medicare the
map is a short hand-written file, `data/<name>_pointers.toml`: what to look for, in our own
words, and the official page to read. A pointer is stored as an entry, so the same fetching,
extraction, quote check and review apply to it as to any state entry.
"""

import hashlib
import tomllib
from datetime import datetime
from importlib import resources

from telecompass import store
from telecompass.db import Connection
from telecompass.models import Entry, FetchedPage, ParsedPage, ParseRun, SourceLink

PARSER_VERSION = "pointers-1"


def pointer_file(jurisdiction: str) -> str:
    path = resources.files("telecompass") / "data" / f"{jurisdiction}_pointers.toml"
    return path.read_text(encoding="utf-8")


def parse_pointers(text: str) -> ParsedPage:
    """Read a pointer file into entries. A pointer without a source link is reported."""
    entries, problems = [], []
    for row in tomllib.loads(text).get("pointer", []):
        links = [
            SourceLink(label=link["label"], url=link["url"]) for link in row.get("sources", [])
        ]
        if not links:
            problems.append(f"{row.get('category')} / {row.get('topic')}: pointer has no source.")
            continue
        entries.append(
            Entry(
                category=row["category"],
                topic=row["topic"],
                subtopic=row.get("subtopic"),
                text=" ".join(row["text"].split()),
                source_name="; ".join(link.label for link in links),
                source_url=links[0].url,
                source_links=links,
            )
        )
    return ParsedPage(answers=[], entries=entries, problems=problems)


def store_pointers(conn: Connection, jurisdiction: str, text: str, at: datetime) -> ParseRun:
    """Store a pointer file as a snapshot and its pointers as entries."""
    page = FetchedPage(
        url=f"telecompass:data/{jurisdiction}_pointers.toml",
        status=200,
        fetched_at=at,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        body=text,
    )
    snapshot = store.save_snapshot(conn, jurisdiction, page)
    return store.save_parse(conn, snapshot, parse_pointers(text), PARSER_VERSION, at)
