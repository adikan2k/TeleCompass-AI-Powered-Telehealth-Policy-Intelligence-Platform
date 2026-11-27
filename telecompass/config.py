"""Settings come from environment variables. The project's .env is loaded into them at start."""

import os
from pathlib import Path

from dotenv import load_dotenv


class MissingSetting(RuntimeError):
    """A required environment variable is not set."""


def load_env(env_file: Path | None = None) -> None:
    """Load a .env file into the environment. Variables that are already set win."""
    if env_file is None:
        load_dotenv()
    else:
        load_dotenv(env_file)


def database_url() -> str:
    """Return DATABASE_URL, or fail with a message that does not reveal any value."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise MissingSetting(
            "DATABASE_URL is not set. Copy .env.example to .env, or set the variable yourself."
        )
    return url


def require(name: str) -> str:
    """Return an environment variable, or fail naming the variable and never its value."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingSetting(f"{name} is not set. Add it to .env or to your environment.")
    return value


def langfuse_base_url() -> str:
    """The Langfuse address. LANGFUSE_BASE_URL is the current name; LANGFUSE_HOST also works."""
    for name in ("LANGFUSE_BASE_URL", "LANGFUSE_HOST"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise MissingSetting(
        "LANGFUSE_BASE_URL is not set. Add it to .env, for example https://cloud.langfuse.com "
        "or https://us.cloud.langfuse.com, matching the region of your Langfuse project."
    )
