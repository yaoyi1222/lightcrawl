"""Unit tests for search config resolution (resolve_api_key)."""
from __future__ import annotations

import json
from pathlib import Path

from lightcrawl.search.config import resolve_api_key


def test_explicit_wins(tmp_path: Path, monkeypatch):
    """Explicit api_key parameter takes priority over every other source."""
    monkeypatch.setenv("TAVILY_API_KEY", "env-key")
    tvly_cfg = tmp_path / "tavily" / "config.json"
    tvly_cfg.parent.mkdir()
    tvly_cfg.write_text(json.dumps({"api_key": "tvly-cli-key"}))

    result = resolve_api_key("TAVILY_API_KEY", "tavily", explicit="explicit-key")
    assert result == "explicit-key"


def test_env_var_fallback(tmp_path: Path, monkeypatch):
    """When no explicit key, environment variable is used next."""
    monkeypatch.setenv("TAVILY_API_KEY", "env-key")
    assert resolve_api_key("TAVILY_API_KEY", "tavily") == "env-key"


def test_lightcrawl_config_fallback(tmp_path: Path, monkeypatch):
    """~/.lightcrawl/config.json is checked after env var."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    lc_dir = tmp_path / ".lightcrawl"
    lc_dir.mkdir()
    cfg = {"backends": {"brave": {"api_key": "lc-brave-key"}}}
    (lc_dir / "config.json").write_text(json.dumps(cfg))

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert resolve_api_key("BRAVE_SEARCH_API_KEY", "brave") == "lc-brave-key"


def test_lightcrawl_config_missing_backend_returns_none(tmp_path: Path, monkeypatch):
    """When the backend isn't in the config file, returns None."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    lc_dir = tmp_path / ".lightcrawl"
    lc_dir.mkdir()
    cfg = {"backends": {"brave": {"api_key": "k"}}}
    (lc_dir / "config.json").write_text(json.dumps(cfg))

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert resolve_api_key("TAVILY_API_KEY", "tavily") is None


def test_tavily_cli_config_fallback(tmp_path: Path, monkeypatch):
    """~/.tavily/config.json is the last fallback for tavily."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    tvly_dir = tmp_path / ".tavily"
    tvly_dir.mkdir()
    tvly_dir.joinpath("config.json").write_text(json.dumps({"api_key": "tvly-cli-key"}))

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert resolve_api_key("TAVILY_API_KEY", "tavily") == "tvly-cli-key"


def test_tavily_cli_config_not_checked_for_non_tavily(tmp_path: Path, monkeypatch):
    """~/.tavily/config.json is NOT used for brave or serper."""
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    tvly_dir = tmp_path / ".tavily"
    tvly_dir.mkdir()
    tvly_dir.joinpath("config.json").write_text(json.dumps({"api_key": "tvly-cli-key"}))

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert resolve_api_key("BRAVE_SEARCH_API_KEY", "brave") is None


def test_priority_env_over_config(tmp_path: Path, monkeypatch):
    """Environment variable beats ~/.lightcrawl/config.json."""
    monkeypatch.setenv("TAVILY_API_KEY", "env-key")

    lc_dir = tmp_path / ".lightcrawl"
    lc_dir.mkdir()
    (lc_dir / "config.json").write_text(
        json.dumps({"backends": {"tavily": {"api_key": "lc-key"}}})
    )

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert resolve_api_key("TAVILY_API_KEY", "tavily") == "env-key"


def test_none_when_nothing_configured(tmp_path: Path, monkeypatch):
    """Returns None when no key is available from any source."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert resolve_api_key("TAVILY_API_KEY", "tavily") is None
    assert resolve_api_key("BRAVE_SEARCH_API_KEY", "brave") is None


def test_missing_config_files_graceful(tmp_path: Path, monkeypatch):
    """Missing config files do not raise — they return None."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # tmp_path has no .lightcrawl or .tavily directories
    assert resolve_api_key("TAVILY_API_KEY", "tavily") is None


def test_malformed_config_json_graceful(tmp_path: Path, monkeypatch):
    """Malformed JSON in config files is treated as absent."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    tvly_dir = tmp_path / ".tavily"
    tvly_dir.mkdir()
    tvly_dir.joinpath("config.json").write_text("not json")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert resolve_api_key("TAVILY_API_KEY", "tavily") is None
