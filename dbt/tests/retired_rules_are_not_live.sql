-- A rule a person retired is never live.
select rule_id from {{ ref('stg_rules') }} where retired_on is not null and is_live
