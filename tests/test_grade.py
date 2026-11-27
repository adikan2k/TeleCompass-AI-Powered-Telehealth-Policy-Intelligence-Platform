"""The grade: plain Python from rules to yes, no or silent, and the results file."""

import json
from decimal import Decimal
from pathlib import Path

from fakes import AT, CODE_59_1, LAW_59_1, save_source, start_run, store_invented_page
from telecompass import grade, rule_store, scope
from telecompass.db import Connection
from telecompass.models import GlanceAnswer, Rule


def rule(rule_type: str, effect: str = "allow", verified: bool = True, **fields: object) -> Rule:
    values = {
        "id": 1,
        "extraction_run_id": 1,
        "entry_id": 1,
        "jurisdiction": "avalon",
        "rule_type": rule_type,
        "aspect": "other",
        "effect": effect,
        "summary": "A rule.",
        "quote": "words copied from the law, long enough",
        "quote_verified": verified,
        "status": "draft" if verified else "unverified",
        "created_at": AT,
    }
    return Rule(**(values | fields))


def line(question: str) -> grade.KeyLine:
    return next(key for key in grade.KEY_LINES if key.question == question)


def answer(section: str, question: str, text: str) -> GlanceAnswer:
    return GlanceAnswer(section=section, question=question, answer=text)


def test_compare_separates_a_miss_from_a_wrong_answer() -> None:
    assert grade.compare("yes", "yes") == grade.AGREE
    assert grade.compare("no", "no") == grade.AGREE
    assert grade.compare("yes", "silent") == grade.MISS
    assert grade.compare("no", "silent") == grade.AGREE_NOTHING_FOUND
    assert grade.compare("yes", "no") == grade.WRONG
    assert grade.compare("no", "yes") == grade.WRONG


def test_medicaid_modality_needs_an_allow_rule_for_that_modality() -> None:
    video = rule(scope.MEDICAID_MODALITY, "allow", modality="live_video")
    phone = rule(scope.MEDICAID_MODALITY, "deny", modality="audio_only")

    assert grade.our_answer(line("Live Video"), [video, phone]) == "yes"
    assert grade.our_answer(line("Audio Only"), [video, phone]) == "no"
    assert grade.our_answer(line("Store-and-Forward"), [video, phone]) == "silent"


def test_unverified_and_silent_rules_never_count_towards_an_answer() -> None:
    unverified = rule(scope.MEDICAID_MODALITY, "allow", verified=False, modality="live_video")
    silent = rule(scope.MEDICAID_MODALITY, "silent", verified=False, modality="live_video")

    assert grade.our_answer(line("Live Video"), [unverified, silent]) == "silent"


def test_private_payer_and_licensure_lines() -> None:
    law = rule(scope.PRIVATE_PAYER_PARITY, "require", aspect="service_parity")
    exception = rule(scope.CROSS_STATE_LICENSURE, "allow", aspect="licensure_exception")
    registration = rule(scope.CROSS_STATE_LICENSURE, "require", aspect="telehealth_registration")
    rules = [law, exception, registration]

    assert grade.our_answer(line("Law Exists"), rules) == "yes"
    assert grade.our_answer(line("Payment Parity"), rules) == "silent"
    assert grade.our_answer(line("Limited Licensure Exceptions"), rules) == "yes"
    assert (
        grade.our_answer(line("Telehealth Specific License/Registration Process"), rules) == "yes"
    )
    assert grade.our_answer(line("Consent Requirements"), rules) == "silent"
    parity = rule(scope.PRIVATE_PAYER_PARITY, "require", aspect="payment_parity")
    assert grade.our_answer(line("Payment Parity"), [parity]) == "yes"


def test_yes_and_no_are_read_from_the_start_of_cchps_answer() -> None:
    assert grade.yes_or_no("Yes (See section for applicable profession)") == "yes"
    assert grade.yes_or_no("No") == "no"
    assert grade.yes_or_no("ASLP, CC, IMLC") is None


def test_lines_are_graded_only_where_the_page_has_them() -> None:
    answers = [
        answer("MEDICAID REIMBURSEMENT", "Live Video", "Yes"),
        answer("MEDICAID REIMBURSEMENT", "Audio Only", "No"),
        answer("PROFESSIONAL REQUIREMENTS", "Consent Requirements", "No"),
        answer("STATE RESOURCES", "Medicaid Program", "Avalon Medicaid"),
    ]
    rules = [rule(scope.MEDICAID_MODALITY, "allow", modality="live_video")]

    graded = grade.grade_lines(answers, rules)

    assert [(g["question"], g["cchp"], g["ours"], g["outcome"]) for g in graded] == [
        ("Live Video", "yes", "yes", grade.AGREE),
        ("Audio Only", "no", "silent", grade.AGREE_NOTHING_FOUND),
        ("Consent Requirements", "no", "silent", grade.AGREE_NOTHING_FOUND),
    ]


def test_compacts_are_compared_as_sets() -> None:
    answers = [answer("PROFESSIONAL REQUIREMENTS", "Licensure Compacts", "IMLC, PSY, PTC (View)")]

    def member(name: str) -> Rule:
        return rule(scope.CROSS_STATE_LICENSURE, aspect="compact_membership", compact=name)

    exact = grade.grade_lines(answers, [member("IMLC"), member("PSYPACT"), member("PT")])[0]
    fewer = grade.grade_lines(answers, [member("IMLC")])[0]
    extra = grade.grade_lines(answers, [member("IMLC"), member("NLC")])[0]

    assert (exact["cchp"], exact["outcome"]) == (["IMLC", "PSYPACT", "PT"], grade.AGREE)
    assert (fewer["ours"], fewer["outcome"]) == (["IMLC"], grade.MISS)
    assert extra["outcome"] == grade.WRONG


def test_results_file_holds_the_grade_the_counts_and_no_labels_yet(
    conn: Connection, tmp_path: Path
) -> None:
    _, parse_run, entries = store_invented_page(conn)
    source = save_source(conn, CODE_59_1, LAW_59_1)
    run_id = start_run(conn, parse_run)
    live_video = next(entry for entry in entries if entry.topic == "Live Video")
    quote = "The programme reimburses services delivered by live, two-way video."
    common = {
        "run_id": run_id,
        "entry_id": live_video.id,
        "jurisdiction": "avalon",
        "rule_type": scope.MEDICAID_MODALITY,
        "aspect": "coverage",
        "summary": "Medicaid pays for live video.",
        "created_at": AT,
        "payer": "medicaid",
        "modality": "live_video",
        "source_text_id": source.id,
    }
    rule_store.save_rule(
        conn, effect="allow", status="draft", quote_verified=True, quote=quote, **common
    )
    rule_store.save_rule(
        conn, effect="allow", status="unverified", quote_verified=False, quote="made up", **common
    )
    rule_store.save_item(conn, run_id, live_video.id, scope.MEDICAID_MODALITY, "rules")
    rule_store.save_item(
        conn, run_id, live_video.id, scope.MEDICAID_MODALITY, "source_not_fetchable", "forbidden"
    )

    results = grade.build_results(conn, "avalon", AT)
    path = grade.write_results(results, tmp_path)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "extraction_avalon.json"
    assert saved["not_legal_advice"] == "Not legal advice. Sources last fetched 2026-03-15."
    assert saved["run"]["model"] == "gpt-6.2-sol" and saved["run"]["cap_usd"] == 5.0
    assert saved["cost"] == {
        "model_calls": 0,
        "failed_calls": 0,
        "input_tokens": 0,
        "cached_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
    }
    assert saved["rules"]["quote_check"] == {"checked": 2, "passed": 1, "pass_rate": 0.5}
    assert saved["rules"]["by_status"] == {"draft": 1, "unverified": 1}
    assert saved["entries"]["by_outcome"] == {"rules": 1, "source_not_fetchable": 1}
    assert saved["entries"]["without_rules"][0]["topic"] == "Live Video"
    lines = {g["question"]: g["outcome"] for g in saved["answer_key"]["lines"]}
    assert lines == {
        "Live Video": grade.AGREE,
        "Audio Only": grade.AGREE_NOTHING_FOUND,
        "Consent Requirements": grade.AGREE_NOTHING_FOUND,
        "Licensure Compacts": grade.MISS,
    }
    assert (saved["answer_key"]["matched"], saved["answer_key"]["total"]) == (3, 4)
    assert saved["labels"]["labelled"] == 0 and saved["labels"]["items"] == []


def test_grading_before_any_extraction_says_what_to_run(conn: Connection) -> None:
    try:
        grade.build_results(conn, "avalon", AT)
    except LookupError as error:
        assert "extract avalon" in str(error)
    else:
        raise AssertionError("expected a LookupError")


def test_cap_is_stored_exactly(conn: Connection) -> None:
    _, parse_run, _ = store_invented_page(conn)
    start_run(conn, parse_run, cap="2.50")
    assert rule_store.latest_run(conn, "avalon")["cap_usd"] == Decimal("2.5000")
