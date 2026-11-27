"""Older copies of pages from the Internet Archive's Wayback Machine (D20).

The Archive is used for history only: what a page said before our own snapshots began. Every
request goes through the polite fetcher (robots.txt read, one request at a time, a wait, an
honest name, every request logged). A copy is stored as a snapshot marked `wayback`, dated by
the Archive's capture time, and is never mistaken for our own fetch.
"""

import json
from datetime import UTC, datetime

from pydantic import BaseModel

from telecompass import store
from telecompass.db import Connection
from telecompass.fetch import Fetcher, FetchRefused
from telecompass.models import Snapshot

CDX = "https://web.archive.org/cdx/search/cdx"


class Capture(BaseModel):
    timestamp: str  # YYYYMMDDhhmmss, the Archive's own form
    digest: str

    @property
    def captured_at(self) -> datetime:
        return datetime.strptime(self.timestamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def list_captures(fetcher: Fetcher, url: str, since: str, until: str) -> list[Capture]:
    """Distinct captures of a page between two years, oldest first."""
    query = (
        f"{CDX}?url={url}&output=json&from={since}&to={until}"
        "&filter=statuscode:200&collapse=digest&fl=timestamp,digest"
    )
    fetcher.check_robots(query)
    response = fetcher.get(query)
    if response.status_code != 200:
        raise FetchRefused(f"The Archive's index answered {response.status_code}")
    rows = json.loads(response.text) if response.text.strip() else []
    return [Capture(timestamp=row[0], digest=row[1]) for row in rows[1:]]


def capture_url(url: str, timestamp: str) -> str:
    """The Archive's address for the page exactly as captured, without its own toolbar."""
    return f"https://web.archive.org/web/{timestamp}id_/{url}"


def store_capture(
    conn: Connection, fetcher: Fetcher, jurisdiction: str, url: str, timestamp: str
) -> Snapshot:
    """Fetch one capture and store it as a `wayback` snapshot dated by the capture."""
    address = capture_url(url, timestamp)
    fetcher.check_robots(address)
    page = fetcher.fetch(address)
    captured_at = Capture(timestamp=timestamp, digest="").captured_at
    return store.save_snapshot(conn, jurisdiction, page, origin="wayback", captured_at=captured_at)
