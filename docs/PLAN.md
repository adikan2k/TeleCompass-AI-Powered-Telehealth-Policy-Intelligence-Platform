# TeleCompass rebuild plan

## Goal

Describe a telehealth visit. TeleCompass says whether it is allowed and payable on a given date,
shows the exact sentence of law behind each answer, and reports what changed since last month.

Interview line: "CCHP tells you what each state's policy says. TeleCompass decides one visit, on
one date, and shows the law behind every step."

It is one project with three walkthroughs: AI engineering (law into rules, checked quotes, an
agent with human approval, evals), data engineering (snapshots, dated tables, tests, lineage) and
analysis (what changed, what expires, shown on a map).

## What we keep and what we drop

Keep: the name, the repository, the Next.js shell, credit to the original team in the README.

Drop: Ollama, Pinecone, PDF upload, the chat tab, the similarity "confidence" score, Prisma.
CCHP already offers search, compare and trend maps for free, so those tabs go too.

## Where the data comes from

CCHP's Policy Finder (https://www.cchpca.org/) has a page per jurisdiction:

- An "At a Glance" panel of yes/no answers per state. This is the answer key for evals.
- Entries grouped by category and topic, each ending in a SOURCE line that names the statute,
  rule or manual and the month it was accessed.
- "Last updated" dates, entries marked "No Reference Found", and provisions with expiry dates.

TeleCompass reads the state page, follows each SOURCE to the law, and quotes the law. CCHP is
linked as the map. See rules 14 and 15 in `CLAUDE.md`.

## Other sources

CCHP is the map. These fill in what it points to, and each is checked for its own robots.txt and
terms before it is fetched.

| Source | What it adds |
|---|---|
| State statute, administrative code and Medicaid manual sites (the SOURCE links) | The exact words of the law, shown as evidence |
| CMS: telehealth FAQ, the Medicare telehealth services list, the Physician Fee Schedule | Federal Medicare rules and their dates |
| telehealth.hhs.gov | Plain federal summaries of licensure and policy updates |
| Federal Register and eCFR (both have free APIs) | Dated federal rules, including DEA telemedicine prescribing |
| Compact sites: IMLC, PSYPACT, Nurse Licensure Compact, Counseling Compact | Which states belong to which licensure compact |
| NPPES NPI Registry (free public API) | A clinician's listed licence states from an NPI, for the demo form. Self-reported, so shown as "listed", never "verified" |
| LegiScan (free tier API) | Pending state bills, for a "what may change next" view |
| Internet Archive Wayback Machine | Older copies of CCHP state pages, for the time view before our own snapshots begin |

## Stack

| Part | Choice |
|---|---|
| Models | OpenAI: `gpt-6.2-sol` (rules, agent), `gpt-6-luna` (bulk), OpenAI embeddings, batch mode for monthly re-reads |
| Database | Neon Postgres for everything: snapshots, entries, dated rules, decisions, pgvector and full-text search |
| Rules engine | Plain typed Python with tests |
| Agent | LangGraph with a checkpointer and an approval interrupt, for the change review |
| Pipeline | Dagster for the schedule, dbt for models and data tests (added in M5) |
| API | FastAPI on Cloud Run |
| Site | Next.js, Tailwind, shadcn on Vercel |
| Quality | pytest, DeepEval in CI, Langfuse tracing, cost caps |

## The tables

- `snapshot`: jurisdiction, url, fetched_at, sha256, raw page.
- `entry`: jurisdiction, category, topic, text, source name, source url, accessed, last_updated.
- `source_text`: the statute, rule or manual page as fetched, with hash and fetch time.
- `rule`: jurisdiction, rule type, who and what it applies to (profession, payer, modality,
  service), effect (allow, deny, require, silent), conditions, quote, source, effective_from,
  effective_to, status (draft, approved, unverified), who approved it.
- `decision`: the visit asked about, the date, the answer, and the ids of the rules used.

Five rule types to start: cross-state licensure and registration, Medicaid coverage by modality,
consent, online prescribing, private payer parity.

## Milestones

Each one ends with something you can run and show.

### M0. Set up
- Clone the repository, create `rebuild`, move the starter files in, add the Python package
  `telecompass/` with `pyproject.toml`, ruff, pytest and one passing test.
- Check `https://www.cchpca.org/robots.txt` and record what it allows in `docs/DECISIONS.md`.
- Done when: `pytest` passes and the robots.txt finding is written down.

### M1. One state in the database
- Fetch Florida's page once, store the snapshot, parse it into `entry` rows with their SOURCE
  lines, dates and the "At a Glance" answers.
- Done when: `python -m telecompass show florida` prints the entries and the answer key.

### M2. Law into rules, and a grade
- For each Florida entry in the five rule types, fetch the cited law where allowed, extract rules
  into the schema with structured outputs, and check every quote in code.
- Grade the rules against Florida's "At a Glance" answers.
- **[ADITYA]** Read 30 Florida rules against their sources and mark each right or wrong. Build a
  small blind labelling screen for this.
- Done when: `evals/results/extraction_florida.json` holds the answer-key score and Aditya's
  30 labels.

### M3. Preflight in the terminal
- The rules engine takes a visit (clinician's licence states and profession, patient location,
  modality, payer, service, prescription, date) and returns allowed, not allowed, allowed with
  conditions, or silent, per rule type, with quotes and what would make it allowed.
- Add the federal Medicare telehealth timeline as dated rules, each with its CMS source.
- Done when: the New York psychiatrist, Florida patient, audio-only, Medicaid, stimulant renewal
  visit returns a full answer, and changing the date changes the Medicare lines.

### M4. Live site
- Preflight page: a short form or one sentence in, the answer out, each line opening its quote
  and source. A date slider. Every decision stored with its rule versions and given its own link.
- API on Cloud Run kept warm, site on Vercel, counters in the database.
- Done when: a stranger can run a visit from the public address and share the link.

### M5. Time and change
- Dagster schedules a monthly snapshot. dbt builds the tables and runs data tests.
- A diff of entries between snapshots. A LangGraph agent proposes rule changes from the diff and
  pauses for approval in a review queue.
- "What changed for you": pick states and a service line, get the changes and upcoming expiries.
- Done when: a real change between two snapshots flows through to an approved rule, with lineage
  from decision to rule to quote to snapshot.

### M6. Six states and the numbers
- Add five more states chosen for contrast. Rerun extraction and the answer-key grade on all.
- An evals page: answer-key accuracy per rule type with intervals, quote-check pass rate, how
  often it says "silent", Aditya's labels, and what failed.
- A findings page for the analyst walkthrough: a map and three short written findings.
- Done when: `make evals` writes the result files and both pages read from them.

### M7. Ship
- README with an architecture diagram, results, limits, and credit to the original team.
- A company profile file, so a demo can open on one company's states and services.
- **[ADITYA]** A two-minute video, and five people from healthcare trying a visit of their own.

## Budget

OpenAI credit covers the models. Free tiers for Neon, Langfuse, Vercel and Cloud Run. A hard cap
per run in code, and the first state's cost measured before adding more.

## Environment variables

`OPENAI_API_KEY`, `DATABASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.
Keep them in the project's `.env` only.
