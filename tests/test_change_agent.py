"""The change agent, end to end on invented pages, with a fake model and no network."""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from langgraph.checkpoint.postgres import PostgresSaver

from fakes import AT, FakeModel, FakeTracer, reply, save_source
from telecompass import change_agent, diff, preflight, rule_store, scope, store
from telecompass.db import Connection
from telecompass.extract import ExtractedRule, Extraction
from telecompass.fetch import USER_AGENT, Fetcher
from telecompass.llm import EXTRACTION_MODEL, ModelGate
from telecompass.models import Entry, FetchedPage, ParsedPage, SourceLink

VIDEO_URL = "https://example.org/code/video"
SAF_URL = "https://example.org/code/store-and-forward"
RPM_URL = "https://example.org/alert/monitoring"
RPM_QUOTE = "The programme reimburses remote patient monitoring for high-risk pregnancies."
RPM_LAW = "Remote monitoring.\n" + RPM_QUOTE
SAF_QUOTE = "The programme reimburses store-and-forward images reviewed later."


def entry(topic: str, text: str, url: str) -> Entry:
    return Entry(
        category="Medicaid",
        topic=topic,
        subtopic="POLICY",
        text=text,
        source_name="Invented source",
        source_url=url,
        source_links=[SourceLink(label="Invented source", url=url)],
    )


def stored_page(conn: Connection, entries: list[Entry], captured: datetime) -> int:
    page = FetchedPage(
        url="https://example.org/avalon/",
        status=200,
        fetched_at=captured,
        sha256="0" * 64,
        body="x",
    )
    snapshot = store.save_snapshot(conn, "florida", page, captured_at=captured)
    parsed = ParsedPage(answers=[], entries=entries, problems=[])
    return store.save_parse(conn, snapshot, parsed, "test", captured).id


@pytest.fixture
def world(conn: Connection) -> dict:
    """An old page with video and store-and-forward; a new one where store-and-forward is gone
    and remote monitoring is new. The live rules come from the old page."""
    old_run = stored_page(
        conn,
        [
            entry("Live Video", "Video is paid.", VIDEO_URL),
            entry("Store and Forward", "SAF is paid.", SAF_URL),
        ],
        datetime(2026, 5, 1, tzinfo=UTC),
    )
    new_run = stored_page(
        conn,
        [
            entry("Live Video", "Video is paid.", VIDEO_URL),
            entry("Remote Patient Monitoring", "RPM is new.", RPM_URL),
        ],
        datetime(2026, 11, 1, tzinfo=UTC),
    )
    save_source(conn, RPM_URL, RPM_LAW)
    old_entries = store.stored_entries_for(conn, old_run)
    base = rule_store.start_run(conn, "florida", old_run, EXTRACTION_MODEL, Decimal("5"), AT)
    common = {
        "run_id": base,
        "jurisdiction": "florida",
        "rule_type": scope.MEDICAID_MODALITY,
        "aspect": "coverage",
        "effect": "allow",
        "status": "draft",
        "quote_verified": True,
        "payer": "medicaid",
        "created_at": AT,
    }
    video = rule_store.save_rule(
        conn, entry_id=old_entries[0].id, summary="Video is paid.", modality="live_video",
        quote="The programme reimburses live, two-way video.", **common,
    )  # fmt: skip
    saf = rule_store.save_rule(
        conn, entry_id=old_entries[1].id, summary="Store-and-forward is paid.",
        modality="store_and_forward", quote=SAF_QUOTE, **common,
    )  # fmt: skip
    diff_id, _ = diff.save_diff(conn, "florida", old_run, new_run, AT)
    return {"diff": diff_id, "video": video, "saf": saf}


def rpm_answer(user: str):
    rule = ExtractedRule(
        summary="Medicaid pays for remote monitoring of high-risk pregnancies.",
        aspect="coverage",
        effect="allow",
        profession=None,
        payer="medicaid",
        modality="remote_patient_monitoring",
        service="high-risk pregnancy",
        service_category="any",
        compact=None,
        conditions=[],
        quote=RPM_QUOTE,
        source_number=1,
        effective_from=None,
        effective_to=None,
    )
    return reply(Extraction(rules=[rule], law_is_silent=False, note=None))


@pytest.fixture
def saver(postgres_url: str, world: dict) -> Iterator[PostgresSaver]:
    with PostgresSaver.from_conn_string(postgres_url) as checkpointer:
        checkpointer.setup()
        yield checkpointer


def offline_fetcher(conn: Connection) -> Fetcher:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"No network in tests: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(refuse), headers={"User-Agent": USER_AGENT})
    return Fetcher(conn, client, sleep=lambda s: None)


def agent(conn: Connection, saver: PostgresSaver, model: FakeModel):
    def gate(run_id: int) -> ModelGate:
        return ModelGate(conn, model, FakeTracer(), run_id, Decimal("2"))

    return change_agent.build_graph(conn, saver, offline_fetcher(conn), gate, now=lambda: AT)


def proposals(conn: Connection, diff_id: int) -> list[dict]:
    return conn.execute(
        "SELECT * FROM change_proposal WHERE diff_run_id = %s ORDER BY id", (diff_id,)
    ).fetchall()


def test_the_agent_proposes_a_new_rule_and_a_retirement_then_pauses(
    conn: Connection, saver: PostgresSaver, world: dict
) -> None:
    model = FakeModel(rpm_answer)
    graph = agent(conn, saver, model)

    ids = change_agent.start(graph, world["diff"])

    made = proposals(conn, world["diff"])
    assert [p["id"] for p in made] == ids
    assert sorted(p["kind"] for p in made) == ["add", "retire"]
    retire = next(p for p in made if p["kind"] == "retire")
    assert retire["matched_rule_id"] == world["saf"].id
    assert "removed" in retire["note"]
    assert change_agent.status(graph, world["diff"]) == "waiting for review"
    assert len(model.calls) == 1  # one model call: the new entry; the removed one needs none


def test_nothing_changes_on_the_site_until_a_person_decides(
    conn: Connection, saver: PostgresSaver, world: dict
) -> None:
    change_agent.start(agent(conn, saver, FakeModel(rpm_answer)), world["diff"])

    live = {rule.id for rule in preflight.rules_for(conn, "florida")}
    assert live == {world["video"].id, world["saf"].id}


def test_approved_decisions_flow_through_and_rejected_ones_do_not(
    conn: Connection, saver: PostgresSaver, world: dict
) -> None:
    graph = agent(conn, saver, FakeModel(rpm_answer))
    change_agent.start(graph, world["diff"])
    made = proposals(conn, world["diff"])
    add = next(p for p in made if p["kind"] == "add")
    retire = next(p for p in made if p["kind"] == "retire")
    change_agent.save_decision(conn, add["id"], "approved", None, "Aditya Kanbargi", AT)
    change_agent.save_decision(
        conn, retire["id"], "approved", "Gone from CCHP", "Aditya Kanbargi", AT
    )

    applied = change_agent.finish(graph, world["diff"], "Aditya Kanbargi")

    assert applied == {"approved": 1, "rejected": 0, "retired": 1}
    assert change_agent.status(graph, world["diff"]) == "done"
    live = {rule.id: rule for rule in preflight.rules_for(conn, "florida")}
    assert world["saf"].id not in live  # retired
    assert add["rule_id"] in live and live[add["rule_id"]].status == "approved"
    retired_on = conn.execute("SELECT retired_on FROM rule_retirement").fetchone()["retired_on"]
    assert str(retired_on) == "2026-11-01"  # the date of the snapshot that showed the change


def test_a_rejected_proposal_changes_nothing(
    conn: Connection, saver: PostgresSaver, world: dict
) -> None:
    graph = agent(conn, saver, FakeModel(rpm_answer))
    change_agent.start(graph, world["diff"])
    for proposal in proposals(conn, world["diff"]):
        change_agent.save_decision(conn, proposal["id"], "rejected", None, "Aditya Kanbargi", AT)

    change_agent.finish(graph, world["diff"], "Aditya Kanbargi")

    live = {rule.id for rule in preflight.rules_for(conn, "florida")}
    assert live == {world["video"].id, world["saf"].id}


def test_a_rule_read_again_that_is_already_live_is_marked_so(
    conn: Connection, saver: PostgresSaver, world: dict
) -> None:
    # The live video rule is read again from the new page (as after a reworded entry).
    old_video = world["video"].entry_id
    new_video = conn.execute(
        "SELECT e.id FROM entry e JOIN diff_run d ON d.new_parse_run_id = e.parse_run_id "
        "WHERE d.id = %s AND e.topic = 'Live Video'",
        (world["diff"],),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO entry_change (diff_run_id, kind, category, topic, subtopic, rule_type, "
        "old_entry_id, new_entry_id) VALUES (%s, 'changed', 'Medicaid', 'Live Video', 'POLICY', "
        "%s, %s, %s)",
        (world["diff"], scope.MEDICAID_MODALITY, old_video, new_video),
    )
    conn.commit()
    save_source(conn, VIDEO_URL, "Video.\nThe programme reimburses live, two-way video.")

    def answer(user: str):
        if "RPM is new." in user:
            return rpm_answer(user)
        same = (
            rpm_answer(user)
            .parsed.rules[0]
            .model_copy(
                update={
                    "quote": "The programme reimburses live, two-way video.",
                    "modality": "live_video",
                }
            )
        )
        return reply(Extraction(rules=[same], law_is_silent=False, note=None))

    change_agent.start(agent(conn, saver, FakeModel(answer)), world["diff"])

    kinds = [p["kind"] for p in proposals(conn, world["diff"])]
    assert "already_live" in kinds
    assert kinds.count("retire") == 1  # the video rule is kept; only store-and-forward goes


def test_a_cited_law_that_cannot_be_fetched_is_reported_not_guessed(
    conn: Connection, saver: PostgresSaver, world: dict
) -> None:
    conn.execute("DELETE FROM source_text WHERE url = %s", (RPM_URL,))
    save_source(conn, RPM_URL, None, outcome="forbidden")
    model = FakeModel(rpm_answer)

    change_agent.start(agent(conn, saver, model), world["diff"])

    unreadable = [p for p in proposals(conn, world["diff"]) if p["kind"] == "unreadable"]
    assert len(unreadable) == 1 and "forbidden" in unreadable[0]["note"]
    assert model.calls == []


def test_a_diff_is_reviewed_once(conn: Connection, saver: PostgresSaver, world: dict) -> None:
    graph = agent(conn, saver, FakeModel(rpm_answer))
    change_agent.start(graph, world["diff"])
    with pytest.raises(RuntimeError, match="already has a change review"):
        change_agent.start(graph, world["diff"])
    change_agent.finish(graph, world["diff"], "Aditya Kanbargi")
    with pytest.raises(RuntimeError, match="not waiting"):
        change_agent.finish(graph, world["diff"], "Aditya Kanbargi")
