-- Every rule, with the newest human review, any retirement, and whether it is live.
-- "Live" follows the engine: the newest full run's rules, plus approved rules from later change
-- runs, minus rejected and retired ones, and (on the live site) approved only.
with newest_full as (
    select jurisdiction, max(id) as run_id
    from {{ source('pipeline', 'extraction_run') }}
    where kind = 'full'
    group by jurisdiction
),
review as (
    select distinct on (rule_id) rule_id, decision as human_decision, reviewer, reviewed_at
    from {{ source('pipeline', 'rule_review') }}
    order by rule_id, id desc
),
retired as (
    select rule_id, min(retired_on) as retired_on
    from {{ source('pipeline', 'rule_retirement') }}
    group by rule_id
)
select
    r.id as rule_id,
    r.extraction_run_id,
    run.kind as run_kind,
    r.entry_id,
    r.jurisdiction,
    r.rule_type,
    r.aspect,
    r.effect,
    r.summary,
    r.quote,
    r.quote_verified,
    r.source_text_id,
    r.source_url,
    r.effective_from,
    r.effective_to,
    review.human_decision,
    review.reviewer,
    review.reviewed_at,
    retired.retired_on,
    (
        r.quote_verified
        and r.effect <> 'silent'
        and retired.rule_id is null
        and coalesce(review.human_decision, '') = 'approved'
        and (run.kind = 'full' and r.extraction_run_id = nf.run_id
             or run.kind = 'change' and r.extraction_run_id > nf.run_id)
    ) as is_live
from {{ source('pipeline', 'rule') }} r
join {{ source('pipeline', 'extraction_run') }} run on run.id = r.extraction_run_id
left join newest_full nf on nf.jurisdiction = r.jurisdiction
left join review on review.rule_id = r.id
left join retired on retired.rule_id = r.id
