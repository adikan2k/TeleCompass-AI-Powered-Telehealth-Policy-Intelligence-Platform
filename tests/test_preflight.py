"""Pointers, the stored decision and the preflight command. No model and no network."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fakes import AT, store_invented_page
from telecompass import config, pointers, preflight, rule_store, scope, store
from telecompass.cli import main
from telecompass.db import Connection
from telecompass.engine import Verdict, Visit
from telecompass.llm import EXTRACTION_MODEL

POINTERS = """
[[pointer]]
category = "Medicare"
topic = "Telehealth flexibilities"
subtopic = "Where the patient can be"
text = '''
Where a patient may be
located for telehealth.
'''
sources = [{ label = "Agency FAQ", url = "https://example.org/faq.pdf" }]

[[pointer]]
category = "Medicare"
topic = "Telehealth flexibilities"
text = "A pointer that forgot its source."
"""


def test_pointers_become_entries_and_one_without_a_source_is_reported() -> None:
    parsed = pointers.parse_pointers(POINTERS)

    (entry,) = parsed.entries
    assert (entry.category, entry.topic, entry.subtopic) == (
        "Medicare",
        "Telehealth flexibilities",
        "Where the patient can be",
    )
    assert entry.text == "Where a patient may be located for telehealth."
    assert entry.source_url == "https://example.org/faq.pdf"
    assert parsed.problems == ["Medicare / Telehealth flexibilities: pointer has no source."]
    assert parsed.answers == []


def test_bundled_federal_pointers_all_feed_the_medicare_rule_type() -> None:
    parsed = pointers.parse_pointers(pointers.pointer_file("federal"))

    assert len(parsed.entries) == 4 and parsed.problems == []
    for entry in parsed.entries:
        assert scope.rule_type_for(entry.category, entry.topic) == scope.MEDICARE_TELEHEALTH
        assert all(link.url.startswith("https://www.cms.gov/") for link in entry.source_links)


def test_pointers_are_stored_like_any_other_page(conn: Connection) -> None:
    run = pointers.store_pointers(conn, "federal", POINTERS, AT)

    snapshot = store.latest_snapshot(conn, "federal")
    assert (
        snapshot.url == "telecompass:data/federal_pointers.toml" and snapshot.raw_page == POINTERS
    )
    assert (run.parser_version, run.entry_count) == ("pointers-1", 1)
    assert len(store.stored_entries_for(conn, run.id)) == 1


def seed_rules(conn: Connection) -> tuple[int, int]:
    """One Florida rule against audio-only and one dated federal rule. Returns their ids."""
    _, florida_parse, entries = store_invented_page(conn, "florida")
    federal_parse = pointers.store_pointers(conn, "federal", POINTERS, AT)
    cap = Decimal("5.00")
    florida = rule_store.start_run(conn, "florida", florida_parse.id, EXTRACTION_MODEL, cap, AT)
    federal = rule_store.start_run(conn, "federal", federal_parse.id, EXTRACTION_MODEL, cap, AT)
    common = {
        "aspect": "coverage",
        "status": "draft",
        "quote_verified": True,
        "created_at": AT,
        "source_url": "https://example.org/law",
        "source_fetched_at": AT,
    }
    no_phone = rule_store.save_rule(
        conn,
        run_id=florida,
        entry_id=entries[0].id,
        jurisdiction="florida",
        rule_type=scope.MEDICAID_MODALITY,
        effect="deny",
        summary="Medicaid does not pay for telephone calls.",
        quote="The programme does not reimburse telephone conversations.",
        payer="medicaid",
        modality="audio_only",
        **common,
    )
    federal_entry = store.stored_entries_for(conn, federal_parse.id)[0]
    audio = rule_store.save_rule(
        conn,
        run_id=federal,
        entry_id=federal_entry.id,
        jurisdiction="federal",
        rule_type=scope.MEDICARE_TELEHEALTH,
        effect="allow",
        summary="Audio-only is allowed for now.",
        quote="Through December 31, 2027, audio-only services may continue.",
        payer="medicare",
        modality="audio_only",
        effective_to=date(2027, 12, 31),
        **common,
    )
    return no_phone.id, audio.id


def test_decision_is_stored_with_the_visit_and_the_rules_it_rests_on(conn: Connection) -> None:
    no_phone, audio = seed_rules(conn)

    decision, decision_id, _ = preflight.run_preflight(
        conn, preflight.demo_visit(date(2026, 12, 1)), AT
    )

    row = conn.execute("SELECT * FROM decision WHERE id = %s", (decision_id,)).fetchone()
    assert row["rule_ids"] == sorted([no_phone, audio]) == decision.rule_ids
    assert row["visit_date"] == date(2026, 12, 1)
    assert row["visit"]["profession"] == "psychiatrist"
    assert [line["key"] for line in row["answer"]][:2] == [
        scope.CROSS_STATE_LICENSURE,
        scope.MEDICAID_MODALITY,
    ]
    medicaid = next(line for line in decision.lines if line.key == scope.MEDICAID_MODALITY)
    assert medicaid.verdict == Verdict.NOT_ALLOWED


def test_printout_gives_verdicts_in_words_with_the_law_and_the_disclaimers(
    conn: Connection,
) -> None:
    no_phone, _ = seed_rules(conn)
    decision, decision_id, _ = preflight.run_preflight(
        conn, preflight.demo_visit(date(2026, 12, 1)), AT
    )

    text = preflight.render(decision, decision_id, "2026-03-15")

    assert "2. Medicaid payment for this modality: NOT ALLOWED" in text
    assert 'Law: "The programme does not reimburse telephone conversations."' in text
    assert f"[rule {no_phone}, draft, not yet approved by a person]" in text
    assert "3. Patient consent: SILENT (we hold no rule on this)" in text
    assert "In force from an unstated date to 2027-12-31." in text
    assert f"Decision {decision_id} stored with the 2 rule(s) it rests on." in text
    assert text.endswith("Not legal advice. Sources last fetched 2026-03-15.")


def test_a_visit_holds_no_field_that_could_identify_a_patient() -> None:
    assert set(Visit.model_fields) == {
        "profession",
        "licensed_in",
        "registered_in",
        "patient_state",
        "modality",
        "payer",
        "service",
        "service_category",
        "prescription",
        "visit_date",
    }


def test_state_we_do_not_hold_gives_silent_lines_not_another_states_rules(
    conn: Connection,
) -> None:
    seed_rules(conn)
    visit = preflight.demo_visit(date(2026, 12, 1)).model_copy(update={"patient_state": "TX"})

    decision, _, _ = preflight.run_preflight(conn, visit, AT)

    state_lines = [line for line in decision.lines if not line.key.startswith("medicare_")]
    assert {line.verdict for line in state_lines} <= {Verdict.SILENT, Verdict.NOT_APPLICABLE}


@pytest.fixture
def cli_env(postgres_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(config, "load_env", lambda env_file=None: None)
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_preflight_command_prints_the_answer_and_changes_with_the_date(
    conn: Connection, cli_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_rules(conn)

    assert main(["preflight", "--demo", "--date", "2026-12-01"]) == 0
    before = capsys.readouterr().out
    assert main(["preflight", "--demo", "--date", "2028-03-01"]) == 0
    after = capsys.readouterr().out

    assert "TeleCompass preflight" in before and "on 2026-12-01" in before
    assert "Medicare: this modality (for reference: the payer is not Medicare): ALLOWED" in before
    assert "We hold a rule that ended on 2027-12-31." in after
    assert conn.execute("SELECT count(*) AS n FROM decision").fetchone()["n"] == 2


def test_preflight_command_rejects_a_date_that_is_not_a_date(
    conn: Connection, cli_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["preflight", "--demo", "--date", "next tuesday"]) == 1
    assert "not valid" in capsys.readouterr().err
    assert conn.execute("SELECT count(*) AS n FROM decision").fetchone()["n"] == 0
