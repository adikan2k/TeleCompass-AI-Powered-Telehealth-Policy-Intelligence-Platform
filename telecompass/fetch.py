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


class RobotsForbid(FetchRefused):
    """The site's robots.txt says no. Never worked around."""


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
        self.host_wait: dict[str, float] = {}  # a site's own crawl delay, when longer than ours
        self._robots: dict[str, RobotFileParser | None] = {}  # read once per site per run

    def _wait_for(self, host: str) -> None:
        """Sleep until the wait has passed since our last request to this host."""
        last = store.last_request_at(self.conn, host)
        if last is None:
            return
        wait = self.host_wait.get(host, self.wait_seconds)
        remaining = wait - (self.now() - last).total_seconds()
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

    def _robots_rules(self, url: str) -> RobotFileParser | None:
        """The site's robots.txt rules, read once per run. None means it has no robots.txt."""
        parts = urlsplit(url)
        site = f"{parts.scheme}://{parts.netloc}"
        if site in self._robots:
            return self._robots[site]
        robots_url = f"{site}/robots.txt"
        response = self.get(robots_url)
        if response.status_code in (404, 410):
            rules = None  # No robots.txt: no crawl rules are stated (RFC 9309).
        elif response.status_code != 200:
            raise FetchRefused(
                f"{robots_url} answered {response.status_code}. Not fetching until it is looked at."
            )
        else:
            rules = RobotFileParser()
            rules.parse(response.text.splitlines())
            delay = rules.crawl_delay(AGENT_NAME)
            if delay is not None:
                self.host_wait[parts.netloc] = max(self.wait_seconds, float(delay))
        self._robots[site] = rules
        return rules

    def check_robots(self, url: str) -> None:
        """Raise RobotsForbid unless the site's robots.txt lets us fetch url."""
        rules = self._robots_rules(url)
        if rules is not None and not rules.can_fetch(AGENT_NAME, url):
            raise RobotsForbid(f"robots.txt forbids fetching {url}")

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
            content=response.content,
            content_type=response.headers.get("content-type", "").split(";")[0].strip().lower(),
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
