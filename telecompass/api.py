"""The public API (D15). It runs the same engine as the command line. No model is called.

A visit is made of fixed choices only. There is no free-text field anywhere, so a request
cannot carry a name or any other patient detail (rule 17).
Every response carries "Not legal advice" and the date the sources were last fetched (rule 18).
"""

import hashlib
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from telecompass import config, db, preflight, scope
from telecompass.db import Connection
from telecompass.engine import Modality, Prescription, Visit
from telecompass.fetch import utc_now

VISITOR_DAILY_LIMIT = 200
SITE_DAILY_LIMIT = 5000
DISCLAIMER = "Not legal advice."

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}  # fmt: skip

Profession = Literal[
    "psychiatrist",
    "physician",
    "psychologist",
    "nurse practitioner",
    "counselor",
    "physical therapist",
    "pharmacist",
]
PrescriptionChoice = Literal["none", "not_controlled", "II", "III", "IV", "V"]


class PublicVisit(BaseModel):
    """A visit as the public may describe it: fixed choices only, nothing typed freely."""

    model_config = ConfigDict(extra="forbid")

    profession: Profession
    licensed_in: list[str] = Field(max_length=len(STATES))
    registered_in_patient_state: bool = False
    patient_state: str
    modality: Modality
    payer: Literal["medicaid", "medicare", "private", "self_pay"]
    service_category: Literal["behavioral_health", "other"]
    prescription: PrescriptionChoice = "none"
    visit_date: date

    @field_validator("patient_state")
    @classmethod
    def known_state(cls, value: str) -> str:
        if value not in STATES:
            raise ValueError("not a US state code")
        return value

    @field_validator("licensed_in")
    @classmethod
    def known_states(cls, value: list[str]) -> list[str]:
        if any(code not in STATES for code in value):
            raise ValueError("not a US state code")
        return sorted(set(value))

    @field_validator("visit_date")
    @classmethod
    def sensible_date(cls, value: date) -> date:
        if not date(2015, 1, 1) <= value <= date(2035, 12, 31):
            raise ValueError("the date must be between 2015 and 2035")
        return value

    def to_visit(self) -> Visit:
        drug = None
        if self.prescription == "not_controlled":
            drug = Prescription(drug="a medicine that is not a controlled substance")
        elif self.prescription != "none":
            drug = Prescription(
                drug=f"a Schedule {self.prescription} controlled substance",
                schedule=self.prescription,
            )
        return Visit(
            profession=self.profession,
            licensed_in=self.licensed_in,
            registered_in=[self.patient_state] if self.registered_in_patient_state else [],
            patient_state=self.patient_state,
            modality=self.modality,
            payer=self.payer,
            service_category=self.service_category,
            prescription=drug,
            visit_date=self.visit_date,
        )


def count_request(conn: Connection, key: str, day: date) -> int:
    """Add one to a day's counter and return the new count."""
    row = conn.execute(
        "INSERT INTO rate_counter (day, key, count) VALUES (%s, %s, 1) "
        "ON CONFLICT (day, key) DO UPDATE SET count = rate_counter.count + 1 RETURNING count",
        (day, key),
    ).fetchone()
    conn.commit()
    return row["count"]


def visitor_key(request: Request, day: date) -> str:
    """A one-way hash of the visitor's address and the day. The address is not kept."""
    forwarded = request.headers.get("x-forwarded-for", "")
    address = forwarded.split(",")[0].strip() or (request.client.host if request.client else "")
    return "visitor:" + hashlib.sha256(f"{address}|{day}".encode()).hexdigest()[:24]


def sources_last_fetched(conn: Connection) -> str:
    row = conn.execute(
        "SELECT max(fetched_at) AS at FROM source_text WHERE outcome = 'fetched'"
    ).fetchone()
    return f"{row['at']:%Y-%m-%d}" if row and row["at"] else "never"


def create_app(
    connect: Callable[[], Connection] | None = None,
    now: Callable[[], datetime] = utc_now,
    migrate: bool = True,
) -> FastAPI:
    app = FastAPI(title="TeleCompass API", docs_url=None, redoc_url=None)

    def open_database() -> Connection:
        if connect is not None:
            return connect()
        config.load_env()
        return db.connect(config.database_url())

    if migrate:
        with open_database() as conn:
            db.migrate(conn)

    def reply(conn: Connection, body: dict[str, Any], status: int = 200) -> JSONResponse:
        notice = {
            "not_legal_advice": DISCLAIMER,
            "sources_last_fetched": sources_last_fetched(conn),
        }
        return JSONResponse({**body, "notice": notice}, status_code=status)

    @app.get("/health")
    def health() -> JSONResponse:
        with open_database() as conn:
            return reply(conn, {"ok": True})

    @app.get("/options")
    def options() -> JSONResponse:
        """What the form may offer. Only states we hold rules for can be the patient's state."""
        held = sorted(scope.STATE_JURISDICTIONS)
        with open_database() as conn:
            body = {
                "patient_states": [{"code": code, "name": STATES[code]} for code in held],
                "states": [{"code": code, "name": name} for code, name in STATES.items()],
                "professions": list(Profession.__args__),
                "modalities": list(Modality.__args__),
                "payers": ["medicaid", "medicare", "private", "self_pay"],
                "service_categories": ["behavioral_health", "other"],
                "prescriptions": list(PrescriptionChoice.__args__),
            }
            return reply(conn, body)

    @app.post("/preflight")
    def run(visit: PublicVisit, request: Request, store: bool = True) -> JSONResponse:
        """Decide a visit. With `store=false` the answer is shown but not kept and has no link:
        the site uses that for the worked example it shows when the page opens."""
        today = now().date()
        with open_database() as conn:
            if count_request(conn, "site", today) > SITE_DAILY_LIMIT:
                return reply(conn, {"error": "The site has reached today's limit."}, 429)
            if count_request(conn, visitor_key(request, today), today) > VISITOR_DAILY_LIMIT:
                return reply(conn, {"error": "You have reached today's limit."}, 429)
            if store:
                decision, _, public_id = preflight.run_preflight(conn, visit.to_visit(), now())
            else:
                decision, public_id = preflight.decide_visit(conn, visit.to_visit()), None
            body = {
                "id": public_id,
                "visit": decision.visit.model_dump(mode="json"),
                "summary": preflight.describe(decision.visit),
                "lines": [line.model_dump(mode="json") for line in decision.lines],
            }
            return reply(conn, body)

    @app.get("/decisions/{public_id}")
    def stored(public_id: str) -> JSONResponse:
        """A stored decision exactly as it was given, with the rules it rested on."""
        with open_database() as conn:
            row = conn.execute(
                "SELECT visit, answer, created_at FROM decision WHERE public_id = %s", (public_id,)
            ).fetchone()
            if row is None:
                return reply(conn, {"error": "No decision has that id."}, 404)
            visit = Visit.model_validate(row["visit"])
            body = {
                "id": public_id,
                "created_at": row["created_at"].isoformat(),
                "visit": row["visit"],
                "summary": preflight.describe(visit),
                "lines": row["answer"],
            }
            return reply(conn, body)

    return app


def production_app() -> FastAPI:
    """The app Cloud Run serves: `uvicorn telecompass.api:production_app --factory`."""
    return create_app()
