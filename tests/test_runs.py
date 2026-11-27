"""Runs are kept side by side so an improvement can be measured, not just claimed."""

from decimal import Decimal

from fakes import (
    AT,
    CODE_59_1,
    LAW_59_1,
    FakeModel,
    FakeTracer,
    reply,
    save_source,
    store_invented_page,
)
from telecompass import extract, grade, rule_store, scope
from telecompass.db import Connection
from telecompass.extract import Extraction, Extractor
from telecompass.llm import EXTRACTION_MODEL, ModelGate

QUOTE = "The programme reimburses services delivered by live, two-way video."


def save_video_rule(conn: Connection, run_id: int, entry_id: int, verified: bool) -> None:
    rule_store.save_rule(
        conn,
        run_id=run_id,
        entry_id=entry_id,
        jurisdiction="avalon",
        rule_type=scope.MEDICAID_MODALITY,
        aspect="coverage",
        effect="allow",
        summary="Medicaid pays for live video.",
        status="draft" if verified else "unverified",
        quote_verified=verified,
        quote=QUOTE if verified else "A sentence that is not in the law.",
        modality="live_video",
        created_at=AT,
    )


def test_results_list_every_run_with_its_instructions_version(conn: Connection) -> None:
    _, parse_run, entries = store_invented_page(conn)
    cap = Decimal("5.00")
    first = rule_store.start_run(conn, "avalon", parse_run.id, EXTRACTION_MODEL, cap, AT)
    save_video_rule(conn, first, entries[0].id, verified=False)
    second = rule_store.start_run(conn, "avalon", parse_run.id, EXTRACTION_MODEL, cap, AT, "v2")
    save_video_rule(conn, second, entries[0].id, verified=True)

    results = grade.build_results(conn, "avalon", AT)

    assert results["run"]["id"] == second and results["run"]["prompt_version"] == "v2"
    before, after = results["runs"]
    assert (before["run_id"], before["prompt_version"]) == (first, "v1")
    assert (after["run_id"], after["prompt_version"]) == (second, "v2")
    assert (before["quotes_found_word_for_word"], after["quotes_found_word_for_word"]) == (0, 1)
    # Live Video is "Yes" on the page: unverified does not count, verified does.
    assert (before["answer_key_matched"], after["answer_key_matched"]) == (2, 3)
    assert before["answer_key_total"] == after["answer_key_total"] == 4


def test_instructions_cover_the_weak_points_the_first_review_found() -> None:
    prompt = extract.SYSTEM_PROMPT
    assert extract.PROMPT_VERSION == "v2"
    assert "never be broader than the SOURCE" in prompt
    assert "Skip veterinary medicine" in prompt
    assert "Do not take a modality from the POINTER" in prompt


def test_entry_the_model_sets_aside_keeps_the_models_reason(conn: Connection) -> None:
    _, parse_run, entries = store_invented_page(conn)
    save_source(conn, CODE_59_1, LAW_59_1)
    run_id = rule_store.start_run(
        conn, "avalon", parse_run.id, EXTRACTION_MODEL, Decimal("5.00"), AT, "v2"
    )
    answer = Extraction(rules=[], law_is_silent=False, note="The source is about animal care only.")
    gate = ModelGate(conn, FakeModel(lambda _: reply(answer)), FakeTracer(), run_id, Decimal("5"))

    Extractor(conn, gate, run_id, "avalon").run(entries)

    set_aside = [
        item for item in rule_store.items_for(conn, run_id) if item["outcome"] == extract.NO_RULES
    ]
    assert [item["note"] for item in set_aside] == ["The source is about animal care only."]
    assert all(rule.effect == "silent" for rule in rule_store.rules_for(conn, run_id))
