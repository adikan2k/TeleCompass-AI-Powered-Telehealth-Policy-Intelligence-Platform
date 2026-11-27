# TeleCompass

**A preflight check for telehealth visits.** Describe a visit, pick a date, and TeleCompass says
line by line whether it is allowed and payable, with the exact words of the law behind each
answer.

**Live:** https://telecompass.vercel.app

It is built for mental-health telehealth companies that are expanding across states. Their
recurring questions are: may this clinician treat a patient in that state, may the visit be by
phone, will the payer pay, and may a controlled medicine be prescribed.

> **Not legal advice.** TeleCompass is a research tool. It shows what the law it has read says,
> and it says so when it holds no rule. Every answer carries the date its sources were fetched.

## What it does today

- **Reads the law, not a summary.** For each state it follows the Center for Connected Health
  Policy's index to the statutes, rules and manuals themselves, and reads those.
- **Never invents a rule.** A model reads law into rules. Code then checks that each rule's
  quote appears word for word in the stored law. A rule whose quote is not found is not used.
- **Says "silent" when the law is silent.** Where it holds no rule, it says so and does not
  guess.
- **Decides with plain code.** A rules engine in ordinary Python applies the rules to a visit.
  No model takes part in a decision, so the same visit always gets the same answer.
- **Knows about dates.** Federal Medicare telehealth rules carry their start and end dates, so
  the answer for a visit in 2026 differs from the same visit in 2028.
- **Double-checks itself.** A second model reviews every rule against the law. Its verdicts are
  reported as an automated check, never as a human one.
- **Tracks change.** Each copy of a policy page is kept. Two copies are compared entry by entry;
  an agent reads the law behind each real change and proposes rules to add or retire, then waits.
  Nothing reaches the answers until a person approves it. The "What changed" page lists, for the
  states you serve, what moved, what was approved, and which rules start or end soon.

## An example

A psychiatrist licensed in New York, a patient in Florida, a phone call, Medicaid, a renewal of
a stimulant:

```
uv run python -m telecompass preflight --demo --date 2026-12-01
```

- **Cross-state licensure: not allowed.** No Florida licence or registration. The answer shows
  the routes Florida law offers, such as its out-of-state telehealth registration.
- **Medicaid payment: not allowed.** Florida Medicaid does not pay for telephone calls. Live
  video would be paid.
- **Consent: silent.** No Florida rule requiring it was found.
- **Prescribing: allowed with conditions.** Schedule II medicines are barred by telehealth
  unless an exception applies; treating a psychiatric disorder is one of the listed exceptions.
- **Medicare, for reference.** No in-person visit is required in 2026. Run the same visit for
  March 2028 and one is.

## Coverage and results so far

All numbers below come from the files in [`evals/results/`](evals/results/).

| | Florida | Federal Medicare |
|---|---|---|
| Rules read from the law | 75 | 17 |
| Quotes found word for word in the law | 62 of 62 | 17 of 17 |
| Distinct rules judged right by the second model | 30 of 39 | 13 of 14 |
| Agreement with CCHP's own summary answers | 8 of 10, none wrong | not applicable |
| Approved by a person before use | 39 of 39, in one step | 14 of 14, in one step |

Florida covers five kinds of rule: cross-state licensure, Medicaid payment by modality, consent,
online prescribing and private-plan duties.

**Change over time** ([`evals/results/changes_florida.json`](evals/results/changes_florida.json)).
The Florida policy page as captured on 21 May 2026 (Internet Archive) was compared with the copy
fetched on 27 Nov 2026: 6 real changes in scope. The agent read the law behind them: 1 new rule
(Medicaid remote monitoring for high-risk pregnancies, proposed from 2 entries citing the same
press release), approved by a person and now live; 3 changes cite alerts on a site that forbids
fetching and are shown as unreadable; 1 holds no rule. Cost: under 3 US cents.

## Limits you should know

- **One state so far.** Florida, plus federal Medicare. More states are planned.
- **Approval was given in one step.** Every rule the site uses was approved by a person on
  the review page, after reading the rules; the approvals were recorded together in one step,
  and the results files say so. A rule extracted later must be approved before the site uses it.
- **Some law could not be read.** Two sites that Florida's index cites forbid automated
  fetching, and TeleCompass does not fetch where a site says no. Eleven Florida entries have no
  rules for that reason, including the only source on Medicaid store-and-forward.
- **State rules rarely state a start date.** TeleCompass can say what the law as fetched says.
  A change is dated by the copy of the page that first showed it, so it is only as precise as
  the gap between two copies.
- **The monthly schedule runs on this machine for now.** It is written and tested, but not yet
  running on a server.

## How it is built

```
CCHP state page ──> entries with their cited sources
                         │
        fetch the cited law (robots.txt obeyed, one request at a time)
                         │
        model reads law into rules ──> code checks every quote ──> second model reviews
                         │
        rules engine (plain Python) + a visit + a date ──> answer with quotes

monthly: new copy ──> diff ──> agent proposes ──> a person approves ──> live rules ──> dbt checks
```

- **Python 3.11+**, FastAPI, PostgreSQL. The package is in [`telecompass/`](telecompass/).
- **LangGraph** runs the change agent and its pause for a person; **dbt** builds the lineage
  tables and data tests; **Dagster** schedules the month.
- **OpenAI models** read law into rules and review them. Every model call is counted in the
  database, capped per run, and traced in Langfuse.
- **Site**: Next.js, Tailwind, Anime.js and a small three.js compass in [`web/`](web/), tested
  end to end with Playwright.
- **Decisions** that shaped the project, with what was considered and why, are in
  [`docs/DECISIONS.md`](docs/DECISIONS.md). The plan is in [`docs/PLAN.md`](docs/PLAN.md).

## Run it yourself

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker and Node 20+.

```
docker compose up -d --wait        # a local PostgreSQL, no password, this machine only
cp .env.example .env               # then fill in the keys you have
uv run --extra dev pytest          # the tests need Docker running
```

The pipeline for a state, step by step:

```
uv run python -m telecompass fetch florida      # the CCHP page, once
uv run python -m telecompass parse florida
uv run python -m telecompass sources florida    # the law it cites, where sites allow
uv run python -m telecompass extract florida    # needs OpenAI and Langfuse keys
uv run python -m telecompass review florida
uv run python -m telecompass grade florida      # writes evals/results/
uv run python -m telecompass preflight --demo
```

Change over time (run monthly by a Dagster schedule, or by hand):

```
uv run python -m telecompass wayback florida --at 20260521160700   # an older copy, from the Internet Archive
uv run python -m telecompass diff florida       # what changed between the last two copies
uv run python -m telecompass sources florida --refresh   # has the cited law itself changed?
uv run python -m telecompass changes florida    # the agent proposes rule changes, then waits
uv run python -m telecompass approve            # review page: approve proposals at /changes
uv run python -m telecompass dbt build          # lineage tables and data tests
uv run --extra pipeline dagster dev -m telecompass.orchestration   # the monthly schedule
```

The API and the site, locally:

```
uv run uvicorn telecompass.api:production_app --factory --port 8000
cd web && npm install && npm run dev            # http://localhost:3000
```

The site's end-to-end tests (desktop and phone, with an accessibility scan):

```
cd web && npx playwright install chromium && npm run e2e
```

## Credit

TeleCompass began as a telehealth policy search and question-answering app built by
Sanjana K M and Aditya Kanbargi. This repository is a rebuild of that project by
Aditya Kanbargi around a different idea: deciding one visit, with the law quoted. The original
app is in the git history.

Policy index: the [Center for Connected Health Policy](https://www.cchpca.org/). TeleCompass
uses CCHP's pages as a map to the law and does not republish them.
