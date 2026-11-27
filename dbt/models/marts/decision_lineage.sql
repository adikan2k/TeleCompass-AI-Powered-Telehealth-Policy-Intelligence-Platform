-- From each stored answer to every rule it used, and on to the law and the snapshot.
select
    d.decision_id,
    d.public_id,
    d.visit_date,
    d.decided_at,
    l.*
from {{ ref('stg_decision_rules') }} d
join {{ ref('rule_lineage') }} l on l.rule_id = d.rule_id
