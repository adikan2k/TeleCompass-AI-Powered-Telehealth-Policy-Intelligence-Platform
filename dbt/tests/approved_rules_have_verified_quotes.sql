-- A person may only approve a rule whose quote was found word for word in the law (rule 10).
select rule_id from {{ ref('stg_rules') }}
where human_decision = 'approved' and effect <> 'silent' and not quote_verified
