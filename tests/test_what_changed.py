"""What changed for you: page changes and where they stand, approved rule changes, and dates."""

from datetime import date

from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres import PostgresSaver

from fakes import AT, FakeModel
from telecompass import api, change_agent, what_changed
from telecompass.db import Connection, connect
from test_change_agent import agent, proposals, rpm_answer, saver, world  # noqa: F401
from test_preflight import seed_rules

TODAY = date(2026, 11, 27)


def florida(conn: Connection, care: str = "behavioral_health", today: date = TODAY) -> dict:
    body = what_changed.what_changed(conn, ["FL"], care, today)
    return next(place for place in body["places"] if place["code"] == "FL")


def reviews(place: dict) -> dict[str, str]:
    return {change["topic"]: change["review"] for change in place["page"]["changes"]}


def test_page_changes_show_the_two_captures_and_are_not_yet_read(
    conn: Connection,
    world: dict,  # noqa: F811
) -> None:
    place = florida(conn)

    assert place["page"]["from"]["captured_at"] == "2026-05-01"
    assert place["page"]["to"]["captured_at"] == "2026-11-01"
    assert reviews(place) == {
        "Store and Forward": "not yet read",
        "Remote Patient Monitoring": "not yet read",
    }
    assert place["rule_changes"] == []


def test_proposed_changes_wait_for_review_and_do_not_go_live(
    conn: Connection,
    saver: PostgresSaver,  # noqa: F811
    world: dict,  # noqa: F811
) -> None:
    change_agent.start(agent(conn, saver, FakeModel(rpm_answer)), world["diff"])

    place = florida(conn)

    assert set(reviews(place).values()) == {"waiting for review"}
    assert place["rule_changes"] == []


def test_approved_changes_show_with_their_quote_and_who_approved_them(
    conn: Connection,
    saver: PostgresSaver,  # noqa: F811
    world: dict,  # noqa: F811
) -> None:
    graph = agent(conn, saver, FakeModel(rpm_answer))
    change_agent.start(graph, world["diff"])
    for proposal in proposals(conn, world["diff"]):
        change_agent.save_decision(conn, proposal["id"], "approved", None, "Aditya Kanbargi", AT)
    assert set(reviews(florida(conn)).values()) == {"decided, not yet applied"}

    change_agent.finish(graph, world["diff"], "Aditya Kanbargi")
    place = florida(conn)

    assert reviews(place) == {
        "Store and Forward": "rule retired",
        "Remote Patient Monitoring": "rule added",
    }
    changes = {item["change"]: item for item in place["rule_changes"]}
    assert changes["added"]["rule"]["quote"].startswith("The programme reimburses remote")
    assert changes["added"]["by"] == "Aditya Kanbargi"
    assert changes["retired"]["on"] == "2026-11-01"
    assert changes["retired"]["rule"]["summary"] == "Store-and-forward is paid."


def test_rejected_changes_say_so(
    conn: Connection,
    saver: PostgresSaver,  # noqa: F811
    world: dict,  # noqa: F811
) -> None:
    graph = agent(conn, saver, FakeModel(rpm_answer))
    change_agent.start(graph, world["diff"])
    for proposal in proposals(conn, world["diff"]):
        change_agent.save_decision(conn, proposal["id"], "rejected", None, "Aditya Kanbargi", AT)
    change_agent.finish(graph, world["diff"], "Aditya Kanbargi")

    place = florida(conn)

    assert set(reviews(place).values()) == {"rejected by the reviewer"}
    assert place["rule_changes"] == []


def test_dates_list_live_rules_that_start_or_end_in_the_window(conn: Connection) -> None:
    seed_rules(conn)

    soon = what_changed.what_changed(conn, ["FL"], "behavioral_health", date(2027, 6, 1))
    later = what_changed.what_changed(conn, ["FL"], "behavioral_health", date(2025, 1, 1))

    federal = next(place for place in soon["places"] if place["code"] == "US")
    assert [(d["event"], d["on"], d["past"]) for d in federal["dates"]] == [
        ("ends", "2027-12-31", False)
    ]
    assert next(p for p in later["places"] if p["code"] == "US")["dates"] == []


def test_a_rule_for_one_line_of_care_is_not_shown_for_another() -> None:
    rule = what_changed.Rule.model_construct(service_category="behavioral_health")
    assert what_changed._applies_to(rule, "behavioral_health")
    assert not what_changed._applies_to(rule, "other")


def test_states_we_do_not_hold_are_named_not_guessed(conn: Connection) -> None:
    body = what_changed.what_changed(conn, ["FL", "TX"], "other", TODAY)
    assert body["not_held"] == ["TX"]
    assert [place["code"] for place in body["places"]] == ["FL", "US"]


def test_the_changes_endpoint_says_not_legal_advice_and_checks_codes(
    conn: Connection, postgres_url: str
) -> None:
    seed_rules(conn)
    app = api.create_app(connect=lambda: connect(postgres_url), now=lambda: AT, migrate=False)
    client = TestClient(app)

    good = client.get("/changes", params={"states": "fl, tx", "care": "behavioral_health"})
    bad = client.get("/changes", params={"states": "FL,Jane Doe"})
    wrong_care = client.get("/changes", params={"care": "anything"})

    assert good.status_code == 200
    assert good.json()["notice"]["not_legal_advice"] == "Not legal advice."
    assert good.json()["not_held"] == ["TX"]
    assert bad.status_code == 422 and "notice" in bad.json()
    assert wrong_care.status_code == 422
