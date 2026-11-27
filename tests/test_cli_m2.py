"""The M2 commands, wired through `main`. No model and no network."""

import json
from pathlib import Path

import pytest

from fakes import start_run, store_invented_page
from telecompass import config, rule_store, scope
from telecompass.cli import main
from telecompass.db import Connection


@pytest.fixture
def cli_env(postgres_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the commands at the test database and an empty working folder, with no .env."""
    monkeypatch.setattr(config, "load_env", lambda env_file=None: None)
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_extract_does_not_start_without_langfuse_keys(
    conn: Connection,
    cli_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_invented_page(conn)
    monkeypatch.setenv("OPENAI_API_KEY", "test-value-not-a-real-key")
    for name in (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
        "LANGFUSE_HOST",
    ):
        monkeypatch.delenv(name, raising=False)

    assert main(["extract", "avalon"]) == 2

    assert "LANGFUSE_PUBLIC_KEY is not set" in capsys.readouterr().err
    assert rule_store.latest_run(conn, "avalon") is None  # no run row, so nothing was started
    assert conn.execute("SELECT count(*) AS n FROM model_call").fetchone()["n"] == 0


def test_extract_does_not_start_without_an_openai_key(
    conn: Connection,
    cli_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_invented_page(conn)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert main(["extract", "avalon"]) == 2

    assert "OPENAI_API_KEY is not set" in capsys.readouterr().err
    assert rule_store.latest_run(conn, "avalon") is None


def test_grade_writes_the_results_file_under_evals_results(
    conn: Connection, cli_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, parse_run, entries = store_invented_page(conn)
    run_id = start_run(conn, parse_run)
    rule_store.save_item(conn, run_id, entries[1].id, scope.PRIVATE_PAYER_PARITY, "no_rules")

    assert main(["grade", "avalon"]) == 0

    path = cli_env / "evals" / "results" / "extraction_avalon.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["run"]["id"] == run_id
    assert saved["labels"] == {
        "sample_size": 0,
        "labelled": 0,
        "right": 0,
        "wrong": 0,
        "cannot_tell": 0,
        "labellers": [],
        "items": [],
        "note": "Labels are written only by a person using the labelling page.",
    }
    output = capsys.readouterr().out
    assert "labels: 0 of 0 labelled" in output
    assert "Not legal advice. Sources last fetched 2026-03-15." in output


def test_commands_say_what_to_run_first(
    conn: Connection, cli_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["grade", "avalon"]) == 1
    assert "extract avalon" in capsys.readouterr().out
    assert main(["sources", "avalon"]) == 1
    assert "Nothing parsed for avalon yet" in capsys.readouterr().out
