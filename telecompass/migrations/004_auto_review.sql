-- An automated second look at each rule by a different model than the one that wrote it.
-- Kept apart from `label`, which holds human judgements only.

CREATE TABLE auto_review (
    id                   bigserial PRIMARY KEY,
    run_id               bigint      NOT NULL REFERENCES extraction_run (id),
    rule_id              bigint      NOT NULL REFERENCES rule (id),
    model                text        NOT NULL,
    verdict              text        NOT NULL CHECK (verdict IN ('right', 'wrong', 'cannot_tell')),
    quote_in_source      boolean     NOT NULL,
    rule_matches_source  boolean     NOT NULL,
    reason               text        NOT NULL,
    reviewed_at          timestamptz NOT NULL
);

CREATE INDEX auto_review_rule ON auto_review (rule_id, id DESC);
