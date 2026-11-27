"""The monthly refresh, scheduled by Dagster (D22).

Once a month, for each state held: take a new snapshot of its CCHP page and parse it, diff it
against the previous snapshot, check the cited law again for changes, start the change agent
on the diff (it then waits for a person), and rebuild and test the dbt tables. Each step runs
the same command a person would run by hand, so the schedule adds no logic of its own.

Run locally with:  uv run --extra pipeline dagster dev -m telecompass.orchestration
Which database it uses is set by TELECOMPASS_DB_SETTING (default DATABASE_URL).
"""

import os

from dagster import (
    DefaultScheduleStatus,
    Definitions,
    In,
    Nothing,
    OpExecutionContext,
    ScheduleDefinition,
    job,
    op,
)

from telecompass import cli
from telecompass.fetch import CCHP_STATE_URLS

MONTHLY = "0 6 1 * *"  # 06:00 on the 1st of every month
TIMEZONE = "America/New_York"


def _run(context: OpExecutionContext, *arguments: str) -> None:
    setting = os.environ.get("TELECOMPASS_DB_SETTING", "DATABASE_URL")
    context.log.info(f"telecompass {' '.join(arguments)} (database: {setting})")
    code = cli.main(["--db", setting, *arguments])
    if code != 0:
        raise RuntimeError(f"`telecompass {' '.join(arguments)}` exited with {code}")


@op
def snapshot_states(context: OpExecutionContext) -> None:
    """A new snapshot of each state's CCHP page, parsed."""
    for state in sorted(CCHP_STATE_URLS):
        _run(context, "fetch", state, "--force")
        _run(context, "parse", state)


@op(ins={"after": In(Nothing)})
def diff_states(context: OpExecutionContext) -> None:
    """What changed since the previous snapshot of each state."""
    for state in sorted(CCHP_STATE_URLS):
        _run(context, "diff", state)


@op(ins={"after": In(Nothing)})
def recheck_law(context: OpExecutionContext) -> None:
    """Ask again for the law each state's entries cite; keep only documents that changed."""
    for state in sorted(CCHP_STATE_URLS):
        _run(context, "sources", state, "--refresh")


@op(ins={"after": In(Nothing)})
def propose_changes(context: OpExecutionContext) -> None:
    """Start the change agent on each new diff. It stops and waits for a person."""
    for state in sorted(CCHP_STATE_URLS):
        _run(context, "changes", state)


@op(ins={"after": In(Nothing)})
def rebuild_tables(context: OpExecutionContext) -> None:
    """Rebuild the dbt tables and run the data tests."""
    _run(context, "dbt", "build")


@job
def monthly_refresh() -> None:
    rebuild_tables(
        after=propose_changes(after=recheck_law(after=diff_states(after=snapshot_states())))
    )


monthly_schedule = ScheduleDefinition(
    job=monthly_refresh,
    cron_schedule=MONTHLY,
    execution_timezone=TIMEZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

defs = Definitions(jobs=[monthly_refresh], schedules=[monthly_schedule])
