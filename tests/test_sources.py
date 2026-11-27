"""Fetching cited law. No request leaves the machine: httpx is given a fake transport."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from fakes import ALERT_7, CODE_59_1, STATUTE_200_1, STATUTE_200_2, store_invented_page
from telecompass import sources, store
from telecompass.db import Connection
from telecompass.fetch import USER_AGENT, Fetcher

Handler = Callable[[httpx.Request], httpx.Response]
LAW_HTML = (
    "<html><head><style>p{color:red}</style><script>alert('x')</script></head><body>"
    "<h1>59-1 Telemedicine</h1><p>The programme <b>reimburses</b> live video.</p>"
    "<ul><li>First item</li><li>Second<br>item</li></ul></body></html>"
)


class Clock:
    def __init__(self) -> None:
        self.time = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.time += timedelta(seconds=seconds)


def fetcher_for(conn: Connection, handler: Handler) -> Fetcher:
    clock = Clock()
    client = httpx.Client(
        transport=httpx.MockTransport(handler), headers={"User-Agent": USER_AGENT}
    )
    return Fetcher(conn, client, sleep=clock.sleep, now=clock.now)


def site(pages: dict[str, httpx.Response], robots: str | None = None, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if seen is not None:
            seen.append(url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=robots) if robots is not None else httpx.Response(404)
        return pages.get(url, httpx.Response(404))

    return handler


def html(text: str) -> httpx.Response:
    return httpx.Response(200, text=text, headers={"content-type": "text/html; charset=utf-8"})


def tiny_pdf(text: str) -> bytes:
    """A one-page PDF holding one line of text, built by hand."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 6\n0000000000 65535 f \n"
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % xref
    return out


def test_html_becomes_one_line_per_block_without_scripts_or_styles() -> None:
    assert sources.html_to_text(LAW_HTML) == (
        "59-1 Telemedicine\nThe programme reimburses live video.\nFirst item\nSecond\nitem"
    )


def test_pdf_text_is_read() -> None:
    assert sources.pdf_to_text(tiny_pdf("Telemedicine is covered")) == "Telemedicine is covered"


def test_broken_pdf_gives_none_not_a_crash() -> None:
    assert sources.pdf_to_text(b"%PDF-1.4 not really a pdf") is None


def test_only_links_of_in_scope_entries_are_listed_once_each(conn: Connection) -> None:
    _, _, entries = store_invented_page(conn)
    # The Definitions entry (statute 100-1) is out of scope; the eligible-sites one was dropped.
    assert sources.cited_urls(entries) == [STATUTE_200_1, STATUTE_200_2, CODE_59_1, ALERT_7]


def test_allowed_document_is_stored_with_its_text(conn: Connection) -> None:
    fetcher = fetcher_for(conn, site({CODE_59_1: html(LAW_HTML)}))

    result = sources.fetch_source(conn, fetcher, CODE_59_1, {})

    assert result.outcome == sources.FETCHED
    assert "The programme reimburses live video." in result.text
    assert result.sha256 and result.http_status == 200 and result.content_type == "text/html"
    assert store.latest_source_text(conn, CODE_59_1) == result


def test_pdf_document_is_stored_as_text(conn: Connection) -> None:
    pdf = httpx.Response(
        200, content=tiny_pdf("Coverage policy text"), headers={"content-type": "application/pdf"}
    )
    fetcher = fetcher_for(conn, site({CODE_59_1: pdf}))

    result = sources.fetch_source(conn, fetcher, CODE_59_1, {})

    assert (result.outcome, result.text) == (sources.FETCHED, "Coverage policy text")


def test_site_that_forbids_fetching_is_recorded_and_never_requested(conn: Connection) -> None:
    seen: list[str] = []
    handler = site({ALERT_7: html(LAW_HTML)}, robots="User-agent: *\nDisallow: /\n", seen=seen)

    result = sources.fetch_source(conn, fetcher_for(conn, handler), ALERT_7, {})

    assert result.outcome == sources.FORBIDDEN
    assert result.text is None
    assert seen == ["https://example.org/robots.txt"]  # the document itself was never asked for


def test_server_error_is_recorded_as_failed(conn: Connection) -> None:
    fetcher = fetcher_for(conn, site({CODE_59_1: httpx.Response(500)}))

    result = sources.fetch_source(conn, fetcher, CODE_59_1, {})

    assert result.outcome == sources.FAILED
    assert "500" in result.note


def test_type_we_cannot_read_is_stored_as_unreadable(conn: Connection) -> None:
    image = httpx.Response(200, content=b"\x89PNG....", headers={"content-type": "image/png"})
    fetcher = fetcher_for(conn, site({CODE_59_1: image}))

    assert sources.fetch_source(conn, fetcher, CODE_59_1, {}).outcome == sources.UNREADABLE


def test_document_already_fetched_is_not_fetched_again(conn: Connection) -> None:
    seen: list[str] = []
    fetcher = fetcher_for(conn, site({CODE_59_1: html(LAW_HTML)}, seen=seen))

    first = sources.fetch_source(conn, fetcher, CODE_59_1, {})
    second = sources.fetch_source(conn, fetcher, CODE_59_1, {})

    assert second == first
    assert seen.count(CODE_59_1) == 1


def test_override_is_ignored_until_a_person_confirms_it() -> None:
    text = """
    [[override]]
    cited_url = "https://blocked.example/a"
    official_url = "https://official.example/a"
    document = "Alert A"

    [[override]]
    cited_url = "https://blocked.example/b"
    official_url = "https://official.example/b"
    document = "Alert B"
    confirmed_by = "Aditya"
    confirmed_on = "2026-12-01"
    """
    overrides = sources.load_overrides(text)

    assert list(overrides) == ["https://blocked.example/b"]


def test_no_bundled_override_is_live_without_a_name_on_it() -> None:
    assert all(row.confirmed_by.strip() for row in sources.load_overrides().values())


def test_confirmed_override_fetches_the_official_copy(conn: Connection) -> None:
    official = "https://official.example/alert-7"
    override = sources.Override(
        cited_url=ALERT_7, official_url=official, document="Alert 7", confirmed_by="Aditya"
    )
    seen: list[str] = []
    fetcher = fetcher_for(conn, site({official: html(LAW_HTML)}, seen=seen))

    result = sources.fetch_source(conn, fetcher, ALERT_7, {ALERT_7: override})

    assert result.outcome == sources.FETCHED
    assert (result.url, result.fetch_url) == (ALERT_7, official)
    assert "confirmed by Aditya" in result.note
    assert ALERT_7 not in seen  # the blocked link itself is never requested


def test_doorway_page_is_followed_one_step_to_the_document(conn: Connection) -> None:
    door = "https://www.flrules.org/gateway/ruleNo.asp?id=59G-1.057"
    document = "https://www.flrules.org/gateway/readFile.asp?sid=0&type=1&file=59G-1.057.doc"
    door_html = (
        '<html><body><a href="/elsewhere">Home</a>'
        '<a href="readFile.asp?sid=0&amp;type=1&amp;file=59G-1.057.doc">View Rule</a></body></html>'
    )
    pages = {door: html(door_html), document: html("<p>The rule text itself.</p>")}

    result = sources.fetch_source(conn, fetcher_for(conn, site(pages)), door, {})

    assert result.outcome == sources.FETCHED
    assert result.text == "The rule text itself."
    assert result.final_url == document
