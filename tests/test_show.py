"""Store round trip and the show command, on the invented page."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from telecompass import store
from telecompass.cli import main
from telecompass.db import Connection
from telecompass.models import FetchedPage, Snapshot
from telecompass.parse_cchp import PARSER_VERSION, parse_state_page
from telecompass.show import EXCERPT_CHARS, excerpt, render

FIXTURE = Path(__file__).parent / "fixtures" / "cchp_state_page.html"
FETCHED_AT = datetime(2026, 3, 15, 9, 30, tzinfo=UTC)


def stored_snapshot(conn: Connection, jurisdiction: str = "avalon") -> Snapshot:
    html = FIXTURE.read_text(encoding="utf-8")
    page = FetchedPage(
        url="https://example.org/avalon/",
        status=200,
        fetched_at=FETCHED_AT,
        sha256="0" * 64,
        body=html,
    )
    return store.save_snapshot(conn, jurisdiction, page)


def test_parsed_page_survives_a_round_trip_through_the_database(conn: Connection) -> None:
    snapshot = stored_snapshot(conn)
    parsed = parse_state_page(snapshot.raw_page)

    run = store.save_parse(conn, snapshot, parsed, PARSER_VERSION, FETCHED_AT)

    assert store.entries_for(conn, run.id) == parsed.entries
    assert store.answers_for(conn, run.id) == parsed.answers
    assert run.problems == parsed.problems
    assert (run.entry_count, run.answer_count) == (len(parsed.entries), len(parsed.answers))


def test_parsing_again_adds_a_new_run_and_keeps_the_old_rows(conn: Connection) -> None:
    snapshot = stored_snapshot(conn)
    parsed = parse_state_page(snapshot.raw_page)

    first = store.save_parse(conn, snapshot, parsed, PARSER_VERSION, FETCHED_AT)
    second = store.save_parse(conn, snapshot, parsed, PARSER_VERSION, FETCHED_AT)

    latest = store.latest_parse_run(conn, snapshot.id)
    assert latest is not None and latest.id == second.id
    assert store.entries_for(conn, first.id) == parsed.entries  # nothing was overwritten
    count = conn.execute("SELECT count(*) AS n FROM entry").fetchone()
    assert count is not None and count["n"] == 2 * len(parsed.entries)


def test_excerpt_cuts_long_text_and_marks_the_cut() -> None:
    assert excerpt("short text") == "short text"
    long_text = "word " * 100
    cut = excerpt(long_text)
    assert cut.endswith("...")
    assert len(cut) <= EXCERPT_CHARS + 3


def test_render_shows_answers_sources_and_never_more_than_an_excerpt(conn: Connection) -> None:
    snapshot = stored_snapshot(conn)
    parsed = parse_state_page(snapshot.raw_page)
    parsed.entries[0].text = "x" * 1000
    run = store.save_parse(conn, snapshot, parsed, PARSER_VERSION, FETCHED_AT)

    output = render(snapshot, run, parsed.answers, parsed.entries)

    assert "AT A GLANCE, the answer key (5 answers)" in output
    assert "    Live Video: Yes" in output
    assert '7: 4 with a SOURCE line, 2 marked "No Reference Found", 1 with no SOURCE line' in output
    assert "[2] Private Payer > Parity > SERVICE PARITY  (last updated 2026-03-09)" in output
    assert "    SOURCE: ZZ Statute 200.1 (4). & 200.2 (accessed Mar. 2026)" in output
    assert "      https://example.org/statute/200-2" in output
    assert "SOURCE: none. CCHP marks this No Reference Found." in output
    assert "SOURCE: none given for this passage." in output
    assert "x" * EXCERPT_CHARS + "..." in output
    assert "x" * (EXCERPT_CHARS + 1) not in output
    assert "Parser notes (4):" in output
    assert "Full text and copyright: https://example.org/avalon/" in output
    assert output.endswith("Not legal advice. Sources last fetched 2026-03-15.")


def test_show_command_prints_the_stored_page(
    conn: Connection,
    postgres_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    stored_snapshot(conn, "avalon")

    assert main(["show", "avalon"]) == 1
    assert "not parsed yet" in capsys.readouterr().out

    assert main(["parse", "avalon"]) == 0
    assert "7 entries, 5 answers, 4 notes" in capsys.readouterr().out

    assert main(["show", "Avalon"]) == 0
    output = capsys.readouterr().out
    assert "Avalon: CCHP page https://example.org/avalon/" in output
    assert "    Audio Only: No" in output
    assert "Not legal advice. Sources last fetched 2026-03-15." in output


def test_show_command_says_so_when_nothing_is_stored(
    conn: Connection,
    postgres_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", postgres_url)

    assert main(["show", "florida"]) == 1
    assert "No snapshot of florida yet" in capsys.readouterr().out
