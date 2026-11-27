"""Render what we hold for a jurisdiction as plain text for the terminal.

CCHP's text is copyrighted (rule 15), so only a short excerpt of each entry is shown, with a
link back to the page it came from.
"""

from telecompass.models import Entry, GlanceAnswer, ParseRun, Snapshot

EXCERPT_CHARS = 200
DISCLAIMER = "Not legal advice."


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """The first `limit` characters on one line, with "..." if anything was cut."""
    one_line = " ".join(text.split())
    if len(one_line) <= limit:
        return one_line
    return one_line[:limit].rstrip() + "..."


def render(
    snapshot: Snapshot, run: ParseRun, answers: list[GlanceAnswer], entries: list[Entry]
) -> str:
    """The full `show` output as one string."""
    lines = [
        f"{snapshot.jurisdiction.title()}: CCHP page {snapshot.url}",
        f"Snapshot {snapshot.id}, fetched {snapshot.fetched_at:%Y-%m-%d %H:%M} UTC, "
        f"sha256 {snapshot.sha256[:12]}",
        f"Parse run {run.id}, parser {run.parser_version}",
        "",
    ]
    lines += _answer_lines(answers)
    lines += _entry_lines(entries)
    lines += _problem_lines(run.problems)
    lines += [
        f"Excerpts only, first {EXCERPT_CHARS} characters of each entry. "
        f"Full text and copyright: {snapshot.url}",
        f"{DISCLAIMER} Sources last fetched {snapshot.fetched_at:%Y-%m-%d}.",
    ]
    return "\n".join(lines)


def _answer_lines(answers: list[GlanceAnswer]) -> list[str]:
    lines = [f"AT A GLANCE, the answer key ({len(answers)} answers)"]
    section = None
    for answer in answers:
        if answer.section != section:
            section = answer.section
            lines.append(f"  {section}")
        lines.append(f"    {answer.question}: {answer.answer}")
    return lines + [""]


def _entry_lines(entries: list[Entry]) -> list[str]:
    sourced = sum(1 for entry in entries if entry.source_name)
    no_reference = sum(1 for entry in entries if entry.no_reference_found)
    unsourced = len(entries) - sourced - no_reference
    lines = [
        f"ENTRIES ({len(entries)}: {sourced} with a SOURCE line, "
        f'{no_reference} marked "No Reference Found", {unsourced} with no SOURCE line)'
    ]
    for number, entry in enumerate(entries, start=1):
        lines += _one_entry(number, entry)
    return lines + [""]


def _one_entry(number: int, entry: Entry) -> list[str]:
    place = " > ".join(part for part in (entry.category, entry.topic, entry.subtopic) if part)
    updated = f"  (last updated {entry.last_updated})" if entry.last_updated else ""
    lines = [f"[{number}] {place}{updated}", f"    {excerpt(entry.text)}"]
    if entry.source_name:
        accessed = f" (accessed {entry.accessed})" if entry.accessed else ""
        lines.append(f"    SOURCE: {entry.source_name}{accessed}")
        lines += [f"      {link.url}" for link in entry.source_links]
    elif entry.no_reference_found:
        lines.append("    SOURCE: none. CCHP marks this No Reference Found.")
    else:
        lines.append("    SOURCE: none given for this passage.")
    return lines


def _problem_lines(problems: list[str]) -> list[str]:
    if not problems:
        return ["Parser notes: none.", ""]
    return [f"Parser notes ({len(problems)}):"] + [f"  - {note}" for note in problems] + [""]
