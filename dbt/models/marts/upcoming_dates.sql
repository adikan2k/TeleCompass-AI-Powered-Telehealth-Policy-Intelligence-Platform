-- Live rules that start or end on a stated date: what is about to change on its own.
select rule_id, jurisdiction, rule_type, aspect, effect, summary, 'ends' as event,
       effective_to as on_date
from {{ ref('stg_rules') }}
where is_live and effective_to is not null
union all
select rule_id, jurisdiction, rule_type, aspect, effect, summary, 'starts' as event,
       effective_from as on_date
from {{ ref('stg_rules') }}
where is_live and effective_from is not null
