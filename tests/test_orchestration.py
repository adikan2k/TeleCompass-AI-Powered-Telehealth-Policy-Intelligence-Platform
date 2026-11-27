"""The monthly schedule: its timing, and that it runs the steps in order and stops on failure."""

import pytest

dagster = pytest.importorskip("dagster", reason="needs the pipeline extra")

from telecompass import cli, orchestration  # noqa: E402
from telecompass.dbt_runner import command, dbt_environment  # noqa: E402


def test_the_refresh_runs_on_the_first_of_every_month() -> None:
    schedule = orchestration.monthly_schedule
    assert schedule.cron_schedule == "0 6 1 * *"
    assert schedule.execution_timezone == "America/New_York"
    assert schedule.job_name == "monthly_refresh"
    assert orchestration.defs.resolve_job_def("monthly_refresh") is not None


def test_the_steps_run_in_order_against_the_chosen_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda argv: calls.append(argv) or 0)
    monkeypatch.setenv("TELECOMPASS_DB_SETTING", "NEON_DATABASE_URL")

    result = orchestration.monthly_refresh.execute_in_process()

    assert result.success
    assert [call[2:] for call in calls] == [
        ["fetch", "florida", "--force"],
        ["parse", "florida"],
        ["diff", "florida"],
        ["sources", "florida", "--refresh"],
        ["changes", "florida"],
        ["dbt", "build"],
    ]
    assert all(call[:2] == ["--db", "NEON_DATABASE_URL"] for call in calls)


def test_a_failed_step_stops_the_steps_after_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def main(argv: list[str]) -> int:
        calls.append(argv)
        return 1 if argv[2] == "diff" else 0

    monkeypatch.setattr(cli, "main", main)

    result = orchestration.monthly_refresh.execute_in_process(raise_on_error=False)

    assert not result.success
    assert [call[2] for call in calls] == ["fetch", "parse", "diff"]


def test_dbt_gets_its_settings_from_the_address_and_runs_pinned() -> None:
    env = dbt_environment(
        "postgresql://someone:secret@db.example.org:6543/telecompass?sslmode=require"
    )
    assert env == {
        "TC_DB_HOST": "db.example.org",
        "TC_DB_PORT": "6543",
        "TC_DB_USER": "someone",
        "TC_DB_PASSWORD": "secret",
        "TC_DB_NAME": "telecompass",
        "TC_DB_SSLMODE": "require",
    }
    argv = command(["build"])
    assert argv[:7] == [
        "uvx",
        "--python",
        "3.12",
        "--from",
        "dbt-core==1.12.7",
        "--with",
        "dbt-postgres==1.11.0",
    ]
    assert "secret" not in " ".join(argv)
