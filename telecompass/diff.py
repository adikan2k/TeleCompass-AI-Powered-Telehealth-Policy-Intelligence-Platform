"""What changed between two parsed snapshots of the same page (D20).

Entries are matched by their place on the page: category, topic, sub-heading, and their order
under that heading. Plain code, no model: the same two snapshots always give the same diff.
"""

import re
from collections import defaultdict
from datetime import datetime

from psycopg.types.json import Jsonb
from pydantic import BaseModel

from telecompass import store
from telecompass.db import Connection
from telecompass.models import StoredEntry
from telecompass.scope import rule_type_for

ADDED, REMOVED, CHANGED, REWORDED, RECHECKED = (
    "added",
    "removed",
    "changed",
    "reworded",
    "rechecked",
)
SUBSTANTIVE = (ADDED, REMOVED, CHANGED)
_FILLER = {"the", "a", "an"}


def gist(text: str) -> str:
    """Text reduced to its words: lower case, no punctuation, no "the", "a" or "an".

    Two entries with the same gist and the same sources say the same thing in other words.
    """
    words = re.findall(r"[a-z0-9]+", text.lower())
    return " ".join(word for word in words if word not in _FILLER)


# Fields whose change alters what an entry says. A change only in `accessed` or `last_updated`
# means CCHP looked again without changing the substance: "rechecked".
SUBSTANCE = ("text", "no_reference_found", "source_name", "links")
STAMPS = ("accessed", "last_updated")


class EntryChange(BaseModel):
    kind: str
    category: str
    topic: str
    subtopic: str | None
    rule_type: str | None
    old: StoredEntry | None
    new: StoredEntry | None
    fields: list[str]


def _key(entry: StoredEntry) -> tuple[str, str, str]:
    return (entry.category, entry.topic, entry.subtopic or "")


def _value(entry: StoredEntry, field: str) -> object:
    if field == "links":
        return sorted(link.url for link in entry.source_links)
    if field == "text":
        return " ".join(entry.text.split())
    return getattr(entry, field)


def _changed_fields(old: StoredEntry, new: StoredEntry) -> list[str]:
    return [f for f in (*SUBSTANCE, *STAMPS) if _value(old, f) != _value(new, f)]


def diff_entries(old: list[StoredEntry], new: list[StoredEntry]) -> list[EntryChange]:
    """Every entry added, removed, changed or only rechecked, in the new page's order."""
    old_by_key: dict[tuple, list[StoredEntry]] = defaultdict(list)
    for entry in old:
        old_by_key[_key(entry)].append(entry)
    new_by_key: dict[tuple, list[StoredEntry]] = defaultdict(list)
    for entry in new:
        new_by_key[_key(entry)].append(entry)

    changes: list[EntryChange] = []

    def change(kind: str, a: StoredEntry | None, b: StoredEntry | None, fields: list[str]):
        entry = b or a
        assert entry is not None
        changes.append(
            EntryChange(
                kind=kind,
                category=entry.category,
                topic=entry.topic,
                subtopic=entry.subtopic,
                rule_type=rule_type_for(entry.category, entry.topic),
                old=a,
                new=b,
                fields=fields,
            )
        )

    for key in list(dict.fromkeys([*new_by_key, *old_by_key])):
        olds, news = old_by_key.get(key, []), new_by_key.get(key, [])
        # Pair same-text entries first, so an inserted paragraph does not shift every pairing.
        remaining_old = list(olds)
        pairs: list[tuple[StoredEntry | None, StoredEntry | None]] = []
        unmatched_new = []
        for b in news:
            same = next((a for a in remaining_old if _value(a, "text") == _value(b, "text")), None)
            if same is not None:
                remaining_old.remove(same)
                pairs.append((same, b))
            else:
                unmatched_new.append(b)
        for b in unmatched_new:
            pairs.append((remaining_old.pop(0) if remaining_old else None, b))
        pairs += [(a, None) for a in remaining_old]
        for a, b in pairs:
            if a is None:
                change(ADDED, None, b, [])
            elif b is None:
                change(REMOVED, a, None, [])
            else:
                fields = _changed_fields(a, b)
                substance = [f for f in fields if f in SUBSTANCE]
                if substance == ["text"] and gist(a.text) == gist(b.text):
                    change(REWORDED, a, b, fields)
                elif substance:
                    change(CHANGED, a, b, fields)
                elif fields:
                    change(RECHECKED, a, b, fields)
    order = {entry.id: i for i, entry in enumerate(new)}
    changes.sort(key=lambda c: order.get(c.new.id, len(order)) if c.new else len(order))
    return changes


def save_diff(
    conn: Connection, jurisdiction: str, old_run: int, new_run: int, at: datetime
) -> tuple[int, list[EntryChange]]:
    """Diff two parse runs, store the result, and return its id with the changes."""
    changes = diff_entries(
        store.stored_entries_for(conn, old_run), store.stored_entries_for(conn, new_run)
    )
    row = conn.execute(
        "INSERT INTO diff_run (jurisdiction, old_parse_run_id, new_parse_run_id, created_at) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (jurisdiction, old_run, new_run, at),
    ).fetchone()
    for item in changes:
        conn.execute(
            "INSERT INTO entry_change (diff_run_id, kind, category, topic, subtopic, rule_type, "
            "old_entry_id, new_entry_id, fields) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                row["id"],
                item.kind,
                item.category,
                item.topic,
                item.subtopic,
                item.rule_type,
                item.old.id if item.old else None,
                item.new.id if item.new else None,
                Jsonb(item.fields),
            ),
        )
    conn.commit()
    return row["id"], changes
