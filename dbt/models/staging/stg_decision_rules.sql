-- One row per rule a stored decision rested on.
select
    d.id as decision_id,
    d.public_id,
    d.visit_date,
    d.created_at as decided_at,
    unnest(d.rule_ids) as rule_id
from {{ source('pipeline', 'decision') }} d
