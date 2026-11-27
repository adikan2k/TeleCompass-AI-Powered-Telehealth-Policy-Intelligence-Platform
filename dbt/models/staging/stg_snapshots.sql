-- Every stored page, with where it came from and the moment its content represents.
select
    id as snapshot_id,
    jurisdiction,
    url,
    origin,
    captured_at,
    fetched_at,
    sha256
from {{ source('pipeline', 'snapshot') }}
