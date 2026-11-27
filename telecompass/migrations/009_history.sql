-- M5: snapshots over time, and the differences between them.

-- Where a snapshot came from, and the moment its content represents. For our own fetches that
-- is the fetch time; for a copy from the Internet Archive it is the Archive's capture time.
ALTER TABLE snapshot ADD COLUMN origin text NOT NULL DEFAULT 'live'
    CHECK (origin IN ('live', 'wayback'));
ALTER TABLE snapshot ADD COLUMN captured_at timestamptz;
UPDATE snapshot SET captured_at = fetched_at WHERE captured_at IS NULL;
ALTER TABLE snapshot ALTER COLUMN captured_at SET NOT NULL;

-- One comparison of two parsed snapshots of the same jurisdiction.
CREATE TABLE diff_run (
    id                 bigserial PRIMARY KEY,
    jurisdiction       text        NOT NULL,
    old_parse_run_id   bigint      NOT NULL REFERENCES parse_run (id),
    new_parse_run_id   bigint      NOT NULL REFERENCES parse_run (id),
    created_at         timestamptz NOT NULL
);

-- One difference between the two: an entry added, removed or changed.
CREATE TABLE entry_change (
    id              bigserial PRIMARY KEY,
    diff_run_id     bigint  NOT NULL REFERENCES diff_run (id),
    kind            text    NOT NULL CHECK (kind IN ('added', 'removed', 'changed', 'rechecked')),
    category        text    NOT NULL,
    topic           text    NOT NULL,
    subtopic        text,
    rule_type       text,
    old_entry_id    bigint  REFERENCES entry (id),
    new_entry_id    bigint  REFERENCES entry (id),
    fields          jsonb   NOT NULL DEFAULT '[]'
);

CREATE INDEX entry_change_run ON entry_change (diff_run_id, id);

-- A cited document that read differently at two fetches.
CREATE TABLE source_change (
    id                   bigserial PRIMARY KEY,
    url                  text        NOT NULL,
    old_source_text_id   bigint      NOT NULL REFERENCES source_text (id),
    new_source_text_id   bigint      NOT NULL REFERENCES source_text (id),
    detected_at          timestamptz NOT NULL
);
