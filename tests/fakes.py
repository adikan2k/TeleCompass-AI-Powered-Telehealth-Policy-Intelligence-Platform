"""Stand-ins used by the tests. Nothing here touches the network or a real model."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from telecompass import rule_store, store
from telecompass.db import Connection
from telecompass.llm import EXTRACTION_MODEL, ModelReply, Usage
from telecompass.models import FetchedPage, ParseRun, Snapshot, SourceText, StoredEntry
from telecompass.parse_cchp import PARSER_VERSION, parse_state_page

FIXTURE = Path(__file__).parent / "fixtures" / "cchp_state_page.html"
AT = datetime(2026, 3, 15, 9, 30, tzinfo=UTC)

STATUTE_200_1 = "https://example.org/statute/200-1"
STATUTE_200_2 = "https://example.org/statute/200-2"
CODE_59_1 = "https://example.org/code/59-1"
ALERT_7 = "https://example.org/alert/7"

# Invented law text for the invented page's sources.
LAW_200_1 = (
    "200.1 Telehealth coverage.\n"
    "(4) A health plan shall cover a service delivered by telehealth if it covers the same "
    "service delivered in person.\n"
    "(5) A health plan may not require an in-person visit before a telehealth visit."
)
LAW_59_1 = (
    "59-1 Telemedicine.\n"
    "The programme reimburses services delivered by live, two-way video.\n"
    "The programme does not reimburse telephone conversations, chart review, e-mail or fax."
)


class FakeModel:
    """Answers each call with whatever `answer` returns for the prompt, and remembers the calls."""

    def __init__(self, answer: Callable[[str], ModelReply | Exception]) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    def parse(
        self, *, model: str, system: str, user: str, schema: type[BaseModel], max_output_tokens: int
    ) -> ModelReply:
        self.calls.append({"model": model, "system": system, "user": user, "schema": schema})
        reply = self.answer(user)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeTracer:
    """Records what would have been traced."""

    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []
        self.finished: list[dict[str, Any]] = []
        self.flushes = 0

    def start(self, *, name: str, model: str, system: str, user: str, metadata: dict[str, Any]):
        self.started.append({"name": name, "model": model, "metadata": metadata})

        def finish(output: Any, usage: Usage, cost: Decimal, failure: str | None) -> None:
            self.finished.append(
                {"output": output, "usage": usage, "cost": cost, "failure": failure}
            )

        return finish

    def flush(self) -> None:
        self.flushes += 1


def reply(parsed: BaseModel | None, failure: str | None = None, **usage: int) -> ModelReply:
    tokens = Usage(**(usage or {"input_tokens": 1000, "output_tokens": 200}))
    return ModelReply(parsed=parsed, usage=tokens, failure=failure, response_id="resp_test")


def store_invented_page(
    conn: Connection, jurisdiction: str = "avalon"
) -> tuple[Snapshot, ParseRun, list[StoredEntry]]:
    """Store and parse the invented state page. Returns the snapshot, the run and its entries."""
    page = FetchedPage(
        url=f"https://example.org/{jurisdiction}/",
        status=200,
        fetched_at=AT,
        sha256="0" * 64,
        body=FIXTURE.read_text(encoding="utf-8"),
    )
    snapshot = store.save_snapshot(conn, jurisdiction, page)
    run = store.save_parse(conn, snapshot, parse_state_page(page.body), PARSER_VERSION, AT)
    return snapshot, run, store.stored_entries_for(conn, run.id)


def save_source(
    conn: Connection, url: str, text: str | None, outcome: str = "fetched"
) -> SourceText:
    return store.save_source_text(
        conn,
        url=url,
        fetch_url=url,
        final_url=url if outcome == "fetched" else None,
        fetched_at=AT,
        outcome=outcome,
        http_status=200 if outcome == "fetched" else None,
        content_type="text/html" if outcome == "fetched" else None,
        text=text,
    )


def start_run(conn: Connection, parse_run: ParseRun, cap: str = "5.00") -> int:
    return rule_store.start_run(conn, "avalon", parse_run.id, EXTRACTION_MODEL, Decimal(cap), AT)
