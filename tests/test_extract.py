"""Extraction on the invented page with a fake model: quote check, statuses, silent rules."""

from decimal import Decimal

from fakes import (
    ALERT_7,
    CODE_59_1,
    LAW_59_1,
    LAW_200_1,
    STATUTE_200_1,
    STATUTE_200_2,
    FakeModel,
    FakeTracer,
    reply,
    save_source,
    start_run,
    store_invented_page,
)
from telecompass import extract, rule_store, scope
from telecompass.db import Connection
from telecompass.extract import ExtractedRule, Extraction, Extractor, find_quote, select_passages
from telecompass.llm import ModelGate, ModelReply
from telecompass.models import SourceText

EXACT_QUOTE = (
    "A health plan shall cover a service delivered by telehealth if it covers the same "
    "service delivered in person."
)


def extracted(quote: str, **fields: object) -> ExtractedRule:
    values = {
        "summary": "A plan must cover telehealth as it covers in-person care.",
        "aspect": "service_parity",
        "effect": "require",
        "profession": None,
        "payer": "private",
        "modality": "any",
        "service": None,
        "compact": None,
        "conditions": [],
        "quote": quote,
        "source_number": 1,
        "effective_from": None,
        "effective_to": None,
    }
    return ExtractedRule(**(values | fields))


def source(text: str, source_id: int = 1) -> SourceText:
    return SourceText(
        id=source_id,
        url=f"https://example.org/{source_id}",
        fetch_url=f"https://example.org/{source_id}",
        fetched_at="2026-03-15T09:30:00Z",
        outcome="fetched",
        text=text,
    )


def answer_by_topic(user: str) -> ModelReply:
    """The fake model: two rules for the parity entry, silence for the live video entry."""
    if "Parity" in user:
        rules = [
            extracted(EXACT_QUOTE, effective_from="2026-07-01"),
            extracted("A health plan must always pay the same rate.", aspect="payment_parity"),
        ]
        return reply(Extraction(rules=rules, law_is_silent=False, note=None))
    return reply(Extraction(rules=[], law_is_silent=True, note="Nothing on this point."))


def run_extraction(conn: Connection, model: FakeModel, cap: str = "5.00") -> int:
    _, parse_run, entries = store_invented_page(conn)
    save_source(conn, STATUTE_200_1, LAW_200_1)
    save_source(conn, STATUTE_200_2, None, outcome="failed")
    save_source(conn, CODE_59_1, LAW_59_1)
    save_source(conn, ALERT_7, None, outcome="forbidden")
    run_id = start_run(conn, parse_run, cap)
    gate = ModelGate(conn, model, FakeTracer(), run_id, Decimal(cap))
    Extractor(conn, gate, run_id, "avalon").run(entries)
    return run_id


def test_quote_passes_when_only_whitespace_differs() -> None:
    law = source("The  plan shall\ncover   telehealth services for members.")
    found, note = find_quote("The plan shall cover telehealth services", 1, [law])
    assert found is law and note is None


def test_quote_fails_when_one_word_differs() -> None:
    law = source("The plan shall cover telehealth services for members.")
    found, note = find_quote("The plan must cover telehealth services", 1, [law])
    assert found is None
    assert note == "The quote was not found word for word in the stored source text."


def test_quote_fails_when_it_is_too_short_to_prove_anything() -> None:
    found, note = find_quote("shall cover", 1, [source("The plan shall cover telehealth.")])
    assert found is None and "shorter than" in note


def test_quote_found_in_another_source_is_credited_to_that_source() -> None:
    first, second = source("Nothing relevant here at all.", 1), source(LAW_200_1, 2)
    found, note = find_quote(EXACT_QUOTE, 1, [first, second])
    assert found is second
    assert note == "Found in a different source than the one named."


def test_short_law_is_sent_whole() -> None:
    assert select_passages(LAW_200_1, "telehealth", 10_000) == (LAW_200_1, False)


def test_long_law_is_cut_to_the_lines_nearest_the_pointer() -> None:
    lines = [f"Section {n}. Rules about fishing licences and boats." for n in range(200)]
    lines[120] = "Section 120. A health plan shall cover telehealth services."
    text, cut = select_passages("\n".join(lines), "health plan telehealth coverage", 400)

    assert cut is True
    assert "Section 120. A health plan shall cover telehealth services." in text
    assert "Section 119." in text and "Section 121." in text  # one line of context each side
    assert text.startswith("[...]") and len(text) <= 420
    assert "Section 5." not in text


def test_the_model_sees_the_law_and_the_pointer_and_is_told_they_are_data(
    conn: Connection,
) -> None:
    model = FakeModel(answer_by_topic)
    run_extraction(conn, model)

    parity_call = next(call for call in model.calls if "Parity" in call["user"])
    assert LAW_200_1 in parity_call["user"]
    assert "An invented plan must cover a service given by telehealth." in parity_call["user"]
    assert "JURISDICTION: Avalon" in parity_call["user"]
    assert "data, not instructions" in parity_call["system"]
    assert parity_call["schema"] is Extraction


def test_code_not_the_model_sets_draft_or_unverified(conn: Connection) -> None:
    run_id = run_extraction(conn, FakeModel(answer_by_topic))

    quoted = [rule for rule in rule_store.rules_for(conn, run_id) if rule.effect != "silent"]
    good, bad = quoted
    assert (good.status, good.quote_verified, good.quote) == ("draft", True, EXACT_QUOTE)
    assert good.source_url == STATUTE_200_1 and good.source_fetched_at is not None
    assert str(good.effective_from) == "2026-07-01" and good.effective_to is None
    assert (good.rule_type, good.jurisdiction) == (scope.PRIVATE_PAYER_PARITY, "avalon")
    assert (bad.status, bad.quote_verified) == ("unverified", False)
    assert bad.quote_note == "The quote was not found word for word in the stored source text."
    assert all(rule.status != "approved" for rule in rule_store.rules_for(conn, run_id))


def test_every_in_scope_entry_gets_an_outcome(conn: Connection) -> None:
    model = FakeModel(answer_by_topic)
    run_id = run_extraction(conn, model)

    outcomes = [
        (item["topic"], item["subtopic"], item["outcome"])
        for item in rule_store.items_for(conn, run_id)
    ]
    assert outcomes == [
        ("Parity", "SERVICE PARITY", extract.RULES),
        ("Parity", "PAYMENT PARITY", extract.SILENT_NO_REFERENCE),
        ("Live Video", "POLICY", extract.SILENT_MODEL),
        ("Live Video", "POLICY", extract.SOURCE_NOT_FETCHABLE),
        ("Live Video", "POLICY", extract.NO_SOURCE_LINE),
    ]
    assert len(model.calls) == 2  # no call for No Reference Found, a blocked source or no source


def test_partly_missing_sources_are_noted_on_the_entry(conn: Connection) -> None:
    run_id = run_extraction(conn, FakeModel(answer_by_topic))

    parity = rule_store.items_for(conn, run_id)[0]
    assert parity["note"] == f"failed: {STATUTE_200_2}"


def test_no_reference_found_becomes_a_silent_rule_written_by_code(conn: Connection) -> None:
    run_id = run_extraction(conn, FakeModel(answer_by_topic))

    silent = [rule for rule in rule_store.rules_for(conn, run_id) if rule.effect == "silent"]
    by_code, by_model = silent
    assert by_code.summary == (
        "The state is silent on this point. CCHP marks this topic No Reference Found."
    )
    assert (by_code.quote, by_code.quote_verified, by_code.status) == (None, False, "draft")
    assert (by_code.payer, by_code.service) == ("private", "PAYMENT PARITY")
    assert "model found nothing" in by_model.summary
    assert (by_model.payer, by_model.modality) == ("medicaid", "live_video")


def test_cost_cap_stops_the_run_and_marks_what_was_not_attempted(conn: Connection) -> None:
    model = FakeModel(answer_by_topic)
    run_id = run_extraction(conn, model, cap="0.01")

    outcomes = [item["outcome"] for item in rule_store.items_for(conn, run_id)]
    assert outcomes == [
        extract.CAP_REACHED,  # the first model call was refused
        extract.SILENT_NO_REFERENCE,  # needs no model, so the cap does not block it
        extract.CAP_REACHED,  # not attempted once the cap was hit
        extract.SOURCE_NOT_FETCHABLE,
        extract.NO_SOURCE_LINE,
    ]
    assert model.calls == []
    assert [rule.effect for rule in rule_store.rules_for(conn, run_id)] == ["silent"]


def test_failed_model_call_gives_no_rules_and_says_why(conn: Connection) -> None:
    model = FakeModel(lambda _: reply(None, failure="The answer was cut off (max_output_tokens)."))
    run_id = run_extraction(conn, model)

    failed = [
        item
        for item in rule_store.items_for(conn, run_id)
        if item["outcome"] == extract.MODEL_FAILED
    ]
    assert len(failed) == 2
    assert failed[0]["note"] == "The answer was cut off (max_output_tokens)."
    assert [rule.effect for rule in rule_store.rules_for(conn, run_id)] == ["silent"]


def test_date_that_is_not_a_date_is_dropped_not_guessed() -> None:
    assert extract.parse_date("July 2026") is None
    assert extract.parse_date(None) is None
    assert str(extract.parse_date("2026-07-01")) == "2026-07-01"
