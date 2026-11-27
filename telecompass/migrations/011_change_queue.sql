-- M5: the change agent's proposals and the decisions a person makes on them. Rows are added only.

-- A full run reads every in-scope entry; a change run reads only the entries a diff found new or
-- changed, and its rules are used only once a person approves them.
ALTER TABLE extraction_run ADD COLUMN kind text NOT NULL DEFAULT 'full'
    CHECK (kind IN ('full', 'change'));
ALTER TABLE extraction_run ADD COLUMN diff_run_id bigint REFERENCES diff_run (id);

-- One thing the agent proposes after reading a change.
--   add           a new rule, not already live
--   retire        a live rule whose entry was removed or no longer supports it
--   already_live  a rule read again that matches one already live: nothing to do
--   unreadable    the law the entry cites could not be read
--   no_rules      the law was read and holds no rule on the point
CREATE TABLE change_proposal (
    id               bigserial PRIMARY KEY,
    diff_run_id      bigint      NOT NULL REFERENCES diff_run (id),
    entry_change_id  bigint      NOT NULL REFERENCES entry_change (id),
    kind             text        NOT NULL
        CHECK (kind IN ('add', 'retire', 'already_live', 'unreadable', 'no_rules')),
    rule_id          bigint      REFERENCES rule (id),
    matched_rule_id  bigint      REFERENCES rule (id),
    note             text,
    thread_id        text        NOT NULL,
    created_at       timestamptz NOT NULL
);

CREATE INDEX change_proposal_diff ON change_proposal (diff_run_id, id);

-- A person's decision on a proposal. The newest decision on a proposal is the one in effect.
CREATE TABLE change_decision (
    id           bigserial PRIMARY KEY,
    proposal_id  bigint      NOT NULL REFERENCES change_proposal (id),
    decision     text        NOT NULL CHECK (decision IN ('approved', 'rejected')),
    note         text,
    reviewer     text        NOT NULL,
    decided_at   timestamptz NOT NULL
);

CREATE INDEX change_decision_proposal ON change_decision (proposal_id, id DESC);

-- A live rule that stops being used, from a given date, because a person approved retiring it.
CREATE TABLE rule_retirement (
    id           bigserial PRIMARY KEY,
    rule_id      bigint      NOT NULL REFERENCES rule (id),
    proposal_id  bigint      REFERENCES change_proposal (id),
    retired_on   date        NOT NULL,
    reviewer     text        NOT NULL,
    recorded_at  timestamptz NOT NULL
);

-- A person's confirmation that an official copy is the same document as a blocked citation (D7).
CREATE TABLE override_confirmation (
    id            bigserial PRIMARY KEY,
    cited_url     text        NOT NULL,
    official_url  text        NOT NULL,
    confirmed_by  text        NOT NULL,
    confirmed_at  timestamptz NOT NULL
);
