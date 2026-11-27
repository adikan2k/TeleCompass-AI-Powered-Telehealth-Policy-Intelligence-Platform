-- A rule made by a change run was read from an entry of that diff's newer snapshot.
select r.id as rule_id
from {{ source('pipeline', 'rule') }} r
join {{ source('pipeline', 'extraction_run') }} run on run.id = r.extraction_run_id
join {{ source('pipeline', 'diff_run') }} d on d.id = run.diff_run_id
join {{ source('pipeline', 'entry') }} e on e.id = r.entry_id
where run.kind = 'change' and e.parse_run_id <> d.new_parse_run_id
