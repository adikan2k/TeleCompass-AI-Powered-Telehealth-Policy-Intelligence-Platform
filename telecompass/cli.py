"""Command line: python -m telecompass <command>."""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal

from telecompass import (
    config,
    db,
    extract,
    fetch,
    grade,
    label_app,
    llm,
    parse_cchp,
    rule_store,
    show,
    sources,
    store,
)


def _open_database() -> db.Connection:
    """Load .env, connect and bring the schema up to date."""
    config.load_env()
    conn = db.connect(config.database_url())
    db.migrate(conn)
    return conn


def cmd_fetch(args: argparse.Namespace) -> int:
    """Fetch a jurisdiction's CCHP page once and store the raw page."""
    with _open_database() as conn, fetch.new_client() as client:
        fetcher = fetch.Fetcher(conn, client)
        try:
            snapshot = fetch.fetch_jurisdiction(conn, fetcher, args.jurisdiction, args.force)
        except (fetch.FetchRefused, fetch.AlreadyFetched) as error:
            print(f"Not fetched: {error}", file=sys.stderr)
            return 1
    print(f"Stored snapshot {snapshot.id} of {snapshot.url}")
    print(f"  fetched at {snapshot.fetched_at:%Y-%m-%d %H:%M:%S} UTC")
    print(f"  sha256     {snapshot.sha256}")
    print(f"  size       {len(snapshot.raw_page):,} characters")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    """Parse the newest stored snapshot into entry and answer rows. No network."""
    with _open_database() as conn:
        snapshot = store.latest_snapshot(conn, args.jurisdiction)
        if snapshot is None:
            print(f"No snapshot of {args.jurisdiction} yet. Run: fetch {args.jurisdiction}")
            return 1
        parsed = parse_cchp.parse_state_page(snapshot.raw_page)
        run = store.save_parse(conn, snapshot, parsed, parse_cchp.PARSER_VERSION, fetch.utc_now())
    print(f"Parse run {run.id} over snapshot {snapshot.id}:")
    print(f"  {run.entry_count} entries, {run.answer_count} answers, {len(run.problems)} notes")
    for note in run.problems:
        print(f"  - {note}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Print the answer key and a short excerpt of every entry."""
    with _open_database() as conn:
        snapshot = store.latest_snapshot(conn, args.jurisdiction)
        if snapshot is None:
            print(f"No snapshot of {args.jurisdiction} yet. Run: fetch {args.jurisdiction}")
            return 1
        run = store.latest_parse_run(conn, snapshot.id)
        if run is None:
            print(f"Snapshot {snapshot.id} is not parsed yet. Run: parse {args.jurisdiction}")
            return 1
        answers = store.answers_for(conn, run.id)
        entries = store.entries_for(conn, run.id)
    print(show.render(snapshot, run, answers, entries))
    return 0


def _latest_parse(conn: db.Connection, jurisdiction: str):
    """The newest snapshot and parse run, or (None, None) with a hint already printed."""
    snapshot = store.latest_snapshot(conn, jurisdiction)
    run = store.latest_parse_run(conn, snapshot.id) if snapshot else None
    if run is None:
        print(f"Nothing parsed for {jurisdiction} yet. Run: fetch, then parse.")
        return None, None
    return snapshot, run


def cmd_sources(args: argparse.Namespace) -> int:
    """Fetch the law that in-scope entries cite, from sites whose robots.txt allows it."""
    with _open_database() as conn, fetch.new_client() as client:
        _, run = _latest_parse(conn, args.jurisdiction)
        if run is None:
            return 1
        urls = sources.cited_urls(store.stored_entries_for(conn, run.id))
        print(f"{len(urls)} cited links. One request at a time per site, so this takes a while.")
        results = sources.fetch_sources(
            conn, fetch.Fetcher(conn, client), urls, sources.load_overrides()
        )
    for outcome, count in sorted(Counter(result.outcome for result in results).items()):
        print(f"  {outcome}: {count}")
    for result in results:
        size = f"{len(result.text):,} chars" if result.text else "no text"
        note = f"  ({result.note})" if result.note and result.outcome != sources.FETCHED else ""
        print(f"  [{result.outcome}] {size}  {result.url[:90]}{note[:160]}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    """Read the fetched law into rules. Needs the OpenAI and Langfuse keys."""
    with _open_database() as conn:
        _, run = _latest_parse(conn, args.jurisdiction)
        if run is None:
            return 1
        client, tracer = llm.OpenAIClient(), llm.LangfuseTracer()
        cap = Decimal(args.cap)
        run_id = rule_store.start_run(
            conn, args.jurisdiction, run.id, llm.EXTRACTION_MODEL, cap, fetch.utc_now()
        )
        gate = llm.ModelGate(conn, client, tracer, run_id, cap)
        try:
            extract.Extractor(conn, gate, run_id, args.jurisdiction).run(
                store.stored_entries_for(conn, run.id)
            )
        finally:
            tracer.flush()
        totals = rule_store.call_totals(conn, run_id)
        items = Counter(item["outcome"] for item in rule_store.items_for(conn, run_id))
        rules = Counter(rule.status for rule in rule_store.rules_for(conn, run_id))
    print(f"Extraction run {run_id} with {llm.EXTRACTION_MODEL}, cap ${cap:.2f}")
    print(f"  model calls: {totals['calls']} ({totals['failed']} failed)")
    print(f"  spent: ${totals['cost_usd']:.4f}")
    print(f"  entries: {dict(items)}")
    print(f"  rules by status: {dict(rules)}")
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    """Grade the newest run against the answer key and write the results file."""
    with _open_database() as conn:
        try:
            results = grade.build_results(conn, args.jurisdiction, fetch.utc_now())
        except LookupError as error:
            print(error)
            return 1
    path = grade.write_results(results)
    key, labels = results["answer_key"], results["labels"]
    print(f"Wrote {path}")
    print(f"  answer key: {key['matched']} of {key['total']} lines matched {key['counts']}")
    check = results["rules"]["quote_check"]
    print(f"  quote check: {check['passed']} of {check['checked']} quotes found word for word")
    print(f"  labels: {labels['labelled']} of {labels['sample_size']} labelled")
    print(f"  {results['not_legal_advice']}")
    return 0


def cmd_label(args: argparse.Namespace) -> int:
    """Start the local labelling page."""
    import uvicorn

    conn = _open_database()
    run = rule_store.latest_run(conn, args.jurisdiction)
    if run is None:
        print(f"No extraction run for {args.jurisdiction} yet. Run: extract {args.jurisdiction}")
        return 1
    snapshot = store.latest_snapshot(conn, args.jurisdiction)
    fetched = f"{snapshot.fetched_at:%Y-%m-%d}" if snapshot else "unknown"
    app = label_app.create_app(conn, run["id"], args.labeller, fetched)
    print(f"Labelling page: http://127.0.0.1:{args.port}/   (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telecompass", description="Telehealth visit preflight.")
    commands = parser.add_subparsers(dest="command", required=True)

    sources_cmd = commands.add_parser("sources", help="Fetch the law the entries cite.")
    sources_cmd.add_argument("jurisdiction", type=str.lower)
    sources_cmd.set_defaults(run=cmd_sources)

    extract_cmd = commands.add_parser("extract", help="Read the fetched law into rules.")
    extract_cmd.add_argument("jurisdiction", type=str.lower)
    extract_cmd.add_argument("--cap", default="5.00", help="Hard cost cap in US dollars.")
    extract_cmd.set_defaults(run=cmd_extract)

    grade_cmd = commands.add_parser("grade", help="Grade rules and write the results file.")
    grade_cmd.add_argument("jurisdiction", type=str.lower)
    grade_cmd.set_defaults(run=cmd_grade)

    label_cmd = commands.add_parser("label", help="Start the local labelling page.")
    label_cmd.add_argument("jurisdiction", type=str.lower)
    label_cmd.add_argument("--port", type=int, default=8765)
    label_cmd.add_argument("--labeller", default="Aditya", help="Who is labelling.")
    label_cmd.set_defaults(run=cmd_label)

    fetch_cmd = commands.add_parser("fetch", help="Fetch a jurisdiction's CCHP page once.")
    fetch_cmd.add_argument("jurisdiction", type=str.lower)
    fetch_cmd.add_argument("--force", action="store_true", help="Fetch even if already stored.")
    fetch_cmd.set_defaults(run=cmd_fetch)

    parse_cmd = commands.add_parser("parse", help="Parse the stored page into entries.")
    parse_cmd.add_argument("jurisdiction", type=str.lower)
    parse_cmd.set_defaults(run=cmd_parse)

    show_cmd = commands.add_parser("show", help="Print the entries and the answer key.")
    show_cmd.add_argument("jurisdiction", type=str.lower)
    show_cmd.set_defaults(run=cmd_show)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Never crash on a character the terminal cannot draw.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except config.MissingSetting as error:
        print(error, file=sys.stderr)
        return 2
