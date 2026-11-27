-- A person's approval or rejection of a rule (rule 13). Rows are only added: a later review
-- of the same rule replaces the earlier one in effect, and both stay on record. The rule
-- itself is never changed.

CREATE TABLE rule_review (
    id           bigserial PRIMARY KEY,
    rule_id      bigint      NOT NULL REFERENCES rule (id),
    decision     text        NOT NULL CHECK (decision IN ('approved', 'rejected')),
    note         text,
    reviewer     text        NOT NULL,
    reviewed_at  timestamptz NOT NULL
);

CREATE INDEX rule_review_rule ON rule_review (rule_id, id DESC);
