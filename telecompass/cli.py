"""Command line: python -m telecompass <command>."""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import get_args

from telecompass import (
    approve_app,
    config,
    copy_db,
    db,
    engine,
    extract,
    fetch,
    grade,
    label_app,
    llm,
    parse_cchp,
    pointers,
    preflight,
    review,
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
            conn,
            fetch.Fetcher(conn, client),
            urls,
            sources.load_overrides(),
            args.retry,
            args.reread,
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
            conn,
            args.jurisdiction,
            run.id,
            llm.EXTRACTION_MODEL,
            cap,
            fetch.utc_now(),
            extract.PROMPT_VERSION,
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


def cmd_copy_db(args: argparse.Namespace) -> int:
    """Copy every row from the DATABASE_URL database into the one another setting names.

    The target is given by the name of its setting (for example NEON_DATABASE_URL), so its
    address never appears on the command line or in any output.
    """
    config.load_env()
    target_url = config.require(args.to_env)
    with db.connect(target_url) as target:
        db.migrate(target)
        if args.check:
            counts = copy_db.row_counts(target)
            print(f"Connected to the database {args.to_env} names. Schema is up to date.")
            print(f"  rows already there: {sum(counts.values()):,}")
            return 0
        with _open_database() as source:
            try:
                counts = copy_db.copy_all(source, target)
            except copy_db.TargetNotEmpty as error:
                print(f"Nothing copied: {error}", file=sys.stderr)
                return 1
    print(f"Copied {sum(counts.values()):,} rows into the database {args.to_env} names:")
    for table, count in counts.items():
        print(f"  {table}: {count:,}")
    return 0


def cmd_pointers(args: argparse.Namespace) -> int:
    """Store our hand-written pointers to official pages as entries. No network."""
    with _open_database() as conn:
        run = pointers.store_pointers(
            conn, args.jurisdiction, pointers.pointer_file(args.jurisdiction), fetch.utc_now()
        )
    print(f"Stored {run.entry_count} pointer(s) for {args.jurisdiction} as parse run {run.id}.")
    for note in run.problems:
        print(f"  - {note}")
    return 0


def _visit_from(args: argparse.Namespace) -> engine.Visit:
    on = date.fromisoformat(args.date) if args.date else date.today()
    if args.demo:
        return preflight.demo_visit(on)
    drug = None
    if args.drug:
        drug = engine.Prescription(drug=args.drug, schedule=args.schedule, renewal=args.renewal)
    return engine.Visit(
        profession=args.profession,
        licensed_in=[code.upper() for code in args.licensed],
        registered_in=[code.upper() for code in args.registered],
        patient_state=args.patient_state.upper(),
        modality=args.modality,
        payer=args.payer,
        service=args.service,
        service_category=args.service_category,
        prescription=drug,
        visit_date=on,
    )


def cmd_preflight(args: argparse.Namespace) -> int:
    """Decide one visit on one date from the stored rules. No model is called."""
    try:
        visit = _visit_from(args)
    except ValueError as error:
        print(f"That visit is not valid: {error}", file=sys.stderr)
        return 1
    with _open_database() as conn:
        decision, decision_id, _ = preflight.run_preflight(conn, visit, fetch.utc_now())
        fetched = conn.execute("SELECT max(fetched_at) AS at FROM source_text").fetchone()["at"]
    print(preflight.render(decision, decision_id, f"{fetched:%Y-%m-%d}" if fetched else "never"))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """Start the local page where a person approves or rejects each rule."""
    import uvicorn

    conn = _open_database()
    app = approve_app.create_app(conn, args.reviewer)
    print(f"Rule review page: http://127.0.0.1:{args.port}/   (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """Have a second model check each distinct rule against the stored law."""
    with _open_database() as conn:
        run = rule_store.latest_run(conn, args.jurisdiction)
        if run is None:
            print(
                f"No extraction run for {args.jurisdiction} yet. Run: extract {args.jurisdiction}"
            )
            return 1
        client, tracer = llm.OpenAIClient(), llm.LangfuseTracer()
        gate = llm.ModelGate(conn, client, tracer, run["id"], Decimal(run["cap_usd"]))
        try:
            counts = review.Reviewer(conn, gate, run["id"]).run(
                rule_store.rules_for(conn, run["id"])
            )
        finally:
            tracer.flush()
        spent = rule_store.call_totals(conn, run["id"])["cost_usd"]
    print(f"Automated review of run {run['id']} with {review.REVIEW_MODEL} (not a human review)")
    for name, count in sorted(counts.items()):
        print(f"  {name}: {count}")
    print(f"  run spend so far: ${spent:.4f} of the ${run['cap_usd']:.2f} cap")
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
    auto = results["automated_review"]
    print(
        f"  automated review: {auto['right']} right, {auto['wrong']} wrong, "
        f"{auto['cannot_tell']} cannot tell, of {auto['reviewed']} reviewed"
    )
    print(f"  human labels: {labels['labelled']} of {labels['sample_size']} labelled")
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
    sources_cmd.add_argument(
        "--retry", action="store_true", help="Ask again for documents that failed before."
    )
    sources_cmd.add_argument(
        "--reread", action="store_true", help="Read stored documents again; no new request."
    )
    sources_cmd.set_defaults(run=cmd_sources)

    extract_cmd = commands.add_parser("extract", help="Read the fetched law into rules.")
    extract_cmd.add_argument("jurisdiction", type=str.lower)
    extract_cmd.add_argument("--cap", default="5.00", help="Hard cost cap in US dollars.")
    extract_cmd.set_defaults(run=cmd_extract)

    copy_cmd = commands.add_parser("copy-db", help="Copy this database into another one.")
    copy_cmd.add_argument(
        "--to-env", required=True, help="Name of the setting that holds the target's address."
    )
    copy_cmd.add_argument("--check", action="store_true", help="Only connect and migrate.")
    copy_cmd.set_defaults(run=cmd_copy_db)

    pointers_cmd = commands.add_parser("pointers", help="Store our pointers to official pages.")
    pointers_cmd.add_argument("jurisdiction", type=str.lower)
    pointers_cmd.set_defaults(run=cmd_pointers)

    pre = commands.add_parser("preflight", help="Decide one visit on one date.")
    pre.add_argument("--demo", action="store_true", help="The plan's example visit.")
    pre.add_argument("--date", help="Visit date, YYYY-MM-DD. Default: today.")
    pre.add_argument("--profession", default="physician")
    pre.add_argument("--licensed", nargs="*", default=[], help="State codes, e.g. NY NJ.")
    pre.add_argument("--registered", nargs="*", default=[], help="Telehealth registrations.")
    pre.add_argument("--patient-state", default="FL")
    pre.add_argument("--modality", default="live_video", choices=get_args(engine.Modality))
    pre.add_argument(
        "--payer", default="medicaid", choices=["medicaid", "medicare", "private", "self_pay"]
    )
    pre.add_argument("--service")
    pre.add_argument("--service-category", default="other", choices=["behavioral_health", "other"])
    pre.add_argument("--drug", help="What is prescribed, if anything.")
    pre.add_argument("--schedule", choices=["II", "III", "IV", "V"], help="Controlled schedule.")
    pre.add_argument("--renewal", action="store_true")
    pre.set_defaults(run=cmd_preflight)

    approve_cmd = commands.add_parser("approve", help="Approve or reject rules, by hand.")
    approve_cmd.add_argument("--port", type=int, default=8766)
    approve_cmd.add_argument("--reviewer", default="Aditya Kanbargi", help="Who is reviewing.")
    approve_cmd.set_defaults(run=cmd_approve)

    review_cmd = commands.add_parser("review", help="Second-model check of each rule.")
    review_cmd.add_argument("jurisdiction", type=str.lower)
    review_cmd.set_defaults(run=cmd_review)

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
