"""Turn a stored CCHP state page into typed entries and the "At a Glance" answer key.

The page is untrusted data: it is read as text and nothing in it is followed or run.
The parser never guesses. Anything it cannot place goes into `problems`.

How the page is laid out (checked against the stored Florida snapshot):

- `.atglance-slide`: an <h4> group name and <li> lines written "Question: Answer".
- `.item.has-content`: one category. Its name is the <h2> inside `.item-head`.
- `.item-content-section`: one topic, with `p.last-updated` and `h2.section-head`.
  Inside it, a plain <h2> starts a sub-topic, an <hr> ends one, and a paragraph that starts
  with "SOURCE:" closes the text before it into one entry.
"""

import re
from collections.abc import Iterator
from datetime import date

from bs4 import BeautifulSoup, Comment, Tag

from telecompass.models import Entry, GlanceAnswer, ParsedPage, SourceLink

PARSER_VERSION = "cchp-1"

_ACCESSED = re.compile(r"\(\s*Accessed\s+([A-Za-z]{3,9}\.?\s+\d{4})\s*\)")
_ACCESSED_LOOSE = re.compile(r"\(\s*Accessed\b[^)]*\)?")
_LAST_UPDATED = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_NO_REFERENCE = re.compile(r"no reference found\.?", re.IGNORECASE)
_SOURCE_PREFIX = re.compile(r"^SOURCE\s*:?\s*", re.IGNORECASE)
_HEADINGS = {"h2", "h3", "h4", "h5", "h6"}
_LISTS = {"ul", "ol"}


def clean(text: str) -> str:
    """Collapse runs of whitespace into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def parse_state_page(html: str) -> ParsedPage:
    """Parse one CCHP state page."""
    soup = BeautifulSoup(html, "lxml")
    for line_break in soup.find_all("br"):
        line_break.replace_with(" ")
    problems: list[str] = []
    answers = _parse_glance(soup, problems)
    entries = _parse_entries(soup, problems)
    if not answers:
        problems.append("No 'At a Glance' answers were found.")
    if not entries:
        problems.append("No entries were found.")
    return ParsedPage(answers=answers, entries=entries, problems=problems)


def _parse_glance(soup: BeautifulSoup, problems: list[str]) -> list[GlanceAnswer]:
    answers = []
    for slide in soup.select(".atglance-slide"):
        heading = slide.find("h4")
        section = clean(heading.get_text()) if heading else ""
        if not section:
            problems.append("An 'At a Glance' group has no heading.")
        for item in slide.select(".card-content li"):
            line = clean(item.get_text())
            question, colon, answer = line.partition(":")
            if not colon or not question.strip() or not answer.strip():
                problems.append(f"At a Glance / {section}: a line is not 'Question: Answer'.")
                continue
            answers.append(
                GlanceAnswer(section=section, question=question.strip(), answer=answer.strip())
            )
    return answers


def _parse_entries(soup: BeautifulSoup, problems: list[str]) -> list[Entry]:
    entries: list[Entry] = []
    for item in soup.select(".item.has-content"):
        heading = item.select_one(".item-head h2")
        category = clean(heading.get_text()) if heading else ""
        if not category:
            problems.append("A category has no heading. Its entries were skipped.")
            continue
        for section in item.select(".item-content-section"):
            entries.extend(_parse_section(section, category, problems))
    return entries


def _parse_section(section: Tag, category: str, problems: list[str]) -> list[Entry]:
    heading = section.select_one("h2.section-head")
    topic = clean(heading.get_text()) if heading else ""
    if not topic:
        problems.append(f"{category}: a topic has no heading. Its entries were skipped.")
        return []
    reader = _SectionReader(category, topic, _last_updated(section, category, topic, problems))
    for block in _blocks(section):
        reader.feed(block)
    reader.flush()
    problems.extend(reader.problems)
    return reader.entries


def _last_updated(section: Tag, category: str, topic: str, problems: list[str]) -> date | None:
    tag = section.select_one(".last-updated")
    match = _LAST_UPDATED.search(tag.get_text()) if tag else None
    if match is None:
        problems.append(f"{category} / {topic}: no readable 'Last updated' date.")
        return None
    month, day, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        problems.append(f"{category} / {topic}: 'Last updated' is not a real date.")
        return None


def _blocks(node: Tag) -> Iterator[Tag | str]:
    """Yield the content blocks of a topic in page order, looking inside wrapper <div>s.

    Text that sits directly in the topic, outside any tag, is yielded as a plain string so
    that it is kept and not silently dropped.
    """
    for child in node.children:
        if isinstance(child, Tag):
            if child.name == "div":
                yield from _blocks(child)
            else:
                yield child
        elif not isinstance(child, Comment) and clean(str(child)):
            yield clean(str(child))


def _block_text(block: Tag | str) -> str:
    """The text of one block. List items become lines starting with a dash."""
    if isinstance(block, str):
        return block
    if block.name in _LISTS:
        items = (clean(item.get_text()) for item in block.find_all("li", recursive=False))
        return "\n".join(f"- {item}" for item in items if item)
    return clean(block.get_text())


class _SectionReader:
    """Walks the blocks of one topic and cuts them into entries."""

    def __init__(self, category: str, topic: str, last_updated: date | None) -> None:
        self.category = category
        self.topic = topic
        self.last_updated = last_updated
        self.subtopic: str | None = None
        self.pending: list[str] = []
        self.entries: list[Entry] = []
        self.problems: list[str] = []

    @property
    def place(self) -> str:
        parts = [self.category, self.topic] + ([self.subtopic] if self.subtopic else [])
        return " / ".join(parts)

    def feed(self, block: Tag | str) -> None:
        if isinstance(block, str):
            self.pending.append(block)
            return
        classes = block.get("class") or []
        if "last-updated" in classes or "section-head" in classes:
            return
        if block.name in _HEADINGS:
            self.flush()
            self.subtopic = clean(block.get_text()) or None
        elif block.name == "hr":
            self.flush()
        elif block.name == "p" and clean(block.get_text()).upper().startswith("SOURCE"):
            self._close_with_source(block)
        else:
            text = _block_text(block)
            if text:
                self.pending.append(text)

    def flush(self) -> None:
        """Turn text that was never followed by a SOURCE line into an entry of its own."""
        if not self.pending:
            return
        no_reference = any(_NO_REFERENCE.fullmatch(block) for block in self.pending)
        text = "\n".join(self.pending)
        self.pending = []
        self.entries.append(self._entry(text, no_reference_found=no_reference))

    def _close_with_source(self, block: Tag) -> None:
        if not self.pending:
            self.problems.append(f"{self.place}: a SOURCE line has no text before it.")
            return
        text = "\n".join(self.pending)
        self.pending = []
        line = _SOURCE_PREFIX.sub("", clean(block.get_text()))
        accessed = _ACCESSED.search(line)
        if accessed is None:
            self.problems.append(f"{self.place}: a SOURCE line has no readable accessed date.")
        links = _source_links(block)
        if not links:
            self.problems.append(f"{self.place}: a SOURCE line has no link.")
        self.entries.append(
            self._entry(
                text,
                source_name=_strip_accessed(line),
                source_url=links[0].url if links else None,
                source_links=links,
                accessed=clean(accessed.group(1)) if accessed else None,
            )
        )

    def _entry(self, text: str, **fields: object) -> Entry:
        return Entry(
            category=self.category,
            topic=self.topic,
            subtopic=self.subtopic,
            text=text,
            last_updated=self.last_updated,
            **fields,
        )


def _strip_accessed(text: str) -> str:
    """Remove the "(Accessed Jun. 2026)" part and the loose punctuation it leaves behind.

    The closing bracket is optional because it sometimes sits outside the link.
    """
    return _ACCESSED_LOOSE.sub("", text).strip(" .,;")


def _source_links(block: Tag) -> list[SourceLink]:
    links = []
    for anchor in block.find_all("a", href=True):
        url = str(anchor["href"]).strip()
        if url.startswith(("http://", "https://")):
            links.append(SourceLink(label=_strip_accessed(clean(anchor.get_text())), url=url))
    return links
