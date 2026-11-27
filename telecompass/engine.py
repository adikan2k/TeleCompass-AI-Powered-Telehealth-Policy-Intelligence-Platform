"""Decide one telehealth visit on one date from stored rules (D13).

Plain typed Python and no model (rule 9): the same visit and the same rules always give the
same answer. Only rules whose quote was found word for word in the law are used (rule 10).
Where no rule speaks to a point the answer is "silent", never a guess (rule 11).
"""

import re
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from telecompass import scope
from telecompass.models import Rule


class Verdict(StrEnum):
    ALLOWED = "allowed"
    CONDITIONS = "allowed_with_conditions"
    NOT_ALLOWED = "not_allowed"
    SILENT = "silent"
    NOT_APPLICABLE = "not_applicable"


Modality = Literal["live_video", "audio_only", "store_and_forward", "remote_patient_monitoring"]


class Prescription(BaseModel):
    drug: str
    schedule: Literal["II", "III", "IV", "V"] | None = None  # the controlled-substance schedule
    renewal: bool = False


class Visit(BaseModel):
    """An invented visit to check. It never holds a name, a date of birth or any patient data."""

    profession: str
    licensed_in: list[str]
    registered_in: list[str] = []  # states where the clinician holds a telehealth registration
    patient_state: str
    modality: Modality
    payer: Literal["medicaid", "medicare", "private", "self_pay"]
    service: str | None = None
    service_category: Literal["behavioral_health", "other"] = "other"
    prescription: Prescription | None = None
    visit_date: date


class Evidence(BaseModel):
    """A rule shown to the reader: what it says, the exact words of the law, and where from."""

    rule_id: int
    summary: str
    quote: str
    source_url: str | None
    source_fetched: date | None
    status: str
    conditions: list[str]
    effective_from: date | None
    effective_to: date | None
    auto_review: str | None = None


class Line(BaseModel):
    """The answer for one rule type."""

    key: str
    title: str
    verdict: Verdict
    reason: str
    evidence: list[Evidence] = []
    conditions: list[Evidence] = []
    would_allow: list[Evidence] = []


class Decision(BaseModel):
    visit: Visit
    lines: list[Line]
    rule_ids: list[int]


# Words that name one profession. A rule whose "who it applies to" has none of these is about
# clinicians in general. A rule that has one applies only to a visit by that profession.
SPECIFIC_PROFESSION_WORDS = (
    "physician", "psychiatrist", "psychologist", "counselor", "therapist", "nurse", "pharmacist",
    "dentist", "dental", "optometrist", "chiropract", "podiatr", "audiolog", "speech",
    "social worker", "dietitian", "midwife", "analyst", "veterinar",
)  # fmt: skip
PROFESSION_FAMILY = {
    "psychiatrist": ("psychiatrist", "physician"),
    "physician": ("physician",),
    "psychologist": ("psychologist",),
    "nurse practitioner": ("nurse",),
    "counselor": ("counselor",),
    "pharmacist": ("pharmacist",),
    "physical therapist": ("physical therapist",),
}


def usable(rules: list[Rule]) -> list[Rule]:
    """Rules the engine may rely on: a quote found word for word, and not a silent marker."""
    return [
        rule for rule in rules if rule.quote_verified and rule.quote and rule.effect != "silent"
    ]


def in_force(rule: Rule, on: date) -> bool:
    """True if the rule applies on the date. A missing date means no stated start or end."""
    started = rule.effective_from is None or rule.effective_from <= on
    not_ended = rule.effective_to is None or on <= rule.effective_to
    return started and not_ended


def fits_profession(rule: Rule, profession: str) -> bool:
    """False only when the rule names some other profession than the visit's clinician."""
    if not rule.profession:
        return True
    named = rule.profession.lower()
    if not any(word in named for word in SPECIFIC_PROFESSION_WORDS):
        return True
    family = PROFESSION_FAMILY.get(profession.lower(), (profession.lower(),))
    return any(word in named for word in family)


def fits_service(rule: Rule, service: str | None) -> bool:
    """A rule limited to a service applies only when the visit's service shares a key word."""
    if not rule.service:
        return True
    wanted = set(re.findall(r"[a-z]{5,}", (service or "").lower()))
    return bool(wanted & set(re.findall(r"[a-z]{5,}", rule.service.lower())))


def prescribing_topic(rule: Rule) -> str:
    """What a prescribing rule is about, read from its own words by plain pattern matching."""
    text = f"{rule.service or ''} {rule.quote or ''}".lower()
    if "abortion" in text:
        return "abortion"
    if "marijuana" in text or "cannabis" in text:
        return "marijuana"
    if re.search(r"schedule\s+ii(?!i)\b", text):
        return "schedule_ii"
    if "controlled substance" in text:
        return "controlled"
    return "general"


def evidence(rule: Rule) -> Evidence:
    return Evidence(
        rule_id=rule.id,
        summary=rule.summary,
        quote=rule.quote or "",
        source_url=rule.source_url,
        source_fetched=rule.source_fetched_at.date() if rule.source_fetched_at else None,
        status=rule.status,
        conditions=rule.conditions,
        effective_from=rule.effective_from,
        effective_to=rule.effective_to,
        auto_review=rule.auto_review,
    )


def _shown(rules: list[Rule]) -> list[Evidence]:
    return [evidence(rule) for rule in rules]


def _of(rules: list[Rule], effect: str) -> list[Rule]:
    return [rule for rule in rules if rule.effect == effect]


def licensure_line(visit: Visit, rules: list[Rule]) -> Line:
    title = "Cross-state licensure"
    key = scope.CROSS_STATE_LICENSURE
    state = visit.patient_state
    if state in visit.licensed_in:
        reason = (
            f"The clinician is licensed in {state}, so cross-state rules do not come into play."
        )
        return Line(key=key, title=title, verdict=Verdict.ALLOWED, reason=reason)
    mine = [r for r in rules if r.rule_type == key and fits_profession(r, visit.profession)]
    registration = [r for r in mine if r.aspect == "telehealth_registration"]
    paths = [r for r in mine if r.effect == "allow" and r.aspect != "license_required"]
    if not paths:
        reason = f"We hold no rule on treating a patient in {state} without a {state} licence."
        return Line(key=key, title=title, verdict=Verdict.SILENT, reason=reason)
    if state in visit.registered_in and _of(registration, "allow"):
        return Line(
            key=key,
            title=title,
            verdict=Verdict.CONDITIONS,
            reason=f"Allowed under the clinician's {state} telehealth registration, with duties.",
            evidence=_shown(_of(registration, "allow")),
            conditions=_shown([r for r in registration if r.effect != "allow"]),
        )
    return Line(
        key=key,
        title=title,
        verdict=Verdict.NOT_ALLOWED,
        reason=(
            f"The clinician has no {state} licence and no {state} telehealth registration. "
            "The law gives the routes below; none is met as the visit is described."
        ),
        would_allow=_shown(paths),
    )


def medicaid_line(visit: Visit, rules: list[Rule]) -> Line:
    title = "Medicaid payment for this modality"
    key = scope.MEDICAID_MODALITY
    if visit.payer != "medicaid":
        reason = f"The payer is {visit.payer}, not Medicaid."
        return Line(key=key, title=title, verdict=Verdict.NOT_APPLICABLE, reason=reason)
    mine = [
        r
        for r in rules
        if r.rule_type == key
        and fits_profession(r, visit.profession)
        and fits_service(r, visit.service)
    ]
    here = [r for r in mine if r.modality in (visit.modality, "any")]
    other_ways = [
        r for r in mine if r.effect == "allow" and r.modality not in (visit.modality, "any")
    ]
    # Rules that pay for this modality only for a named service. The public form names no
    # service (no free text), so they cannot decide the visit, but they are shown, not hidden.
    only_for = [
        r
        for r in rules
        if r.rule_type == key
        and r.effect == "allow"
        and r.modality in (visit.modality, "any")
        and fits_profession(r, visit.profession)
        and not fits_service(r, visit.service)
    ]
    return _coverage_line(key, title, visit.modality, here, other_ways, only_for)


def _coverage_line(
    key: str,
    title: str,
    modality: str,
    here: list[Rule],
    other_ways: list[Rule],
    only_for: list[Rule] | None = None,
) -> Line:
    only_for = only_for or []
    name = modality.replace("_", " ")
    denies, allows, requires = _of(here, "deny"), _of(here, "allow"), _of(here, "require")
    if denies:
        return Line(
            key=key,
            title=title,
            verdict=Verdict.NOT_ALLOWED,
            reason=f"Not payable: a rule excludes {name}.",
            evidence=_shown(denies),
            would_allow=_shown(other_ways),
        )
    if allows:
        has_conditions = bool(requires) or any(rule.conditions for rule in allows)
        return Line(
            key=key,
            title=title,
            verdict=Verdict.CONDITIONS if has_conditions else Verdict.ALLOWED,
            reason=f"Payable for {name}" + (", with conditions." if has_conditions else "."),
            evidence=_shown(allows),
            conditions=_shown(requires),
        )
    reason = f"We hold no rule that says whether {name} is paid."
    if only_for:
        services = "; ".join(sorted({rule.service or "" for rule in only_for}))
        reason = (
            f"We hold no rule that says whether {name} is paid in general. "
            f"It is paid for a named service only: {services}."
        )
    return Line(
        key=key,
        title=title,
        verdict=Verdict.SILENT,
        reason=reason,
        would_allow=_shown([*only_for, *other_ways]),
    )


def consent_line(visit: Visit, rules: list[Rule]) -> Line:
    title = "Patient consent"
    required = [r for r in rules if r.rule_type == scope.CONSENT and r.effect == "require"]
    if required:
        return Line(
            key=scope.CONSENT,
            title=title,
            verdict=Verdict.CONDITIONS,
            reason="Consent is required.",
            conditions=_shown(required),
        )
    reason = f"We hold no {visit.patient_state} rule that requires consent for a telehealth visit."
    return Line(key=scope.CONSENT, title=title, verdict=Verdict.SILENT, reason=reason)


def prescribing_line(visit: Visit, rules: list[Rule]) -> Line:
    title = "Prescribing by telehealth"
    key = scope.ONLINE_PRESCRIBING
    if visit.prescription is None:
        reason = "No prescription is part of this visit."
        return Line(key=key, title=title, verdict=Verdict.NOT_APPLICABLE, reason=reason)
    topics = {"general"}
    if visit.prescription.schedule:
        topics.add("controlled")
    if visit.prescription.schedule == "II":
        topics.add("schedule_ii")
    mine = [
        r
        for r in rules
        if r.rule_type == key
        and fits_profession(r, visit.profession)
        and prescribing_topic(r) in topics
    ]
    specific = [r for r in mine if prescribing_topic(r) != "general"]
    denies, exceptions = _of(specific, "deny"), _of(specific, "allow")
    requires = _of(mine, "require")
    drug = visit.prescription.drug
    if denies and exceptions:
        return Line(
            key=key,
            title=title,
            verdict=Verdict.CONDITIONS,
            reason=f"Prescribing {drug} by telehealth is barred unless an exception applies.",
            evidence=_shown(denies),
            would_allow=_shown(exceptions),
            conditions=_shown(requires),
        )
    if denies:
        return Line(
            key=key,
            title=title,
            verdict=Verdict.NOT_ALLOWED,
            reason=f"A rule bars prescribing {drug} by telehealth.",
            evidence=_shown(denies),
        )
    if mine:
        return Line(
            key=key,
            title=title,
            verdict=Verdict.CONDITIONS if requires else Verdict.ALLOWED,
            reason=f"We hold no rule that bars prescribing {drug} by telehealth.",
            evidence=_shown(_of(mine, "allow")),
            conditions=_shown(requires),
        )
    reason = "We hold no rule on prescribing by telehealth for this visit."
    return Line(key=key, title=title, verdict=Verdict.SILENT, reason=reason)


def private_payer_line(visit: Visit, rules: list[Rule]) -> Line:
    title = "Private plan duties"
    key = scope.PRIVATE_PAYER_PARITY
    if visit.payer != "private":
        reason = f"The payer is {visit.payer}, not a private plan."
        return Line(key=key, title=title, verdict=Verdict.NOT_APPLICABLE, reason=reason)
    mine = [r for r in rules if r.rule_type == key]
    parity = [r for r in mine if r.aspect in ("service_parity", "payment_parity")]
    if _of(parity, "require"):
        return Line(
            key=key,
            title=title,
            verdict=Verdict.ALLOWED,
            reason="State law requires plans to cover or pay for telehealth as for in-person care.",
            evidence=_shown(_of(parity, "require")),
        )
    return Line(
        key=key,
        title=title,
        verdict=Verdict.SILENT,
        reason=(
            "We hold no rule that makes a private plan cover or pay for telehealth at parity."
            + (" The law does set the contract duties below." if mine else "")
        ),
        conditions=_shown(mine),
    )


MEDICARE_ASPECTS = {
    "originating_site": "Medicare: where the patient can be",
    "coverage": "Medicare: this modality",
    "in_person_requirement": "Medicare: in-person visit requirement",
    "eligible_practitioner": "Medicare: who can provide the visit",
}


def medicare_lines(visit: Visit, rules: list[Rule]) -> list[Line]:
    """One line per Medicare aspect, decided by which dated rules are in force on the visit date."""
    mine = [
        r
        for r in rules
        if r.rule_type == scope.MEDICARE_TELEHEALTH
        and r.modality in (visit.modality, "any")
        and r.service_category in (visit.service_category, "any")
        and fits_profession(r, visit.profession)
    ]
    note = "" if visit.payer == "medicare" else " (for reference: the payer is not Medicare)"
    lines = []
    for aspect, title in MEDICARE_ASPECTS.items():
        group = [r for r in mine if r.aspect == aspect]
        decide_line = requirement_line if aspect == "in_person_requirement" else dated_line
        lines.append(decide_line(f"medicare_{aspect}", title + note, group, visit.visit_date))
    return lines


def requirement_line(key: str, title: str, rules: list[Rule], on: date) -> Line:
    """A line about a duty that starts on a date: is it in force yet, and if not, when."""
    live = [rule for rule in rules if in_force(rule, on)]
    coming = [r for r in rules if r.effective_from is not None and r.effective_from > on]
    requires = _of(live, "require")
    if requires:
        return Line(
            key=key,
            title=title,
            verdict=Verdict.CONDITIONS,
            reason=f"A requirement is in force on {on}.",
            conditions=_shown(requires),
            evidence=_shown(_of(live, "allow")),
        )
    if not rules:
        return Line(
            key=key, title=title, verdict=Verdict.SILENT, reason="We hold no rule on this point."
        )
    first = min((r.effective_from for r in _of(coming, "require")), default=None)
    reason = f"No requirement we hold is in force on {on}." + (
        f" One starts on {first}." if first else ""
    )
    return Line(
        key=key,
        title=title,
        verdict=Verdict.ALLOWED,
        reason=reason,
        evidence=_shown([*_of(live, "allow"), *_of(coming, "require")]),
    )


def dated_line(key: str, title: str, rules: list[Rule], on: date) -> Line:
    """Decide from dated rules: what is in force on the date, what has ended, what is coming."""
    live = [rule for rule in rules if in_force(rule, on)]
    ended = [r for r in rules if r.effective_to is not None and r.effective_to < on]
    coming = [r for r in rules if r.effective_from is not None and r.effective_from > on]
    denies, allows, requires = _of(live, "deny"), _of(live, "allow"), _of(live, "require")
    if denies:
        reason = f"Not allowed on {on}." + _until(denies)
        return Line(key=key, title=title, verdict=Verdict.NOT_ALLOWED, reason=reason,
                    evidence=_shown(denies), would_allow=_shown(_of(ended, "allow")))  # fmt: skip
    if allows or requires:
        conditional = bool(requires) or any(rule.conditions for rule in allows)
        verdict = Verdict.CONDITIONS if conditional else Verdict.ALLOWED
        reason = ("Allowed" if allows else "A requirement applies") + f" on {on}."
        reason += _until(allows or requires)
        return Line(key=key, title=title, verdict=verdict, reason=reason,
                    evidence=_shown(allows), conditions=_shown(requires))  # fmt: skip
    if ended or coming:
        last = max((r.effective_to for r in ended), default=None)
        first = min((r.effective_from for r in coming), default=None)
        ended_part = f"a rule that ended on {last}" if last else ""
        coming_part = f"one that starts on {first}" if first else ""
        parts = [ended_part, coming_part]
        reason = (
            f"No rule we hold is in force on {on}. We hold "
            + " and ".join(p for p in parts if p)
            + "."
        )
        return Line(key=key, title=title, verdict=Verdict.SILENT, reason=reason,
                    would_allow=_shown([*ended, *coming]))  # fmt: skip
    return Line(
        key=key, title=title, verdict=Verdict.SILENT, reason="We hold no rule on this point."
    )


def _until(rules: list[Rule]) -> str:
    """When the basis runs out. Nothing is said if any of the rules has no stated end."""
    ends = [rule.effective_to for rule in rules]
    if not ends or any(end is None for end in ends):
        return ""
    return f" In force through {max(ends)}."


def decide(visit: Visit, state_rules: list[Rule], federal_rules: list[Rule]) -> Decision:
    """Decide every line for a visit. `state_rules` are for the patient's state."""
    state = [rule for rule in usable(state_rules) if in_force(rule, visit.visit_date)]
    lines = [
        licensure_line(visit, state),
        medicaid_line(visit, state),
        consent_line(visit, state),
        prescribing_line(visit, state),
        private_payer_line(visit, state),
        *medicare_lines(visit, usable(federal_rules)),
    ]
    used = {
        item.rule_id
        for line in lines
        for item in (*line.evidence, *line.conditions, *line.would_allow)
    }
    return Decision(visit=visit, lines=lines, rule_ids=sorted(used))
