"""The rules engine on hand-made rules. No database, no model: plain functions."""

from datetime import UTC, date, datetime

from telecompass import scope
from telecompass.engine import (
    Prescription,
    Verdict,
    Visit,
    decide,
    fits_profession,
    fits_service,
    in_force,
    prescribing_topic,
)
from telecompass.models import Rule

TODAY = date(2026, 12, 1)
COUNTER = iter(range(1, 10_000))


def rule(rule_type: str, effect: str, aspect: str = "other", **fields: object) -> Rule:
    values = {
        "id": next(COUNTER),
        "extraction_run_id": 1,
        "entry_id": 1,
        "jurisdiction": "avalon",
        "rule_type": rule_type,
        "aspect": aspect,
        "effect": effect,
        "summary": f"A {effect} rule.",
        "quote": "Words copied from the law, long enough to count.",
        "quote_verified": True,
        "source_url": "https://example.org/law",
        "source_fetched_at": datetime(2026, 11, 27, tzinfo=UTC),
        "status": "draft",
        "modality": "any",
        "payer": "any",
        "created_at": datetime(2026, 11, 27, tzinfo=UTC),
    }
    return Rule(**(values | fields))


def visit(**fields: object) -> Visit:
    values = {
        "profession": "psychiatrist",
        "licensed_in": ["NY"],
        "patient_state": "FL",
        "modality": "audio_only",
        "payer": "medicaid",
        "service": "psychiatric medication management",
        "service_category": "behavioral_health",
        "visit_date": TODAY,
    }
    return Visit(**(values | fields))


def line(decision, key: str):
    return next(item for item in decision.lines if item.key == key)


LICENSURE = scope.CROSS_STATE_LICENSURE
REGISTER = rule(LICENSURE, "allow", "telehealth_registration", summary="May register.")
DUTY = rule(LICENSURE, "require", "telehealth_registration", summary="Must keep insurance.")
EMERGENCY = rule(LICENSURE, "allow", "licensure_exception", summary="Emergency exception.")
COUNSELOR_COMPACT = rule(
    LICENSURE, "allow", "compact_membership", profession="professional counselor", compact="CC"
)


def test_clinician_licensed_in_the_patients_state_needs_no_cross_state_rule() -> None:
    decision = decide(visit(licensed_in=["NY", "FL"]), [REGISTER], [])
    result = line(decision, LICENSURE)
    assert result.verdict == Verdict.ALLOWED and result.evidence == []


def test_out_of_state_clinician_without_registration_is_not_allowed_and_sees_the_routes() -> None:
    decision = decide(visit(), [REGISTER, DUTY, EMERGENCY, COUNSELOR_COMPACT], [])
    result = line(decision, LICENSURE)

    assert result.verdict == Verdict.NOT_ALLOWED
    assert [item.summary for item in result.would_allow] == [
        "May register.",
        "Emergency exception.",
    ]
    assert result.evidence == []  # a route is not evidence that the visit is allowed


def test_registered_out_of_state_clinician_is_allowed_with_the_registration_duties() -> None:
    decision = decide(visit(registered_in=["FL"]), [REGISTER, DUTY, EMERGENCY], [])
    result = line(decision, LICENSURE)

    assert result.verdict == Verdict.CONDITIONS
    assert [item.summary for item in result.evidence] == ["May register."]
    assert [item.summary for item in result.conditions] == ["Must keep insurance."]


def test_no_cross_state_rule_at_all_is_silent_not_a_guess() -> None:
    assert line(decide(visit(), [COUNSELOR_COMPACT], []), LICENSURE).verdict == Verdict.SILENT


MEDICAID = scope.MEDICAID_MODALITY
NO_PHONE = rule(MEDICAID, "deny", "coverage", modality="audio_only", payer="medicaid")
VIDEO = rule(MEDICAID, "allow", "coverage", modality="live_video", payer="medicaid")
MODIFIER = rule(MEDICAID, "require", "coverage", modality="live_video", payer="medicaid")
GLUCOSE = rule(MEDICAID, "allow", "coverage", service="continuous glucose monitor")


def test_medicaid_audio_only_is_not_payable_and_live_video_is_offered() -> None:
    result = line(decide(visit(), [NO_PHONE, VIDEO, MODIFIER, GLUCOSE], []), MEDICAID)

    assert result.verdict == Verdict.NOT_ALLOWED
    assert [item.rule_id for item in result.evidence] == [NO_PHONE.id]
    assert [item.rule_id for item in result.would_allow] == [VIDEO.id]


def test_medicaid_live_video_is_payable_with_its_conditions() -> None:
    result = line(decide(visit(modality="live_video"), [NO_PHONE, VIDEO, MODIFIER], []), MEDICAID)

    assert result.verdict == Verdict.CONDITIONS
    assert [item.rule_id for item in result.conditions] == [MODIFIER.id]


def test_modality_with_no_rule_is_silent() -> None:
    result = line(decide(visit(modality="store_and_forward"), [NO_PHONE, VIDEO], []), MEDICAID)
    assert result.verdict == Verdict.SILENT
    assert "store and forward" in result.reason


def test_a_rule_for_one_named_service_is_shown_but_does_not_decide() -> None:
    pregnancy = rule(
        MEDICAID,
        "allow",
        "coverage",
        modality="remote_patient_monitoring",
        service="monitoring for high-risk pregnancies",
        summary="Paid for high-risk pregnancies.",
    )
    general = visit(modality="remote_patient_monitoring", service=None)

    result = line(decide(general, [NO_PHONE, VIDEO, pregnancy], []), MEDICAID)

    assert result.verdict == Verdict.SILENT
    assert "named service only: monitoring for high-risk pregnancies" in result.reason
    assert [item.rule_id for item in result.would_allow] == [pregnancy.id, VIDEO.id]

    named = visit(modality="remote_patient_monitoring", service="high-risk pregnancies")
    assert line(decide(named, [pregnancy], []), MEDICAID).verdict == Verdict.ALLOWED


def test_medicaid_line_does_not_apply_to_another_payer() -> None:
    result = line(decide(visit(payer="private"), [NO_PHONE], []), MEDICAID)
    assert result.verdict == Verdict.NOT_APPLICABLE


def test_rule_for_another_service_is_left_out() -> None:
    assert fits_service(GLUCOSE, "continuous glucose monitoring") is True
    assert fits_service(GLUCOSE, "psychiatric medication management") is False
    assert fits_service(VIDEO, None) is True


def test_rule_for_another_profession_is_left_out() -> None:
    assert fits_profession(COUNSELOR_COMPACT, "psychiatrist") is False
    assert fits_profession(rule(LICENSURE, "allow", profession="physician"), "psychiatrist") is True
    assert fits_profession(rule(LICENSURE, "allow", profession="health care practitioner"), "x")
    assert fits_profession(REGISTER, "psychiatrist") is True


RX = scope.ONLINE_PRESCRIBING
SCHEDULE_II_BAN = rule(RX, "deny", "prescribing", quote="may not prescribe a Schedule II drug")
PSYCHIATRIC = rule(
    RX, "allow", "prescribing", service="Schedule II for a psychiatric disorder", summary="Psych."
)
ABORTION = rule(RX, "deny", "prescribing", service="medical abortion")
EVALUATE = rule(RX, "allow", "prescribing", summary="May evaluate by telehealth.")
STIMULANT = Prescription(drug="a stimulant", schedule="II", renewal=True)


def test_prescribing_topic_is_read_from_the_rules_own_words() -> None:
    assert prescribing_topic(SCHEDULE_II_BAN) == "schedule_ii"
    assert prescribing_topic(ABORTION) == "abortion"
    assert prescribing_topic(EVALUATE) == "general"
    assert prescribing_topic(rule(RX, "deny", quote="a Schedule III substance")) == "general"
    assert prescribing_topic(rule(RX, "deny", quote="any controlled substance")) == "controlled"


def test_schedule_ii_is_barred_unless_an_exception_applies() -> None:
    rules = [SCHEDULE_II_BAN, PSYCHIATRIC, ABORTION, EVALUATE]
    result = line(decide(visit(prescription=STIMULANT), rules, []), RX)

    assert result.verdict == Verdict.CONDITIONS
    assert "unless an exception applies" in result.reason
    assert [item.rule_id for item in result.evidence] == [SCHEDULE_II_BAN.id]
    assert [item.summary for item in result.would_allow] == ["Psych."]


def test_ban_with_no_exception_is_not_allowed() -> None:
    result = line(decide(visit(prescription=STIMULANT), [SCHEDULE_II_BAN, EVALUATE], []), RX)
    assert result.verdict == Verdict.NOT_ALLOWED


def test_drug_that_is_not_controlled_does_not_meet_the_schedule_ii_ban() -> None:
    plain = Prescription(drug="an antidepressant")
    result = line(decide(visit(prescription=plain), [SCHEDULE_II_BAN, ABORTION, EVALUATE], []), RX)

    assert result.verdict == Verdict.ALLOWED
    assert [item.rule_id for item in result.evidence] == [EVALUATE.id]


def test_no_prescription_means_the_prescribing_line_does_not_apply() -> None:
    assert line(decide(visit(), [SCHEDULE_II_BAN], []), RX).verdict == Verdict.NOT_APPLICABLE


def test_consent_is_silent_without_a_rule_and_a_condition_with_one() -> None:
    assert line(decide(visit(), [], []), scope.CONSENT).verdict == Verdict.SILENT
    needs = rule(scope.CONSENT, "require", "consent")
    result = line(decide(visit(), [needs], []), scope.CONSENT)
    assert result.verdict == Verdict.CONDITIONS and result.conditions[0].rule_id == needs.id


def test_private_plan_line_is_silent_on_parity_but_shows_contract_duties() -> None:
    contract = rule(scope.PRIVATE_PAYER_PARITY, "require", payer="private")
    result = line(decide(visit(payer="private"), [contract], []), scope.PRIVATE_PAYER_PARITY)
    assert result.verdict == Verdict.SILENT and result.conditions[0].rule_id == contract.id

    parity = rule(scope.PRIVATE_PAYER_PARITY, "require", "payment_parity", payer="private")
    result = line(decide(visit(payer="private"), [parity], []), scope.PRIVATE_PAYER_PARITY)
    assert result.verdict == Verdict.ALLOWED


def test_unverified_and_silent_rules_are_never_used() -> None:
    unverified = NO_PHONE.model_copy(update={"id": 9001, "quote_verified": False})
    silent = NO_PHONE.model_copy(update={"id": 9002, "effect": "silent", "quote": None})
    decision = decide(visit(), [unverified, silent], [])

    assert line(decision, MEDICAID).verdict == Verdict.SILENT
    assert decision.rule_ids == []


def test_state_rule_not_yet_in_force_is_left_out() -> None:
    later = NO_PHONE.model_copy(update={"id": 9003, "effective_from": date(2027, 1, 1)})
    assert in_force(later, TODAY) is False
    assert line(decide(visit(), [later], []), MEDICAID).verdict == Verdict.SILENT
    assert line(decide(visit(visit_date=date(2027, 6, 1)), [later], []), MEDICAID).verdict == (
        Verdict.NOT_ALLOWED
    )


MEDICARE = scope.MEDICARE_TELEHEALTH
END = date(2027, 12, 31)
HOME = rule(MEDICARE, "allow", "originating_site", effective_to=END, summary="Home is allowed.")
RURAL = rule(
    MEDICARE, "require", "originating_site", effective_from=date(2028, 1, 1), summary="Rural site."
)
AUDIO_MENTAL = rule(
    MEDICARE, "allow", "coverage", modality="audio_only", service_category="behavioral_health"
)
IN_PERSON = rule(
    MEDICARE,
    "require",
    "in_person_requirement",
    service_category="behavioral_health",
    effective_from=date(2028, 1, 1),
    summary="In-person visit first.",
)


def test_medicare_lines_change_when_the_date_passes_the_end_of_a_flexibility() -> None:
    federal = [HOME, RURAL, AUDIO_MENTAL, IN_PERSON]
    now = decide(visit(), [], federal)
    later = decide(visit(visit_date=date(2028, 3, 1)), [], federal)

    place_now, place_later = (line(d, "medicare_originating_site") for d in (now, later))
    assert place_now.verdict == Verdict.ALLOWED
    assert "In force through 2027-12-31" in place_now.reason
    assert place_later.verdict == Verdict.CONDITIONS
    assert [item.summary for item in place_later.conditions] == ["Rural site."]

    visit_now, visit_later = (line(d, "medicare_in_person_requirement") for d in (now, later))
    assert visit_now.verdict == Verdict.ALLOWED  # no duty yet; the future one is shown
    assert [item.summary for item in visit_now.evidence] == ["In-person visit first."]
    assert "starts on 2028-01-01" in visit_now.reason
    assert visit_later.verdict == Verdict.CONDITIONS

    assert line(now, "medicare_coverage").verdict == Verdict.ALLOWED  # no end date: permanent
    assert line(later, "medicare_coverage").verdict == Verdict.ALLOWED


def test_flexibility_that_ended_with_nothing_stated_after_it_is_silent() -> None:
    result = line(
        decide(visit(visit_date=date(2028, 3, 1)), [], [HOME]), "medicare_originating_site"
    )
    assert result.verdict == Verdict.SILENT
    assert "ended on 2027-12-31" in result.reason
    assert [item.rule_id for item in result.would_allow] == [HOME.id]


def test_medicare_rule_for_other_care_is_left_out_of_a_behavioral_visit() -> None:
    other_only = rule(MEDICARE, "deny", "coverage", modality="audio_only", service_category="other")
    assert line(decide(visit(), [], [other_only]), "medicare_coverage").verdict == Verdict.SILENT
    general = visit(service_category="other")
    assert line(decide(general, [], [other_only]), "medicare_coverage").verdict == (
        Verdict.NOT_ALLOWED
    )


def test_medicare_lines_say_when_the_payer_is_not_medicare() -> None:
    assert "for reference" in line(decide(visit(), [], [HOME]), "medicare_originating_site").title
    medicare = visit(payer="medicare")
    assert (
        "for reference" not in line(decide(medicare, [], [HOME]), "medicare_originating_site").title
    )


def test_same_visit_and_rules_always_give_the_same_decision() -> None:
    rules = [REGISTER, DUTY, NO_PHONE, VIDEO, SCHEDULE_II_BAN, PSYCHIATRIC]
    first = decide(visit(prescription=STIMULANT), rules, [HOME, AUDIO_MENTAL])
    second = decide(visit(prescription=STIMULANT), list(reversed(rules)), [AUDIO_MENTAL, HOME])

    assert first.rule_ids == second.rule_ids
    assert [(item.key, item.verdict) for item in first.lines] == [
        (item.key, item.verdict) for item in second.lines
    ]


def test_medicare_rule_for_another_profession_is_left_out() -> None:
    no_therapists = rule(MEDICARE, "deny", "eligible_practitioner", profession="physical therapist")
    decision = decide(visit(), [], [no_therapists])
    assert line(decision, "medicare_eligible_practitioner").verdict == Verdict.SILENT
    therapist = visit(profession="physical therapist")
    assert line(
        decide(therapist, [], [no_therapists]), "medicare_eligible_practitioner"
    ).verdict == (Verdict.NOT_ALLOWED)


def test_end_date_is_stated_only_when_every_basis_has_one() -> None:
    permanent = rule(MEDICARE, "allow", "originating_site", service_category="behavioral_health")
    result = line(decide(visit(), [], [HOME, permanent]), "medicare_originating_site")
    assert result.verdict == Verdict.ALLOWED
    assert "In force through" not in result.reason
