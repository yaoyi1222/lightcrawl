from __future__ import annotations

import json
import os
from pathlib import Path


def _lightcrawl_config() -> dict[str, object]:
    """Load ~/.lightcrawl/config.json, returning {} when absent or unreadable."""
    path = Path.home() / ".lightcrawl" / "config.json"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _tavily_cli_config() -> dict[str, object]:
    """Load ~/.tavily/config.json (the `tvly` CLI auth store), returning {}
    when absent or unreadable."""
    path = Path.home() / ".tavily" / "config.json"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if isinstance(data, dict):
        return data
    return {}


def resolve_api_key(
    env_var: str,
    backend_name: str,
    *,
    explicit: str | None = None,
) -> str | None:
    """Resolve a backend API key from multiple sources in priority order:

    1. Explicit parameter passed to the backend constructor.
    2. Environment variable (current behaviour, unchanged).
    3. ~/.lightcrawl/config.json → backends → <name> → api_key.
    4. Tavily only: ~/.tavily/config.json → api_key (the `tvly` CLI auth store).
    """
    if explicit:
        return explicit

    key = os.environ.get(env_var)
    if key:
        return key

    lc_cfg = _lightcrawl_config()
    backends_cfg = lc_cfg.get("backends")
    if isinstance(backends_cfg, dict):
        entry = backends_cfg.get(backend_name)
        if isinstance(entry, dict):
            key = entry.get("api_key")
            if isinstance(key, str) and key:
                return key

    if backend_name == "tavily":
        tvly_cfg = _tavily_cli_config()
        key = tvly_cfg.get("api_key")
        if isinstance(key, str) and key:
            return key

    return None
