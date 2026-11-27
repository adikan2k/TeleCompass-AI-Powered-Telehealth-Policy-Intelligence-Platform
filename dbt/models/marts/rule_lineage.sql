-- From each rule to the exact words of the law, the page that pointed to it, and the snapshot
-- of that page: the chain a reader follows to check a rule.
select
    r.rule_id,
    r.jurisdiction,
    r.rule_type,
    r.effect,
    r.summary,
    r.quote,
    r.quote_verified,
    r.is_live,
    r.human_decision,
    r.reviewer,
    st.id as source_text_id,
    st.url as cited_url,                               -- the link the policy page gives
    coalesce(st.final_url, st.fetch_url, st.url) as source_url,  -- the document actually read
    (st.fetch_url is distinct from st.url) as read_from_official_copy,
    st.fetched_at as source_fetched_at,
    st.sha256 as source_sha256,
    e.entry_id,
    e.category,
    e.topic,
    e.subtopic,
    s.snapshot_id,
    s.origin as snapshot_origin,
    s.captured_at as snapshot_captured_at,
    s.sha256 as snapshot_sha256
from {{ ref('stg_rules') }} r
left join {{ source('pipeline', 'source_text') }} st on st.id = r.source_text_id
join {{ ref('stg_entries') }} e on e.entry_id = r.entry_id
join {{ ref('stg_snapshots') }} s on s.snapshot_id = e.snapshot_id
