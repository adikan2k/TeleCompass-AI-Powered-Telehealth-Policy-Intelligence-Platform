"""The rule review page, and what approval changes on the live site. No model, no network."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from fakes import AT, CODE_59_1, LAW_59_1, save_source, store_invented_page
from telecompass import grade, preflight, rule_store, scope
from telecompass.approve_app import create_app, quote_in_place, rules_to_review
from telecompass.db import Connection
from telecompass.engine import Verdict
from telecompass.llm import EXTRACTION_MODEL
from telecompass.models import Rule

QUOTE = "The programme does not reimburse telephone conversations, chart review, e-mail or fax."


def seed(conn: Connection) -> tuple[int, list[Rule]]:
    """A Florida run with two quoted rules about phone calls and video, and one silent rule."""
    _, parse_run, entries = store_invented_page(conn, "florida")
    source = save_source(conn, CODE_59_1, LAW_59_1)
    run_id = rule_store.start_run(conn, "florida", parse_run.id, EXTRACTION_MODEL, Decimal("5"), AT)
    common = {
        "run_id": run_id,
        "entry_id": entries[0].id,
        "jurisdiction": "florida",
        "rule_type": scope.MEDICAID_MODALITY,
        "aspect": "coverage",
        "status": "draft",
        "quote_verified": True,
        "payer": "medicaid",
        "source_text_id": source.id,
        "source_url": CODE_59_1,
        "created_at": AT,
    }
    phone = rule_store.save_rule(
        conn, effect="deny", summary="Medicaid does not pay for phone calls.", quote=QUOTE,
        modality="audio_only", **common,
    )  # fmt: skip
    video = rule_store.save_rule(
        conn, effect="allow", summary="Medicaid pays for live video.",
        quote="The programme reimburses services delivered by live, two-way video.",
        modality="live_video", **common,
    )  # fmt: skip
    rule_store.save_rule(
        conn, effect="silent", summary="The state is silent on this point.", quote=None,
        **(common | {"quote_verified": False}),
    )  # fmt: skip
    return run_id, [phone, video]


def client_for(conn: Connection) -> TestClient:
    return TestClient(create_app(conn, "Aditya Kanbargi", now=lambda: AT), follow_redirects=False)


def test_only_distinct_quoted_rules_are_offered_for_review(conn: Connection) -> None:
    _, rules = seed(conn)
    assert [rule.id for rule, _ in rules_to_review(conn)] == [rule.id for rule in rules]


def test_the_quoted_words_are_found_in_their_place_in_the_source() -> None:
    source = (
        "59-1 Telemedicine.\nThe programme does not reimburse telephone\n"
        "conversations, chart review, e-mail or fax."
    )
    html = quote_in_place(source, "The programme does not reimburse telephone conversations")
    assert (
        "<strong class='hit'>The programme does not reimburse telephone\nconversations</strong>"
        in html
    )
    assert "59-1 Telemedicine." in html


def test_page_shows_the_rule_the_law_and_the_second_models_view(conn: Connection) -> None:
    seed(conn)
    page = client_for(conn).get("/rule/0").text

    assert "Medicaid does not pay for phone calls." in page
    assert QUOTE in page
    assert "The second model has not checked this rule." in page
    assert "0 of 2 reviewed" in page
    assert "Not legal advice." in page


def test_a_review_is_written_only_by_submitting_the_form(conn: Connection) -> None:
    _, (phone, video) = seed(conn)
    client = client_for(conn)
    client.get("/")
    client.get("/rule/0")
    client.get("/done")
    assert rule_store.latest_rule_reviews(conn, [phone.id, video.id]) == {}

    response = client.post("/rule/0", content="decision=approved")
    assert response.headers["location"] == "/rule/1"
    client.post("/rule/1", content="decision=rejected&note=Overstates+the+source")

    reviews = rule_store.latest_rule_reviews(conn, [phone.id, video.id])
    assert reviews[phone.id]["decision"] == "approved"
    assert (reviews[video.id]["decision"], reviews[video.id]["note"]) == (
        "rejected",
        "Overstates the source",
    )
    assert reviews[phone.id]["reviewer"] == "Aditya Kanbargi"
    assert client.get("/").headers["location"] == "/done"
    assert "1 approved, 1 rejected, 0 not reviewed." in client.get("/done").text


def test_a_bad_choice_writes_nothing_and_a_rule_is_never_changed(conn: Connection) -> None:
    _, (phone, _) = seed(conn)
    client = client_for(conn)
    client.post("/rule/0", content="decision=maybe")
    client.post("/rule/9", content="decision=approved")
    assert conn.execute("SELECT count(*) AS n FROM rule_review").fetchone()["n"] == 0

    client.post("/rule/0", content="decision=approved")
    assert rule_store.rule_by_id(conn, phone.id).status == "draft"  # the rule row is untouched


def test_changing_your_mind_adds_a_review_and_the_newest_counts(conn: Connection) -> None:
    _, (phone, _) = seed(conn)
    client = client_for(conn)
    client.post("/rule/0", content="decision=rejected")
    client.post("/rule/0", content="decision=approved")

    assert rule_store.latest_rule_reviews(conn, [phone.id])[phone.id]["decision"] == "approved"
    assert conn.execute("SELECT count(*) AS n FROM rule_review").fetchone()["n"] == 2
    assert "You approved this rule earlier." in client.get("/rule/0").text


def medicaid_line(conn: Connection):
    visit = preflight.demo_visit(date(2026, 12, 1))
    decision = preflight.decide_visit(conn, visit)
    return next(line for line in decision.lines if line.key == scope.MEDICAID_MODALITY)


def test_a_rejected_rule_is_never_used(conn: Connection) -> None:
    _, (phone, _) = seed(conn)
    assert medicaid_line(conn).verdict == Verdict.NOT_ALLOWED

    rule_store.save_rule_review(conn, phone.id, "rejected", None, "Aditya Kanbargi", AT)

    assert medicaid_line(conn).verdict == Verdict.SILENT


def test_where_approval_is_required_only_approved_rules_are_used(
    conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, (phone, _) = seed(conn)
    monkeypatch.setenv("TELECOMPASS_REQUIRE_APPROVAL", "1")
    assert medicaid_line(conn).verdict == Verdict.SILENT  # nothing approved yet

    rule_store.save_rule_review(conn, phone.id, "approved", None, "Aditya Kanbargi", AT)

    line = medicaid_line(conn)
    assert line.verdict == Verdict.NOT_ALLOWED
    assert line.evidence[0].status == "approved"


def test_approvals_reach_the_results_file(conn: Connection) -> None:
    run_id, (phone, video) = seed(conn)
    rule_store.save_rule_review(conn, phone.id, "approved", None, "Aditya Kanbargi", AT)

    approval = grade.build_results(conn, "florida", AT)["human_approval"]

    assert (approval["distinct_rules"], approval["approved"], approval["rejected"]) == (2, 1, 0)
    assert approval["not_reviewed"] == 1 and approval["reviewers"] == ["Aditya Kanbargi"]
