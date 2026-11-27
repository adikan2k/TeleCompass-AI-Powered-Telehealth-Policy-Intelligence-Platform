-- M2 tables: the law as fetched, model calls and their cost, rules, and labels.
-- Rows are only ever added.

-- One row per attempt to get a cited document. The newest row for a url is its current state.
CREATE TABLE source_text (
    id            bigserial PRIMARY KEY,
    url           text        NOT NULL,   -- the link exactly as CCHP cites it
    fetch_url     text        NOT NULL,   -- what we actually asked for (a confirmed official copy, or the same)
    final_url     text,                   -- where the document was finally read from
    fetched_at    timestamptz NOT NULL,
    outcome       text        NOT NULL CHECK (outcome IN ('fetched', 'forbidden', 'failed', 'unreadable')),
    http_status   integer,
    content_type  text,
    sha256        text,
    raw_body      bytea,
    text          text,                   -- plain text taken from the body; quotes are checked against this
    note          text
);

CREATE INDEX source_text_url ON source_text (url, id DESC);

CREATE TABLE extraction_run (
    id            bigserial PRIMARY KEY,
    jurisdiction  text          NOT NULL,
    parse_run_id  bigint        NOT NULL REFERENCES parse_run (id),
    model         text          NOT NULL,
    cap_usd       numeric(10,4) NOT NULL,
    started_at    timestamptz   NOT NULL
);

-- Every model call, with its cost. The spend cap is worked out from this table (rule 21).
CREATE TABLE model_call (
    id                  bigserial PRIMARY KEY,
    run_id              bigint        NOT NULL REFERENCES extraction_run (id),
    purpose             text          NOT NULL,
    entry_id            bigint        REFERENCES entry (id),
    model               text          NOT NULL,
    input_tokens        integer       NOT NULL,
    cached_tokens       integer       NOT NULL,
    cache_write_tokens  integer       NOT NULL,
    output_tokens       integer       NOT NULL,
    cost_usd            numeric(12,6) NOT NULL,
    started_at          timestamptz   NOT NULL,
    seconds             real          NOT NULL,
    failure             text,
    response_id         text
);

CREATE INDEX model_call_run ON model_call (run_id);

-- What happened to each in-scope entry in a run, including the ones that produced no rule.
CREATE TABLE extraction_item (
    id          bigserial PRIMARY KEY,
    run_id      bigint  NOT NULL REFERENCES extraction_run (id),
    entry_id    bigint  NOT NULL REFERENCES entry (id),
    rule_type   text    NOT NULL,
    outcome     text    NOT NULL,
    source_cut  boolean NOT NULL DEFAULT false,
    note        text
);

CREATE INDEX extraction_item_run ON extraction_item (run_id, id);

CREATE TABLE rule (
    id                 bigserial PRIMARY KEY,
    extraction_run_id  bigint      NOT NULL REFERENCES extraction_run (id),
    entry_id           bigint      NOT NULL REFERENCES entry (id),
    jurisdiction       text        NOT NULL,
    rule_type          text        NOT NULL,
    aspect             text        NOT NULL,
    effect             text        NOT NULL CHECK (effect IN ('allow', 'deny', 'require', 'silent')),
    profession         text,
    payer              text,
    modality           text,
    service            text,
    compact            text,
    conditions         jsonb       NOT NULL DEFAULT '[]',
    summary            text        NOT NULL,
    quote              text,
    quote_verified     boolean     NOT NULL,
    quote_note         text,
    source_text_id     bigint      REFERENCES source_text (id),
    source_url         text,
    source_fetched_at  timestamptz,
    effective_from     date,
    effective_to       date,
    status             text        NOT NULL CHECK (status IN ('draft', 'unverified', 'approved')),
    approved_by        text,
    approved_at        timestamptz,
    created_at         timestamptz NOT NULL
);

CREATE INDEX rule_run ON rule (extraction_run_id, id);

-- The fixed sample of rules a person labels, and the labels. Only the labelling page writes labels.
CREATE TABLE label_sample (
    id          bigserial PRIMARY KEY,
    run_id      bigint      NOT NULL REFERENCES extraction_run (id),
    position    integer     NOT NULL,
    rule_id     bigint      NOT NULL REFERENCES rule (id),
    seed        integer     NOT NULL,
    created_at  timestamptz NOT NULL,
    UNIQUE (run_id, position)
);

CREATE TABLE label (
    id           bigserial PRIMARY KEY,
    run_id       bigint      NOT NULL REFERENCES extraction_run (id),
    rule_id      bigint      NOT NULL REFERENCES rule (id),
    verdict      text        NOT NULL CHECK (verdict IN ('right', 'wrong', 'cannot_tell')),
    note         text,
    labeller     text        NOT NULL,
    labelled_at  timestamptz NOT NULL
);

CREATE INDEX label_rule ON label (rule_id, id DESC);
