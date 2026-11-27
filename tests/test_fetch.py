"""Fetcher tests. No request leaves the machine: httpx is given a fake transport."""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from telecompass import store
from telecompass.db import Connection
from telecompass.fetch import (
    USER_AGENT,
    AlreadyFetched,
    Fetcher,
    FetchRefused,
    fetch_jurisdiction,
)

FLORIDA = "https://www.cchpca.org/florida/"
ROBOTS = "https://www.cchpca.org/robots.txt"
PAGE = "<html><body>An invented page for tests.</body></html>"

Handler = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    """A clock that only moves when the fetcher sleeps."""

    def __init__(self) -> None:
        self.time = datetime(2026, 1, 1, tzinfo=UTC)
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.time += timedelta(seconds=seconds)


def site(robots: httpx.Response, seen: list[httpx.Request] | None = None) -> Handler:
    """A fake CCHP: the given robots.txt answer, and PAGE at the Florida address."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if str(request.url) == ROBOTS:
            return robots
        if str(request.url) == FLORIDA:
            return httpx.Response(200, text=PAGE)
        return httpx.Response(404)

    return handler


def make_fetcher(conn: Connection, handler: Handler, clock: FakeClock) -> Fetcher:
    client = httpx.Client(
        transport=httpx.MockTransport(handler), headers={"User-Agent": USER_AGENT}
    )
    return Fetcher(conn, client, wait_seconds=10.0, sleep=clock.sleep, now=clock.now)


def test_missing_robots_file_allows_the_fetch_and_stores_a_snapshot(conn: Connection) -> None:
    fetcher = make_fetcher(conn, site(httpx.Response(404)), FakeClock())

    snapshot = fetch_jurisdiction(conn, fetcher, "florida")

    assert snapshot.raw_page == PAGE
    assert snapshot.sha256 == hashlib.sha256(PAGE.encode()).hexdigest()
    assert snapshot.http_status == 200
    assert store.latest_snapshot(conn, "florida") == snapshot


def test_robots_rule_against_the_path_stops_the_fetch(conn: Connection) -> None:
    robots = httpx.Response(200, text="User-agent: *\nDisallow: /florida/\n")
    fetcher = make_fetcher(conn, site(robots), FakeClock())

    with pytest.raises(FetchRefused, match="forbids"):
        fetch_jurisdiction(conn, fetcher, "florida")

    assert store.latest_snapshot(conn, "florida") is None


def test_robots_rule_for_another_path_allows_the_fetch(conn: Connection) -> None:
    robots = httpx.Response(200, text="User-agent: *\nDisallow: /wp-admin/\n")
    fetcher = make_fetcher(conn, site(robots), FakeClock())

    assert fetch_jurisdiction(conn, fetcher, "florida").raw_page == PAGE


def test_robots_server_error_stops_the_fetch(conn: Connection) -> None:
    fetcher = make_fetcher(conn, site(httpx.Response(503)), FakeClock())

    with pytest.raises(FetchRefused, match="503"):
        fetch_jurisdiction(conn, fetcher, "florida")


def test_requests_to_one_site_are_spaced_by_the_wait(conn: Connection) -> None:
    clock = FakeClock()
    fetcher = make_fetcher(conn, site(httpx.Response(404)), clock)

    fetch_jurisdiction(conn, fetcher, "florida")

    # Two requests went out: robots.txt, then the page. The second one waited the full 10s.
    assert clock.sleeps == [10.0]
    rows = conn.execute("SELECT url, status FROM fetch_log ORDER BY id").fetchall()
    assert [(row["url"], row["status"]) for row in rows] == [(ROBOTS, 404), (FLORIDA, 200)]


def test_the_wait_survives_a_restart_because_it_reads_the_database(conn: Connection) -> None:
    clock = FakeClock()
    make_fetcher(conn, site(httpx.Response(404)), clock).get(ROBOTS)
    clock.time += timedelta(seconds=4)

    # A brand new fetcher, as after a restart, still knows about the earlier request.
    make_fetcher(conn, site(httpx.Response(404)), clock).get(ROBOTS)

    assert clock.sleeps == [6.0]


def test_crawl_delay_longer_than_ours_is_obeyed(conn: Connection) -> None:
    robots = httpx.Response(200, text="User-agent: *\nCrawl-delay: 30\nDisallow:\n")
    clock = FakeClock()
    fetcher = make_fetcher(conn, site(robots), clock)

    fetch_jurisdiction(conn, fetcher, "florida")

    assert clock.sleeps == [30.0]


def test_every_request_names_the_fetcher_honestly(conn: Connection) -> None:
    seen: list[httpx.Request] = []
    fetcher = make_fetcher(conn, site(httpx.Response(404), seen), FakeClock())

    fetch_jurisdiction(conn, fetcher, "florida")

    assert len(seen) == 2
    assert all(request.headers["user-agent"] == USER_AGENT for request in seen)
    assert USER_AGENT.startswith("TeleCompass/")


def test_second_fetch_is_refused_unless_forced(conn: Connection) -> None:
    seen: list[httpx.Request] = []
    fetcher = make_fetcher(conn, site(httpx.Response(404), seen), FakeClock())
    first = fetch_jurisdiction(conn, fetcher, "florida")

    with pytest.raises(AlreadyFetched, match="--force"):
        fetch_jurisdiction(conn, fetcher, "florida")
    assert len(seen) == 2  # the refused call sent nothing

    second = fetch_jurisdiction(conn, fetcher, "florida", force=True)
    assert second.id != first.id
    count = conn.execute("SELECT count(*) AS n FROM snapshot").fetchone()
    assert count is not None and count["n"] == 2  # the first snapshot is kept, not overwritten


def test_error_page_is_not_stored_as_a_snapshot(conn: Connection) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if str(request.url) == ROBOTS else 500)

    fetcher = make_fetcher(conn, handler, FakeClock())

    with pytest.raises(FetchRefused, match="500"):
        fetch_jurisdiction(conn, fetcher, "florida")
    assert store.latest_snapshot(conn, "florida") is None


def test_redirect_is_followed_as_its_own_waited_request(conn: Connection) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == ROBOTS:
            return httpx.Response(404)
        if str(request.url) == FLORIDA:
            return httpx.Response(301, headers={"location": "/florida-new/"})
        return httpx.Response(200, text=PAGE)

    clock = FakeClock()
    fetcher = make_fetcher(conn, handler, clock)

    snapshot = fetch_jurisdiction(conn, fetcher, "florida")

    assert snapshot.url == "https://www.cchpca.org/florida-new/"
    assert clock.sleeps == [10.0, 10.0]


def test_unknown_jurisdiction_is_refused_without_any_request(conn: Connection) -> None:
    seen: list[httpx.Request] = []
    fetcher = make_fetcher(conn, site(httpx.Response(404), seen), FakeClock())

    with pytest.raises(FetchRefused, match="Unknown jurisdiction"):
        fetch_jurisdiction(conn, fetcher, "atlantis")
    assert seen == []
