-- Every live rule leads to stored law text and to the snapshot of the page that cited it.
select rule_id from {{ ref('rule_lineage') }}
where is_live and (source_text_id is null or snapshot_id is null or quote is null)
