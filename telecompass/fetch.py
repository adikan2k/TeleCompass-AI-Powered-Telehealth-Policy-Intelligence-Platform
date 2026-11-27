"""Polite fetching (rule 14): robots.txt first, one request at a time, a wait, an honest name.

Everything fetched is untrusted data. It is stored and parsed, never run or obeyed.
"""

import hashlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from telecompass import store
from telecompass.db import Connection
from telecompass.models import FetchedPage, Snapshot

AGENT_NAME = "TeleCompass"
USER_AGENT = (
    f"{AGENT_NAME}/0.1 "
    "(+https://github.com/adikan2k/TeleCompass-AI-Powered-Telehealth-Policy-Intelligence-Platform)"
)
WAIT_SECONDS = 10.0
MAX_REDIRECTS = 3

CCHP_STATE_URLS = {
    "florida": "https://www.cchpca.org/florida/",
}


class FetchRefused(RuntimeError):
    """We must not, or could not safely, fetch this. Stop and tell Aditya."""


class AlreadyFetched(RuntimeError):
    """A snapshot of this page is already stored."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_client() -> httpx.Client:
    """An HTTP client that names itself honestly and never follows redirects on its own."""
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=False)


class Fetcher:
    """Sends requests one at a time and waits between requests to the same site."""

    def __init__(
        self,
        conn: Connection,
        client: httpx.Client,
        wait_seconds: float = WAIT_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.conn = conn
        self.client = client
        self.wait_seconds = wait_seconds
        self.sleep = sleep
        self.now = now

    def _wait_for(self, host: str) -> None:
        """Sleep until wait_seconds have passed since our last request to this host."""
        last = store.last_request_at(self.conn, host)
        if last is None:
            return
        remaining = self.wait_seconds - (self.now() - last).total_seconds()
        if remaining > 0:
            self.sleep(remaining)

    def _get_once(self, url: str) -> httpx.Response:
        """One request, after the wait, written to fetch_log whether it works or not."""
        host = urlsplit(url).netloc
        self._wait_for(host)
        at = self.now()
        try:
            response = self.client.get(url)
        except httpx.HTTPError:
            store.log_request(self.conn, host, url, at, None)
            raise
        store.log_request(self.conn, host, url, at, response.status_code)
        return response

    def get(self, url: str) -> httpx.Response:
        """Get a URL, following a few redirects, each as its own waited request."""
        response = self._get_once(url)
        for _ in range(MAX_REDIRECTS):
            if not response.is_redirect:
                return response
            url = urljoin(url, response.headers["location"])
            response = self._get_once(url)
        if response.is_redirect:
            raise FetchRefused(f"Too many redirects, last one at {url}")
        return response

    def check_robots(self, url: str) -> None:
        """Read the site's robots.txt and raise FetchRefused unless it lets us fetch url."""
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        response = self.get(robots_url)
        if response.status_code in (404, 410):
            return  # No robots.txt: no crawl rules are stated (RFC 9309).
        if response.status_code != 200:
            raise FetchRefused(
                f"{robots_url} answered {response.status_code}. Not fetching until it is looked at."
            )
        rules = RobotFileParser()
        rules.parse(response.text.splitlines())
        if not rules.can_fetch(AGENT_NAME, url):
            raise FetchRefused(f"{robots_url} forbids fetching {url}")
        delay = rules.crawl_delay(AGENT_NAME)
        if delay is not None:
            self.wait_seconds = max(self.wait_seconds, float(delay))

    def fetch(self, url: str) -> FetchedPage:
        """Fetch one page. Anything other than 200 is refused, so no error page is stored."""
        response = self.get(url)
        fetched_at = self.now()
        if response.status_code != 200:
            raise FetchRefused(f"{url} answered {response.status_code}")
        return FetchedPage(
            url=str(response.url),
            status=response.status_code,
            fetched_at=fetched_at,
            sha256=hashlib.sha256(response.content).hexdigest(),
            body=response.text,
        )


def fetch_jurisdiction(
    conn: Connection, fetcher: Fetcher, jurisdiction: str, force: bool = False
) -> Snapshot:
    """Fetch a jurisdiction's CCHP page once and store it as a snapshot."""
    if jurisdiction not in CCHP_STATE_URLS:
        known = ", ".join(sorted(CCHP_STATE_URLS))
        raise FetchRefused(f"Unknown jurisdiction '{jurisdiction}'. Known: {known}")
    existing = store.latest_snapshot(conn, jurisdiction)
    if existing is not None and not force:
        raise AlreadyFetched(
            f"{jurisdiction} was already fetched at {existing.fetched_at:%Y-%m-%d %H:%M} UTC "
            f"(snapshot {existing.id}). Use --force to fetch again."
        )
    url = CCHP_STATE_URLS[jurisdiction]
    fetcher.check_robots(url)
    page = fetcher.fetch(url)
    return store.save_snapshot(conn, jurisdiction, page)
