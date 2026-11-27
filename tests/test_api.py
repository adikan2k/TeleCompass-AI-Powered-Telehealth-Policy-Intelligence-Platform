"""The public API, against the test database. No model and no network."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from fakes import AT
from telecompass import api, scope
from telecompass.db import Connection, connect
from test_preflight import seed_rules

VISIT = {
    "profession": "psychiatrist",
    "licensed_in": ["NY"],
    "patient_state": "FL",
    "modality": "audio_only",
    "payer": "medicaid",
    "service_category": "behavioral_health",
    "prescription": "II",
    "visit_date": "2026-12-01",
}


@pytest.fixture
def client(conn: Connection, postgres_url: str) -> TestClient:
    seed_rules(conn)
    app = api.create_app(connect=lambda: connect(postgres_url), now=lambda: AT, migrate=False)
    return TestClient(app)


def test_every_response_says_not_legal_advice_with_the_fetch_date(client: TestClient) -> None:
    responses = [
        client.get("/health"),
        client.get("/options"),
        client.post("/preflight", json=VISIT),
        client.get("/decisions/nope"),
    ]
    for response in responses:
        assert response.json()["notice"]["not_legal_advice"] == "Not legal advice."
        assert "sources_last_fetched" in response.json()["notice"]


def test_options_offer_only_patient_states_we_hold_rules_for(client: TestClient) -> None:
    options = client.get("/options").json()
    assert options["patient_states"] == [{"code": "FL", "name": "Florida"}]
    assert len(options["states"]) == 51
    assert "psychiatrist" in options["professions"]
    assert set(scope.STATE_JURISDICTIONS) == {"FL"}


def test_preflight_answers_and_the_share_link_returns_the_same_answer(client: TestClient) -> None:
    answer = client.post("/preflight", json=VISIT).json()

    medicaid = next(line for line in answer["lines"] if line["key"] == scope.MEDICAID_MODALITY)
    assert medicaid["verdict"] == "not_allowed"
    assert medicaid["evidence"][0]["quote"] == (
        "The programme does not reimburse telephone conversations."
    )
    assert "psychiatrist licensed in NY" in answer["summary"]
    assert len(answer["id"]) >= 10

    shared = client.get(f"/decisions/{answer['id']}").json()
    assert shared["lines"] == answer["lines"]
    assert shared["visit"] == answer["visit"]
    assert shared["created_at"].startswith("2026-03-15")


def test_two_decisions_get_different_ids_that_cannot_be_counted_up(client: TestClient) -> None:
    first = client.post("/preflight", json=VISIT).json()["id"]
    second = client.post("/preflight", json=VISIT).json()["id"]
    assert first != second
    assert not first.isdigit() and not second.isdigit()


def test_changing_the_date_changes_the_dated_medicare_line(client: TestClient) -> None:
    def audio_line(on: str) -> dict:
        lines = client.post("/preflight", json=VISIT | {"visit_date": on}).json()["lines"]
        return next(line for line in lines if line["key"] == "medicare_coverage")

    assert audio_line("2026-12-01")["verdict"] == "allowed"
    assert audio_line("2028-03-01")["verdict"] == "silent"


def test_a_request_cannot_carry_free_text(client: TestClient) -> None:
    for extra in ({"service": "Jane Doe, born 1980"}, {"note": "anything"}):
        assert client.post("/preflight", json=VISIT | extra).status_code == 422
    assert client.post("/preflight", json=VISIT | {"profession": "Dr Jane Doe"}).status_code == 422
    assert client.post("/preflight", json=VISIT | {"licensed_in": ["Jane"]}).status_code == 422
    assert client.post("/preflight", json=VISIT | {"patient_state": "Narnia"}).status_code == 422
    assert client.post("/preflight", json=VISIT | {"visit_date": "1900-01-01"}).status_code == 422


def test_stored_visit_holds_only_the_fixed_choices(client: TestClient, conn: Connection) -> None:
    client.post("/preflight", json=VISIT)
    stored = conn.execute("SELECT visit FROM decision").fetchone()["visit"]
    assert stored["service"] is None
    assert stored["prescription"]["drug"] == "a Schedule II controlled substance"
    assert stored["licensed_in"] == ["NY"]


def test_registration_choice_reaches_the_engine() -> None:
    visit = api.PublicVisit.model_validate(VISIT | {"registered_in_patient_state": True}).to_visit()
    assert visit.registered_in == ["FL"]
    plain = api.PublicVisit.model_validate(VISIT | {"prescription": "none"}).to_visit()
    assert plain.prescription is None and plain.visit_date == date(2026, 12, 1)


def test_visitor_is_stopped_at_the_daily_limit(
    client: TestClient, conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "VISITOR_DAILY_LIMIT", 2)

    codes = [client.post("/preflight", json=VISIT).status_code for _ in range(3)]

    assert codes == [200, 200, 429]
    assert conn.execute("SELECT count(*) AS n FROM decision").fetchone()["n"] == 2
    other = client.post("/preflight", json=VISIT, headers={"x-forwarded-for": "203.0.113.9"})
    assert other.status_code == 200  # another visitor is not affected


def test_site_is_stopped_at_its_daily_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "SITE_DAILY_LIMIT", 1)
    assert client.post("/preflight", json=VISIT).status_code == 200
    blocked = client.post("/preflight", json=VISIT, headers={"x-forwarded-for": "203.0.113.9"})
    assert blocked.status_code == 429 and "limit" in blocked.json()["error"]


def test_counters_hold_a_hash_and_never_an_address(client: TestClient, conn: Connection) -> None:
    client.post("/preflight", json=VISIT, headers={"x-forwarded-for": "203.0.113.9"})
    keys = [row["key"] for row in conn.execute("SELECT key FROM rate_counter").fetchall()]
    assert sorted(key.split(":")[0] for key in keys) == ["site", "visitor"]
    assert all("203.0.113.9" not in key for key in keys)


def test_an_unstored_preview_answers_but_keeps_nothing(
    client: TestClient, conn: Connection
) -> None:
    preview = client.post("/preflight?store=false", json=VISIT).json()

    assert preview["id"] is None
    assert any(line["key"] == scope.MEDICAID_MODALITY for line in preview["lines"])
    assert conn.execute("SELECT count(*) AS n FROM decision").fetchone()["n"] == 0
    stored = client.post("/preflight", json=VISIT).json()
    assert stored["lines"] == preview["lines"] and stored["id"] is not None
