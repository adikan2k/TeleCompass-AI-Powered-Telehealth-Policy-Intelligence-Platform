# Decisions

## Summary

The decisions that mattered, newest last. Details are in the entries below.

| # | Decision | Date | Status |
|---|---|---|---|
| D1 | Flat `telecompass/` Python package at the repo root, hatchling build, uv for the environment | 2026-11-26 | Approved by Aditya |
| D2 | CCHP has no `robots.txt` (404). Fetching is not forbidden by robots rules; terms of use still to be read before M1 | 2026-11-26 | Approved by Aditya |

Open items:

- Read CCHP's terms of use before the first Florida fetch in M1.
- The fetcher re-checks `robots.txt` at the start of every run, in case one appears.

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
