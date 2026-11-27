-- M3: rules can be limited to behavioral health or other care, and every decision is stored.

ALTER TABLE rule ADD COLUMN service_category text NOT NULL DEFAULT 'any';

-- One row per preflight: the visit asked about, the answer, and the rules it rested on.
-- A visit is invented or typed by a user and never holds a name or a date of birth (rule 17).
CREATE TABLE decision (
    id          bigserial PRIMARY KEY,
    visit       jsonb       NOT NULL,
    visit_date  date        NOT NULL,
    answer      jsonb       NOT NULL,
    rule_ids    bigint[]    NOT NULL,
    created_at  timestamptz NOT NULL
);
