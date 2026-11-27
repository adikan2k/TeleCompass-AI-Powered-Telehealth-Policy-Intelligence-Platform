# Decisions

## Summary

The decisions that mattered, newest last. Details are in the entries below.

| # | Decision | Date | Status |
|---|---|---|---|
| D1 | Flat `telecompass/` Python package at the repo root, hatchling build, uv for the environment | 2026-11-26 | Approved by Aditya |
| D2 | CCHP has no `robots.txt` (404). Fetching is not forbidden by robots rules; terms of use still to be read before M1 | 2026-11-26 | Approved by Aditya |
| D3 | CCHP's terms of use are referenced but not published where we could find them. Fetch Florida once under our own strict limits; Aditya may write to CCHP | 2026-11-26 | Approved by Aditya |
| D4 | Postgres through psycopg 3 and plain SQL migration files. Local Postgres in Docker for now, Neon when the site goes live. Tests use a throwaway Postgres container | 2026-11-26 | Approved by Aditya |
| D5 | Fetcher: httpx, robots check on every run, one request at a time with a 10 second wait, refuses a second fetch of a page it already holds | 2026-11-26 | Approved by Aditya |
| D6 | Parser: BeautifulSoup, written against the stored snapshot, tested on an invented page. `show` prints short excerpts only | 2026-11-26 | Approved by Aditya |

Open items:

- CCHP's terms of use: not found on the site (see D3). Aditya to decide whether to ask CCHP.
- The fetcher re-checks `robots.txt` at the start of every run, in case one appears.
- Create the Neon project and move the database there before the site goes live in M4.

---

## D1. Python package layout and tooling

**What.** The Python code lives in a flat `telecompass/` package at the repo root. It is built
with hatchling. uv manages the virtual environment and writes `uv.lock`. Dev tools are `pytest`
and `ruff`, listed under the `dev` extra in `pyproject.toml`. The version is written once, in
`telecompass/__init__.py`, and the build reads it from there.

**Why.** `docs/PLAN.md` names the package `telecompass/`. uv was already installed, and a lock
file makes every install the same. The package asks for Python 3.11 or newer and uv picks an
interpreter that fits (3.13 on the first run). One place for the version means the
package and its metadata cannot disagree, and the first test checks exactly that.

**Considered.**

- A `src/telecompass/` layout. It stops tests from importing the folder by accident instead of
  the installed package, but adds a directory level the plan does not ask for.
- Plain `pip` with a hand-made venv. Fewer tools, but no lock file. It still works:
  `pip install -e ".[dev]"`.

**Trade-off.** The Python package sits beside the old Next.js folders (`app/`, `components/`,
`lib/`) at the root until the site is rebuilt in M4.

## D2. CCHP robots.txt

**What was checked.** `https://www.cchpca.org/robots.txt`, requested twice about 15 seconds
apart with an unmodified `curl/8.9.0` client.

| Field | Value |
|---|---|
| Fetched at | 2026-11-27T03:48:35Z and 2026-11-27T03:48:50Z |
| Status | `404 Not Found` both times, no redirects |
| Server | `nginx/1.30.7` |
| Body | The stock nginx 404 page, 153 bytes, `text/html` |
| SHA-256 of body | `29b8ea7cf7286595bdce7f04d1ed55b2670cffc86ffe6e4917f6667f6b595cdb` |

**Finding.** The site has no `robots.txt`. Under the robots standard (RFC 9309, section 2.3.1.3)
a 4xx answer means the file is unavailable and no crawl rules are stated. So robots rules do not
forbid fetching any path on `www.cchpca.org`. There is also no stated crawl delay, so we set our
own.

**What this does not mean.**

- It is not permission to republish. CCHP's text is copyrighted and rule 15 in `CLAUDE.md`
  stands: store it for processing, show at most a short excerpt with a link back.
- It does not relax rule 14: one request at a time with a wait, an honest fetcher identity, raw
  pages stored with a hash and a fetch time.
- It says nothing about the site's terms of use. Those have not been read yet.

**Considered.** Treating a missing file as "do not fetch". The standard says otherwise, and the
real limits on this project come from copyright and the terms of use, which are handled
separately.

**Trade-off.** The check is a single point in time from one client. The file could be added
later, so the M1 fetcher must check again on every run and stop if it finds a rule against the
path it is about to fetch.

## D3. CCHP terms of use

**What was checked.** On 2026-11-27 between 03:56 and 03:58 UTC, four requests with an
unmodified `curl/8.9.0` client: `robots.txt` (still 404), the home page, the privacy policy page
and one try at `/terms-of-use/`.

**Finding.**

- The privacy policy says that using the site means agreeing to "our terms of use".
- No terms of use page is linked from the home page, the footer or the privacy policy. The
  conventional address `/terms-of-use/` returns 404. So the terms could not be read.
- The footer carries a copyright notice: Public Health Institute / Center for Connected Health
  Policy, 2010 to 2026.
- The home page's robots meta tag is `index, follow`. Nothing found forbids automated reading.

**Decision.** Go ahead with one fetch of the Florida page, under limits stricter than anything
the site states: one page, one request, an honest fetcher name, the raw page kept in our own
database and never in the public repository, and nothing shown beyond a short excerpt with a
link back (rule 15).

**Considered.**

- Holding all fetching until CCHP answers an email. Safest, but it blocks M1 for an unknown
  time over a single page that any visitor can open.
- Guessing more addresses for the terms page. Not done: probing a site for unlinked pages is
  poor manners and proves little.

**Trade-off.** We act without having read terms the site says exist. If CCHP later publishes or
sends terms that forbid this use, we stop fetching and delete the stored snapshots.

**For Aditya.** Writing to `info@cchpca.org` to describe the project and ask for the terms is
yours to do. It is not required for M1.

## D4. Database and how it is tested

**What.** Postgres, reached with psycopg 3 and plain SQL. The schema lives in numbered files
under `telecompass/migrations/` and a small runner applies the ones not yet applied. M1 adds
three tables:

- `snapshot`: jurisdiction, url, fetched_at, sha256, http status, raw page.
- `entry`: snapshot id, jurisdiction, category, topic, text, source name, source url, accessed,
  last_updated.
- `glance_answer`: snapshot id, jurisdiction, question, answer. This is the answer key. It is
  not in the plan's table list and is added here.

Rows are only ever added. A new snapshot gets new entry rows that point at it.

Two small tables were added while building, after approval, and are flagged to Aditya:

- `fetch_log`: site, url, time and status of every request made. The wait between requests is
  worked out from this table, because rule 21 says rate counters live in the database.
- `parse_run`: snapshot id, parser version, time and counts. `entry` and `glance_answer` rows
  point at the parse run that made them, so a fixed parser adds a new run and never rewrites
  old rows. `show` reads the newest run.

The local database has no password. It listens on `127.0.0.1` only, so there is no secret to
keep or to leak.

For now the database is Postgres in Docker on Aditya's machine, started from a
`docker-compose.yml` in the repo (the pgvector image, so M2 needs no change). `DATABASE_URL`
comes from the environment. The code loads the project's `.env` into the environment at start
with python-dotenv and never prints it. Neon replaces the local database before M4.

Tests that need a database start a throwaway Postgres container with testcontainers and remove
it afterwards. If Docker is not running those tests fail with a clear message. They are not
skipped.

**Why.** Plain SQL is the easiest thing to read and to explain, and dbt will work over the same
tables in M5. A real Postgres in tests means the tests exercise the same database engine as
production. Docker is already installed and running; `DATABASE_URL` is not set and there is no
Neon project yet, and creating that account is Aditya's step.

**Considered.**

- SQLAlchemy or SQLModel. More to learn and explain for three tables.
- SQLite for tests. Fast, but it is a different database, and pgvector and full-text search
  cannot be tested on it later.
- Neon from day one. Matches the plan's end state, but M1 would wait on an account and every
  test run would need the network.

**Trade-off.** Docker must be running for the database tests and for local use. The move to
Neon is a later step that must not be forgotten; it is listed under open items.

## D5. Fetcher

**What.** One module, `telecompass/fetch.py`, using httpx.

- Before any page it requests the site's `robots.txt`. 404 means no rules. A rule against the
  path, or a server error, means stop and tell Aditya.
- One request at a time per site, with at least 10 seconds between requests to the same site.
- It sends this User-Agent: `TeleCompass/0.1 (+<repository URL>)`. No email address.
- It stores the raw page, its SHA-256, the status and the fetch time in `snapshot` before
  anything is parsed.
- If a snapshot of that page already exists it refuses to fetch again unless `--force` is
  given. This is what keeps "fetch Florida once" true.
- The fetched page is treated as untrusted data (rule 16). Nothing in it is run or followed.

Command: `python -m telecompass fetch florida`, which requests `https://www.cchpca.org/florida/`.

**Why.** Rule 14, written as code that can be tested instead of as a habit.

**Considered.** `requests` (httpx gives the same API with timeouts that are harder to forget,
and async later if wanted). A scraping framework such as Scrapy (far more than one page needs).

**Trade-off.** The User-Agent names the project and its public repository, which is what makes
it honest and also what makes it traceable to Aditya. He approves the exact string.

**Not known yet.** Whether the one Florida page holds every entry, or only summaries with the
full entries on per-topic pages. If it is the second, work stops after the first fetch and comes
back to Aditya before any further page is requested.

## D6. Parser and the show command

**What.**

- `telecompass/parse_cchp.py` turns the stored page into typed pydantic models with
  BeautifulSoup: the "At a Glance" answers, and the entries with category, topic, text, SOURCE
  line (name, link, month accessed) and last-updated date. It reads from the `snapshot` table
  and never from the network.
- An entry marked "No Reference Found" is kept as its own row and flagged, not dropped.
- Anything the parser cannot place is counted and reported. It does not guess.
- `python -m telecompass show florida` prints the answer key and the entries: category, topic,
  the first 200 characters of the text, the SOURCE line and dates, and the link back to CCHP.
  It ends with "Not legal advice" and the fetch date (rule 18).
- The command line uses argparse from the standard library.

**Why.** The parser is written against the real stored page, so it is built on what the site
actually sends. Short excerpts keep `show` inside rule 15 even in a terminal.

**Considered.**

- Committing the real Florida page as the test fixture. Not done: that would republish CCHP's
  text in a public repository. The test fixture is an invented page with the same structure.
- selectolax (faster, less widely known) and typer or click for the command line (nicer help
  text, one more dependency).

**Trade-off.** An invented fixture can drift from the real page. To cover that, one extra test
runs the parser over the stored snapshot when a database is present and checks the counts.

**No model calls in M1.** So there is nothing to trace in Langfuse and no cost cap to set yet
(rule 20).
