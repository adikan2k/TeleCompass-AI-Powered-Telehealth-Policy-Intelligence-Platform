-- Every parsed entry, tied to its parse run and its snapshot.
select
    e.id as entry_id,
    e.parse_run_id,
    e.snapshot_id,
    e.jurisdiction,
    e.category,
    e.topic,
    e.subtopic,
    e.no_reference_found,
    e.source_name,
    e.last_updated
from {{ source('pipeline', 'entry') }} e
