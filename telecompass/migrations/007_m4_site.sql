-- M4: share links for decisions, and request counters for the public site.

-- A random id used in share links, so stored decisions cannot be walked through by number.
ALTER TABLE decision ADD COLUMN public_id text;
CREATE UNIQUE INDEX decision_public_id ON decision (public_id) WHERE public_id IS NOT NULL;

-- Requests per day, per visitor and for the whole site (rule 21). `key` never holds an
-- address: a visitor is a one-way hash of their address and the day.
CREATE TABLE rate_counter (
    day    date    NOT NULL,
    key    text    NOT NULL,
    count  integer NOT NULL,
    PRIMARY KEY (day, key)
);
