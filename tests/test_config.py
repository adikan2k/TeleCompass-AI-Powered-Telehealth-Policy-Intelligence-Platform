from pathlib import Path

import pytest

from telecompass.config import MissingSetting, database_url, load_env


def test_database_url_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://example@127.0.0.1:1/example")
    assert database_url() == "postgresql://example@127.0.0.1:1/example"


def test_missing_database_url_fails_with_a_plain_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(MissingSetting, match="DATABASE_URL is not set"):
        database_url()


def test_env_file_is_loaded_but_does_not_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('DATABASE_URL="postgresql://from-file@127.0.0.1:1/x"\n', encoding="utf-8")

    # Set then delete, so pytest remembers the starting state and restores it afterwards.
    monkeypatch.setenv("DATABASE_URL", "placeholder")
    monkeypatch.delenv("DATABASE_URL")
    load_env(env_file)
    assert database_url() == "postgresql://from-file@127.0.0.1:1/x"

    monkeypatch.setenv("DATABASE_URL", "postgresql://already-set@127.0.0.1:1/x")
    load_env(env_file)
    assert database_url() == "postgresql://already-set@127.0.0.1:1/x"
