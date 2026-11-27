"""Parser tests on an invented page that has the structure of a CCHP state page."""

from datetime import date
from pathlib import Path

import pytest

from telecompass.models import Entry, ParsedPage
from telecompass.parse_cchp import parse_state_page

FIXTURE = Path(__file__).parent / "fixtures" / "cchp_state_page.html"


@pytest.fixture(scope="module")
def page() -> ParsedPage:
    return parse_state_page(FIXTURE.read_text(encoding="utf-8"))


def entry_at(page: ParsedPage, topic: str, index: int = 0) -> Entry:
    return [entry for entry in page.entries if entry.topic == topic][index]


def test_answer_key_keeps_group_question_and_answer(page: ParsedPage) -> None:
    assert [(a.section, a.question, a.answer) for a in page.answers] == [
        ("MEDICAID REIMBURSEMENT", "Live Video", "Yes"),
        ("MEDICAID REIMBURSEMENT", "Audio Only", "No"),
        ("PROFESSIONAL REQUIREMENTS", "Licensure Compacts", "AAA, BBB (View the list)"),
        ("PROFESSIONAL REQUIREMENTS", "Consent Requirements", "No"),
        ("STATE RESOURCES", "Medicaid Program", "Avalon Medicaid"),
    ]


def test_answer_line_without_a_colon_is_reported_not_guessed(page: ParsedPage) -> None:
    assert "At a Glance / PROFESSIONAL REQUIREMENTS: a line is not 'Question: Answer'." in (
        page.problems
    )


def test_entries_come_out_in_page_order_with_category_topic_and_subtopic(
    page: ParsedPage,
) -> None:
    assert [(e.category, e.topic, e.subtopic) for e in page.entries] == [
        ("Private Payer", "Definitions", None),
        ("Private Payer", "Parity", "SERVICE PARITY"),
        ("Private Payer", "Parity", "PAYMENT PARITY"),
        ("Medicaid", "Live Video", "POLICY"),
        ("Medicaid", "Live Video", "POLICY"),
        ("Medicaid", "Live Video", "POLICY"),
        ("Medicaid", "Overview", None),
    ]


def test_simple_entry_has_text_source_link_and_dates(page: ParsedPage) -> None:
    entry = entry_at(page, "Definitions")
    assert entry.text == "“Telehealth” means care given at a distance, by any modality."
    assert entry.source_name == "ZZ Statute 100.1"
    assert entry.source_url == "https://example.org/statute/100-1"
    assert entry.accessed == "Mar. 2026"
    assert entry.last_updated == date(2026, 3, 9)
    assert entry.no_reference_found is False


def test_source_line_with_two_links_keeps_both(page: ParsedPage) -> None:
    entry = entry_at(page, "Parity", 0)
    assert entry.text == (
        "An invented plan must cover a service given by telehealth.\n"
        "It may not ask for an in-person visit first."
    )
    assert entry.source_name == "ZZ Statute 200.1 (4). & 200.2"
    assert [(link.label, link.url) for link in entry.source_links] == [
        ("ZZ Statute 200.1 (4)", "https://example.org/statute/200-1"),
        ("200.2", "https://example.org/statute/200-2"),
    ]
    assert entry.source_url == "https://example.org/statute/200-1"
    assert entry.accessed == "Mar. 2026"


def test_no_reference_found_is_kept_and_flagged(page: ParsedPage) -> None:
    entry = entry_at(page, "Parity", 1)
    assert entry.text == "No Reference Found."
    assert entry.no_reference_found is True
    assert entry.source_name is None
    assert entry.source_links == []


def test_no_reference_found_with_a_note_after_it_is_still_flagged(page: ParsedPage) -> None:
    entry = entry_at(page, "Overview")
    assert entry.no_reference_found is True
    assert entry.text == "No Reference Found.\nSee the invented manual for general rules."


def test_list_items_become_dashed_lines(page: ParsedPage) -> None:
    entry = entry_at(page, "Live Video", 0)
    assert entry.text == (
        "Avalon Medicaid pays for live video visits.\n"
        "- The visit must be two-way.\n"
        "- The visit must be in real time."
    )
    assert entry.accessed == "Mar 2026"  # the odd spacing inside the brackets is tolerated


def test_blocks_inside_wrapper_divs_are_read_in_order(page: ParsedPage) -> None:
    entry = entry_at(page, "Live Video", 1)
    assert entry.text == (
        "Hospital at Home\nPatients in an invented home program may be seen by video."
    )
    assert entry.source_name == "ZZ Medicaid, Alert 7"
    assert entry.accessed is None


def test_text_with_no_source_line_is_an_entry_without_a_source(page: ParsedPage) -> None:
    entry = entry_at(page, "Live Video", 2)
    assert entry.text == "A passage that no SOURCE line ever follows."
    assert entry.source_name is None
    assert entry.no_reference_found is False


def test_everything_the_parser_could_not_place_is_reported(page: ParsedPage) -> None:
    assert page.problems == [
        "At a Glance / PROFESSIONAL REQUIREMENTS: a line is not 'Question: Answer'.",
        "Medicaid / Live Video / POLICY: a SOURCE line has no readable accessed date.",
        "Medicaid / Live Video / ELIGIBLE SITES: a SOURCE line has no text before it.",
        "Medicaid / Overview: no readable 'Last updated' date.",
    ]
    assert entry_at(page, "Overview").last_updated is None


def test_text_outside_the_categories_is_ignored(page: ParsedPage) -> None:
    assert all("outside any category" not in entry.text for entry in page.entries)


def test_empty_page_reports_that_nothing_was_found() -> None:
    parsed = parse_state_page("<html><body><p>Nothing here.</p></body></html>")
    assert parsed.entries == []
    assert parsed.answers == []
    assert parsed.problems == ["No 'At a Glance' answers were found.", "No entries were found."]
