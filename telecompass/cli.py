"""Command line: python -m telecompass <command>."""

import argparse
import sys
from collections.abc import Sequence

from telecompass import config, db, fetch

DISCLAIMER = "Not legal advice."


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telecompass", description="Telehealth visit preflight.")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch_cmd = commands.add_parser("fetch", help="Fetch a jurisdiction's CCHP page once.")
    fetch_cmd.add_argument("jurisdiction")
    fetch_cmd.add_argument("--force", action="store_true", help="Fetch even if already stored.")
    fetch_cmd.set_defaults(run=cmd_fetch)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except config.MissingSetting as error:
        print(error, file=sys.stderr)
        return 2
