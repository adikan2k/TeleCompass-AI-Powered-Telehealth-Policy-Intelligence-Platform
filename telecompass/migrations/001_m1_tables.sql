-- M1 tables. Rows are only ever added, never updated.

CREATE TABLE fetch_log (
    id            bigserial PRIMARY KEY,
    host          text        NOT NULL,
    url           text        NOT NULL,
    requested_at  timestamptz NOT NULL,
    status        integer
);

CREATE INDEX fetch_log_host_time ON fetch_log (host, requested_at DESC);

CREATE TABLE snapshot (
    id            bigserial PRIMARY KEY,
    jurisdiction  text        NOT NULL,
    url           text        NOT NULL,
    fetched_at    timestamptz NOT NULL,
    sha256        text        NOT NULL,
    http_status   integer     NOT NULL,
    raw_page      text        NOT NULL
);

CREATE INDEX snapshot_jurisdiction_time ON snapshot (jurisdiction, fetched_at DESC);

CREATE TABLE parse_run (
    id              bigserial PRIMARY KEY,
    snapshot_id     bigint      NOT NULL REFERENCES snapshot (id),
    parser_version  text        NOT NULL,
    parsed_at       timestamptz NOT NULL,
    entry_count     integer     NOT NULL,
    answer_count    integer     NOT NULL,
    problems        jsonb       NOT NULL DEFAULT '[]'
);

CREATE INDEX parse_run_snapshot ON parse_run (snapshot_id, id DESC);

CREATE TABLE entry (
    id                  bigserial PRIMARY KEY,
    parse_run_id        bigint  NOT NULL REFERENCES parse_run (id),
    snapshot_id         bigint  NOT NULL REFERENCES snapshot (id),
    jurisdiction        text    NOT NULL,
    position            integer NOT NULL,
    category            text    NOT NULL,
    topic               text    NOT NULL,
    text                text    NOT NULL,
    no_reference_found  boolean NOT NULL,
    source_name         text,
    source_url          text,
    accessed            text,
    last_updated        date
);

CREATE INDEX entry_parse_run ON entry (parse_run_id, position);

CREATE TABLE glance_answer (
    id            bigserial PRIMARY KEY,
    parse_run_id  bigint  NOT NULL REFERENCES parse_run (id),
    snapshot_id   bigint  NOT NULL REFERENCES snapshot (id),
    jurisdiction  text    NOT NULL,
    position      integer NOT NULL,
    question      text    NOT NULL,
    answer        text    NOT NULL
);

CREATE INDEX glance_answer_parse_run ON glance_answer (parse_run_id, position);
