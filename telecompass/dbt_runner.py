"""Run dbt against the chosen database (D22).

dbt runs as its own isolated tool through uv, pinned to one version, so it never shares or
fights over the app's libraries. The database address is split into the settings dbt's profile
reads; none of it is printed.
"""

import os
import subprocess
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict

DBT_CORE = "dbt-core==1.12.7"
DBT_POSTGRES = "dbt-postgres==1.11.0"
DBT_PYTHON = "3.12"
PROJECT = Path(__file__).resolve().parents[1] / "dbt"


def dbt_environment(database_url: str) -> dict[str, str]:
    """The environment variables dbt's profile reads, taken from a database address."""
    parts = conninfo_to_dict(database_url)
    return {
        "TC_DB_HOST": str(parts.get("host", "localhost")),
        "TC_DB_PORT": str(parts.get("port", "5432")),
        "TC_DB_USER": str(parts.get("user", "")),
        "TC_DB_PASSWORD": str(parts.get("password", "")),
        "TC_DB_NAME": str(parts.get("dbname", "")),
        "TC_DB_SSLMODE": str(parts.get("sslmode", "prefer")),
    }


def command(arguments: list[str]) -> list[str]:
    return [
        "uvx",
        "--python",
        DBT_PYTHON,
        "--from",
        DBT_CORE,
        "--with",
        DBT_POSTGRES,
        "dbt",
        *arguments,
        "--project-dir",
        str(PROJECT),
        "--profiles-dir",
        str(PROJECT),
    ]


def run(database_url: str, arguments: list[str]) -> int:
    """Run one dbt command against the database. Returns dbt's exit code."""
    env = {**os.environ, **dbt_environment(database_url), "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    return subprocess.run(command(arguments), env=env, cwd=PROJECT, check=False).returncode
