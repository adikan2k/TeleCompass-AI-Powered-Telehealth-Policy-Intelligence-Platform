-- Every rule a stored answer rested on exists.
select d.decision_id, d.rule_id
from {{ ref('stg_decision_rules') }} d
left join {{ ref('stg_rules') }} r on r.rule_id = d.rule_id
where r.rule_id is null
