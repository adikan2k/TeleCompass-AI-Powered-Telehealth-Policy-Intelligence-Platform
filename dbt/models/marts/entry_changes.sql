-- Every real change found between two snapshots, with its dates and what a person decided.
with proposals as (
    select
        p.entry_change_id,
        count(*) filter (where p.kind = 'add') as rules_proposed,
        count(*) filter (where p.kind = 'retire') as retirements_proposed,
        count(*) filter (where p.kind = 'add' and dec.decision = 'approved') as rules_approved,
        count(*) filter (where p.kind = 'retire' and dec.decision = 'approved') as rules_retired,
        count(*) filter (where p.kind = 'unreadable') as unreadable
    from {{ source('pipeline', 'change_proposal') }} p
    left join lateral (
        select decision from {{ source('pipeline', 'change_decision') }} c
        where c.proposal_id = p.id order by c.id desc limit 1
    ) dec on true
    group by p.entry_change_id
)
select
    c.id as entry_change_id,
    d.id as diff_run_id,
    d.jurisdiction,
    so.captured_at as old_captured_at,
    so.origin as old_origin,
    sn.captured_at as new_captured_at,
    sn.origin as new_origin,
    c.kind,
    c.category,
    c.topic,
    c.subtopic,
    c.rule_type,
    c.fields,
    coalesce(p.rules_proposed, 0) as rules_proposed,
    coalesce(p.rules_approved, 0) as rules_approved,
    coalesce(p.retirements_proposed, 0) as retirements_proposed,
    coalesce(p.rules_retired, 0) as rules_retired,
    coalesce(p.unreadable, 0) as unreadable
from {{ source('pipeline', 'entry_change') }} c
join {{ source('pipeline', 'diff_run') }} d on d.id = c.diff_run_id
join {{ source('pipeline', 'parse_run') }} ro on ro.id = d.old_parse_run_id
join {{ ref('stg_snapshots') }} so on so.snapshot_id = ro.snapshot_id
join {{ source('pipeline', 'parse_run') }} rn on rn.id = d.new_parse_run_id
join {{ ref('stg_snapshots') }} sn on sn.snapshot_id = rn.snapshot_id
left join proposals p on p.entry_change_id = c.id
where c.kind in ('added', 'removed', 'changed')
