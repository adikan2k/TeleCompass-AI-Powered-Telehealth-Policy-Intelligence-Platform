"""Command line: python -m telecompass <command>."""

import argparse
import sys
from collections.abc import Sequence

from telecompass import config, db, fetch, parse_cchp, show, store


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telecompass", description="Telehealth visit preflight.")
    commands = parser.add_subparsers(dest="command", required=True)

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
