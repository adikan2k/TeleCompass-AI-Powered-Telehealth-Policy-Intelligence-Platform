"""The change queue and official-copy pages, driving the change agent through the browser form."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres import PostgresSaver

from fakes import AT, FakeModel, FakeTracer
from telecompass import change_agent, preflight, sources
from telecompass.approve_app import create_app
from telecompass.db import Connection
from telecompass.llm import ModelGate
from test_change_agent import offline_fetcher, proposals, rpm_answer, world  # noqa: F401

pytestmark = pytest.mark.usefixtures("world")


def started(conn: Connection, postgres_url: str, diff_id: int) -> None:
    """Run the agent's first step, as the `changes` command does, and let it pause."""
    with PostgresSaver.from_conn_string(postgres_url) as saver:
        saver.setup()
        model = FakeModel(rpm_answer)

        def gate(run_id: int) -> ModelGate:
            return ModelGate(conn, model, FakeTracer(), run_id, Decimal("2"))

        graph = change_agent.build_graph(conn, saver, offline_fetcher(conn), gate, now=lambda: AT)
        change_agent.start(graph, diff_id)


def client_for(conn: Connection, postgres_url: str) -> TestClient:
    app = create_app(conn, "Aditya Kanbargi", now=lambda: AT, db_url=postgres_url)
    return TestClient(app, follow_redirects=False)


def test_the_queue_shows_what_changed_and_what_is_proposed(
    conn: Connection,
    postgres_url: str,
    world: dict,  # noqa: F811
) -> None:
    started(conn, postgres_url, world["diff"])
    client = client_for(conn, postgres_url)

    listing = client.get("/changes").text
    assert "Florida: 01 May 2026 (live) to 01 Nov 2026 (live)" in listing
    assert "waiting for review" in listing

    page = client.get(f"/changes/{world['diff']}").text
    assert "Added: Medicaid / Remote Patient Monitoring / POLICY" in page
    assert "Removed: Medicaid / Store and Forward / POLICY" in page
    assert "Proposed new rule" in page and "Proposed retirement of a live rule" in page
    assert "Apply decisions" in page


def test_deciding_and_applying_through_the_page_changes_the_live_rules(
    conn: Connection,
    postgres_url: str,
    world: dict,  # noqa: F811
) -> None:
    started(conn, postgres_url, world["diff"])
    client = client_for(conn, postgres_url)
    made = proposals(conn, world["diff"])
    add = next(p for p in made if p["kind"] == "add")
    retire = next(p for p in made if p["kind"] == "retire")

    answer = client.post(
        f"/changes/{world['diff']}/proposal/{add['id']}", content="decision=approved"
    )
    # Back to the same card, where the decision now shows, not to the top of the page.
    assert answer.headers["location"] == f"/changes/{world['diff']}#proposal-{add['id']}"
    assert f"id='proposal-{add['id']}'" in client.get(f"/changes/{world['diff']}").text
    client.post(f"/changes/{world['diff']}/proposal/{retire['id']}", content="decision=rejected")
    assert {r.id for r in preflight.rules_for(conn, "florida")} == {
        world["video"].id,
        world["saf"].id,
    }  # deciding alone changes nothing; applying does

    response = client.post(f"/changes/{world['diff']}/apply")

    assert response.status_code == 303
    live = {r.id for r in preflight.rules_for(conn, "florida")}
    assert live == {world["video"].id, world["saf"].id, add["rule_id"]}
    assert "have been applied" in client.get(f"/changes/{world['diff']}").text


def test_a_bad_decision_writes_nothing(
    conn: Connection,
    postgres_url: str,
    world: dict,  # noqa: F811
) -> None:
    started(conn, postgres_url, world["diff"])
    client = client_for(conn, postgres_url)
    add = next(p for p in proposals(conn, world["diff"]) if p["kind"] == "add")

    client.post(f"/changes/{world['diff']}/proposal/{add['id']}", content="decision=maybe")
    client.post(f"/changes/{world['diff'] + 1}/proposal/{add['id']}", content="decision=approved")

    assert change_agent.latest_decisions(conn, [add["id"]]) == {}


def test_an_official_copy_is_used_only_after_a_person_confirms_it(
    conn: Connection, postgres_url: str
) -> None:
    client = client_for(conn, postgres_url)
    first = sources.candidate_overrides()[0]
    assert first.cited_url not in sources.load_overrides(conn=conn)
    assert "Confirm the official copy" in client.get("/sources").text

    client.post("/sources/0/confirm", content="")  # box not ticked
    assert first.cited_url not in sources.load_overrides(conn=conn)

    client.post("/sources/0/confirm", content="same=yes")

    confirmed = sources.load_overrides(conn=conn)[first.cited_url]
    assert confirmed.confirmed_by == "Aditya Kanbargi"
    assert confirmed.official_url == first.official_url
    assert "Confirmed by Aditya Kanbargi" in client.get("/sources").text
