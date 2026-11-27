# Decisions

## Summary

The decisions that mattered, newest last. Details are in the entries below.

| # | Decision | Date | Status |
|---|---|---|---|
| D1 | Flat `telecompass/` Python package at the repo root, hatchling build, uv for the environment | 2026-11-26 | Approved by Aditya |
| D2 | CCHP has no `robots.txt` (404). Fetching is not forbidden by robots rules; terms of use still to be read before M1 | 2026-11-26 | Approved by Aditya |
| D3 | CCHP's terms of use are referenced but not published where we could find them. Fetch Florida once under our own strict limits. Aditya decided not to write to CCHP | 2026-11-26 | Approved by Aditya |
| D4 | Postgres through psycopg 3 and plain SQL migration files. Local Postgres in Docker for now, Neon when the site goes live. Tests use a throwaway Postgres container | 2026-11-26 | Approved by Aditya |
| D5 | Fetcher: httpx, robots check on every run, one request at a time with a 10 second wait, refuses a second fetch of a page it already holds | 2026-11-26 | Approved by Aditya |
| D6 | Parser: BeautifulSoup, written against the stored snapshot, tested on an invented page. `show` prints short excerpts only | 2026-11-26 | Approved by Aditya |
| D7 | Fetch the law each Florida entry cites, only from sites whose robots.txt allows it. Two sites forbid it, so 11 entries get no rules and are reported as a gap | 2026-11-26 | Approved by Aditya |
| D8 | Rule schema and extraction: `gpt-6.2-sol` with structured outputs reads the law into typed rules. Code, not the model, checks every quote and sets every status | 2026-11-26 | Approved by Aditya |
| D9 | One model client: every call counted in the database, a hard cost cap per run (5 US dollars for Florida), every call traced in Langfuse, no run without Langfuse keys | 2026-11-26 | Approved by Aditya |
| D10 | Grade: plain Python turns rules into yes or no for the 10 answer-key lines that the five rule types cover, and writes `evals/results/extraction_florida.json` | 2026-11-26 | Approved by Aditya |
| D11 | Labelling screen: a local FastAPI page that shows Aditya 30 rules, one at a time, beside the source text, without the grade or the quote-check result | 2026-11-26 | Approved by Aditya |

Open items:

- The fetcher re-checks `robots.txt` at the start of every run, in case one appears.
- Create the Neon project and move the database there before the site goes live in M4.
  Confirmed by Aditya on 2026-11-26.
- Aditya creates a Langfuse project and sets its keys before the first extraction run (D9).

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

**Follow-up, 2026-11-26.** Aditya decided not to write to CCHP. The limits above stay as the
whole of our conduct towards the site.

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

Reading the real page also showed three things the first schema missed, added in migration
`002`: a topic can have sub-headings (`entry.subtopic`), one SOURCE line can link to several
documents (`entry.source_links`, with `source_url` holding the first), and the "At a Glance"
panel is split into named groups (`glance_answer.section`).

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

## D7. Fetching the cited law

**Scope.** The five rule types map to these Florida topics, and nothing else is fetched in M2:

| Rule type | CCHP topics | Entries | With a SOURCE line |
|---|---|---|---|
| Cross-state licensure and registration | Professional Requirements: Cross State Licensing, Licensure Compacts | 10 | 9 |
| Medicaid coverage by modality | Medicaid: Live Video, Store and Forward, Remote Patient Monitoring, Email Phone & Fax | 26 | 19 |
| Consent | Consent Requirements under Medicaid and under Professional Requirements | 2 | 0 |
| Online prescribing | Professional Requirements: Online Prescribing | 5 | 5 |
| Private payer parity | Private Payer: Parity, Requirements | 4 | 4 |

That is 47 entries, 37 with a SOURCE line, citing 25 distinct links on 12 sites.

**What robots.txt says.** Each site was asked once on 2026-11-27 (UTC), through our own fetcher,
and the requests are in `fetch_log`.

| Site | What it is | robots.txt | Links |
|---|---|---|---|
| `www.leg.state.fl.us` | Florida Statutes | allows | 9 |
| `www.flrules.org` | Florida Administrative Code | allows | 1 |
| `ahca.myflorida.com` | Medicaid coverage policies (PDF) | allows | 2 |
| `flboardofmedicine.gov` | Board of Medicine | allows, asks for 3 seconds between requests | 1 |
| `imlcc.com`, `ptcompact.org`, `aslpcompact.com`, `counselingcompact.org` | Licensure compacts | allow (Counseling Compact asks for 10 seconds) | 4 |
| `www.nursecompact.com` | Nurse Licensure Compact | no robots.txt (404) | 1 |
| `psypact.org` | PSYPACT | could not connect | 1 |
| `www.icontact-archive.com` | Archive of Florida Medicaid alert emails | **forbids** | 4 |
| `track.govhawk.com` | Bill tracker (the budget bill) | **forbids** | 2 |

**Decision.**

- Fetch only from sites that allow it, with the M1 fetcher: robots check each run, one request
  at a time per site, our 10 second wait or the site's own if longer.
- Never fetch from the two sites that forbid it. The 11 entries whose only source is there get
  no rules. They are counted and listed in the results as "source not fetchable". This includes
  the only source for Medicaid store-and-forward, so that answer-key line cannot be backed.
- A site that cannot be reached is tried once and reported, not retried in a loop.
- Each document goes into `source_text`: url, fetch time, SHA-256, status, content type, the
  raw body, and the plain text taken from it. HTML is read with BeautifulSoup and PDF with
  pypdf. Any other type is stored and reported as unread.
- If a link opens a doorway page that only points to the document (the Administrative Code
  site may work this way), the fetcher may follow one link on the same site to the document.
  Each such step is written in code for that one site. A model never chooses a link.
- The same document cited by several entries is fetched once.

**Considered.**

- Finding the Medicaid alerts and the budget bill on official sites that allow fetching
  (the agency's own site, the Florida Senate). This would close most of the gap, but a person
  has to confirm each replacement is the same document. Left as a later step for Aditya to
  approve link by link.
- Asking a model to browse for the law. Rejected: rule 16, and it could not be repeated.

**Trade-off.** Florida's Medicaid numbers will be weaker than they could be, and the results
say why. That is preferred over fetching where a site says not to.

## D8. Rules and extraction

**What.** A `rule` table as in the plan, plus the lineage that makes a rule traceable:

- What it is: jurisdiction, rule type, effect (`allow`, `deny`, `require`, `silent`), who and
  what it applies to (profession, payer, modality, service), conditions, a one-sentence summary.
- Evidence: the quote, the `source_text` row it came from, and that row's fetch date.
- Dates: `effective_from` and `effective_to`. They are filled only when the law states them.
  Empty means "in force when fetched, start not stated", never a guessed date.
- Status: `draft`, `unverified` or `approved`, and who approved it.
- Lineage: the entry it came from and the extraction run that made it.

How rules are made:

- For each in-scope entry with a fetched source, one call to `gpt-6.2-sol` through
  `client.responses.parse` with a pydantic schema (structured outputs). The model gets the
  text of the law and the CCHP entry as a pointer to the part that matters. It returns rules
  whose quote must be copied from the law, or says the law is silent on the point.
- Code then checks each quote: it must appear word for word in the stored source text, with
  only runs of whitespace treated as equal. Pass gives `draft`. Fail gives `unverified`, kept
  and shown as such (rule 10). The model never sets a status.
- An entry marked "No Reference Found" becomes a `silent` rule written by code with no model
  call (rule 11). The model is told to return nothing when the law does not address the point.
- If a law is too long to send whole, code picks the passages that share the most words with
  the entry, and the run records that the source was cut.
- Nothing becomes `approved` in M2. Rules wait as `draft` for a person (rule 13).
- Calls are made one at a time, not in batch mode, so the first run's failures are easy to see.
  Batch mode is for the monthly re-reads in M5.

**Why.** It keeps the model to the one job rule 9 allows: reading text into rules. Everything
that decides trust (the quote check, the status, the silent case) is plain code with tests.

**Considered.**

- Letting the model read the CCHP entry alone. Rejected: the evidence must be the law (rule 15).
- Sending only the law, without the CCHP entry. Purer, but on a long statute the model would
  return every rule in it, most of them not about telehealth.
- Embedding search to pick passages from long laws. Word overlap is simpler to explain and
  repeat; embeddings arrive when search is needed.

**Trade-off.** CCHP's entry text is sent to OpenAI as part of the prompt. It is used for
processing only and is never shown or stored anywhere new.

## D9. Model client, cost cap and tracing

**Checked against OpenAI's documentation on 2026-11-26.** Both model IDs exist as written.
Per million tokens: `gpt-6.2-sol` 2.00 US dollars in, 0.10 cached, 10.00 out; `gpt-6-luna`
0.10 in, 0.01 cached, 0.50 out. Structured outputs use `client.responses.parse(...,
text_format=Model)` and `response.output_parsed`. `gpt-6.2-sol` rejects reasoning effort `none`.

**What.** One module, `telecompass/llm.py`, is the only place that calls a model.

- Every call writes a row to `model_call`: run, model, tokens in, cached and out, cost in US
  dollars worked out from the price table in code, time, and whether it failed (rule 21).
- Each run has a hard cap. Before a call, code adds up the run's spend in the database and
  refuses the call if the cap could be passed. Florida's cap is 5.00 US dollars. The estimate
  for the 25 or so calls is 2 to 3 dollars.
- Every call is traced in Langfuse (rule 20), as a generation with the run and entry ids.
- A refusal, a cut-off answer or an API error is recorded and the entry is reported as failed.
  It is never retried silently and never replaced with a guess.
- If the Langfuse keys are missing the run does not start. Tests use a fake model client and
  make no network call.

**Environment.** `OPENAI_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and the
Langfuse address. Langfuse's current documentation names that last one `LANGFUSE_BASE_URL`;
the plan says `LANGFUSE_HOST`. The code reads `LANGFUSE_BASE_URL` first, then `LANGFUSE_HOST`.

**Considered.** Langfuse's drop-in OpenAI import. Its documentation does not confirm support
for the Responses API, so calls are traced explicitly instead. LiteLLM or LangChain as a
wrapper: more layers than one provider needs.

**Trade-off.** No extraction can run until Aditya has created a Langfuse project and set the
keys. That is a deliberate stop, not a soft warning.

## D10. The grade

**What.** `python -m telecompass grade florida` compares the rules with CCHP's "At a Glance"
answers and writes `evals/results/extraction_florida.json`.

Ten answer-key lines fall inside the five rule types:

- Medicaid reimbursement (4): Live Video, Store-and-Forward, Remote Patient Monitoring, Audio Only.
- Private payer law (2): Law Exists, Payment Parity.
- Professional requirements (4): Licensure Compacts (a list of compacts), Limited Licensure
  Exceptions, Telehealth Specific License/Registration Process, Consent Requirements.

For each line, plain Python derives our answer from the rules that passed the quote check, for
example "Medicaid, audio only: is there an `allow` rule for that modality?". The mapping is a
small table in code with tests. Our answer is `yes`, `no` or `silent`, and `silent` against a
CCHP "Yes" counts as a miss, shown separately from a wrong answer.

The file also holds: the quote-check pass rate, counts of rules by status and type, entries
with no fetchable source, failed calls, the model, the cost, and the run id and time. Online
prescribing has no answer-key line, so it is covered by Aditya's labels only.

**Why.** Rule 19: every number shown later must come from a file under `evals/results/`.

**Considered.** Asking a model to judge whether our rules agree with the answer key. Rejected:
a grade should be repeatable, and a judging model would need its own grade.

**Trade-off.** Ten lines is a very small test. The file says so, gives no interval for one
state, and M6 widens it to six states.

## D11. The labelling screen

**What.** `python -m telecompass label florida` starts a small FastAPI app on `127.0.0.1` only.

- It draws 30 rules with a fixed random seed, spread across the five rule types, from both
  `draft` and `unverified` rules. The sample is stored, so the same 30 come back each time.
- One rule per page: the rule in plain words, its quote, and the surrounding text of the law
  with a link to the source. Buttons: Right, Wrong, Cannot tell, and an optional note.
- Blind means the page does not show the quote-check result, the status, the grade or the
  CCHP entry, so the judgement rests on the law alone.
- Labels go to a `label` table with the time. `python -m telecompass grade florida` then adds
  them to the results file. Until Aditya has labelled, the file says 0 of 30 labelled. Nothing
  writes a label except his click (rule 6).

**Why.** FastAPI is already the plan's choice for the API in M4, so this adds no new kind of
tool. A page shows a long passage of law far better than a terminal.

**Considered.** A terminal prompt (hard to read long text). A page in the Next.js site (the
site is not rebuilt until M4, and labels would then pass through a public app).

**Trade-off.** A second small web surface exists before the real API. It listens locally only
and has no login.
