from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

import pytest

from lightcrawl import cli


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # All CLI commands call ensure_dirs() and may write profiles/dumps.
    monkeypatch.setattr("lightcrawl.paths.ROOT", tmp_path)
    monkeypatch.setattr("lightcrawl.paths.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("lightcrawl.paths.PROFILES", tmp_path / "profiles")
    monkeypatch.setattr("lightcrawl.paths.LOGS", tmp_path / "logs")
    monkeypatch.setattr("lightcrawl.auth.PROFILES", tmp_path / "profiles")


def _run(argv: list[str]) -> tuple[int, dict]:
    """Invoke the CLI and parse the JSON it printed."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(argv)
    out = buf.getvalue().strip()
    payload = json.loads(out) if out else {}
    return rc, payload


# -- list-backends ----------------------------------------------------------


def test_list_backends_prints_shape_and_exits_zero():
    rc, out = _run(["list-backends"])
    assert rc == 0
    assert out["ok"] is True
    names = {b["name"] for b in out["backends"]}
    assert names == {"brave", "serper", "tavily"}
    for b in out["backends"]:
        assert "configured" in b
        assert "cost_per_call_usd" in b


# -- fetch ------------------------------------------------------------------


def test_fetch_ok_exits_zero():
    fake = AsyncMock(return_value={
        "ok": True,
        "url": "https://example.com/",
        "final_url": "https://example.com/",
        "strategy_used": "http",
        "title": "Example",
        "content": "body text",
        "content_truncated": False,
        "dump_path": None,
        "metadata": {"status_code": 200},
        "attempts": [],
        "headings": [],
    })
    with patch("lightcrawl.cli.Router") as RouterCls:
        RouterCls.return_value.fetch = fake
        RouterCls.return_value.close = AsyncMock()
        rc, out = _run(["fetch", "https://example.com/"])
    assert rc == 0
    assert out["ok"] is True
    assert out["url"] == "https://example.com/"


def test_fetch_failure_exits_one():
    fake = AsyncMock(return_value={
        "ok": False,
        "url": "https://blocked.example/",
        "error_code": "BLOCKED_BY_CLOUDFLARE",
        "error_detail": "still blocked after L2",
        "attempts": [],
        "suggestions": [],
    })
    with patch("lightcrawl.cli.Router") as RouterCls:
        RouterCls.return_value.fetch = fake
        RouterCls.return_value.close = AsyncMock()
        rc, out = _run(["fetch", "https://blocked.example/"])
    assert rc == 1
    assert out["error_code"] == "BLOCKED_BY_CLOUDFLARE"


def test_fetch_closes_router_even_on_failure():
    """We always tear down the BrowserPool — otherwise a one-shot CLI
    invocation leaks a Chromium subprocess on exit. The unexpected
    exception is converted to an error-envelope by _safe_run, but
    Router.close() must still run via the inner try/finally."""
    close_mock = AsyncMock()

    async def boom(*_a, **_kw):
        raise RuntimeError("explode")

    with patch("lightcrawl.cli.Router") as RouterCls:
        RouterCls.return_value.fetch = boom
        RouterCls.return_value.close = close_mock
        rc, out = _run(["fetch", "https://example.com/"])
    close_mock.assert_awaited_once()
    assert rc == 1
    assert out["error_code"] == "UNKNOWN"


def test_fetch_passes_wait_for_selector_through():
    captured = {}

    async def capture(req):
        captured["wait_for"] = req.wait_for
        captured["selector"] = req.selector
        return {"ok": True, "url": req.url, "final_url": req.url,
                "strategy_used": "browser", "title": "", "content": "",
                "content_truncated": False, "dump_path": None,
                "metadata": {}, "attempts": [], "headings": []}

    with patch("lightcrawl.cli.Router") as RouterCls:
        RouterCls.return_value.fetch = capture
        RouterCls.return_value.close = AsyncMock()
        rc, _ = _run([
            "fetch", "https://spa.example/",
            "--wait-for-selector", "main.loaded",
            "--selector", "article",
        ])
    assert rc == 0
    assert captured["wait_for"].selector == "main.loaded"
    assert captured["selector"] == "article"


def _capture_fetch_request(argv: list[str]) -> "object":
    """Run the CLI fetch with Router patched; return the FetchRequest the
    CLI built. Shared helper for the three remove_base64_images cases below."""
    captured = {}

    async def capture(req):
        captured["req"] = req
        return {"ok": True, "url": req.url, "final_url": req.url,
                "strategy_used": "http", "title": "", "content": "",
                "content_truncated": False, "dump_path": None,
                "metadata": {}, "attempts": [], "headings": []}

    with patch("lightcrawl.cli.Router") as RouterCls:
        RouterCls.return_value.fetch = capture
        RouterCls.return_value.close = AsyncMock()
        rc, _ = _run(argv)
    assert rc == 0
    return captured["req"]


def test_fetch_no_flag_uses_v03_default_true():
    """Regression for the v0.3 CLI bug: no flag must let FetchRequest's
    dataclass default (True) take effect, not be overridden by argparse
    store_true False. Failure mode: CLI users without the flag silently
    get v0.2 behavior, defeating the breaking change."""
    req = _capture_fetch_request(["fetch", "https://example.com/"])
    assert req.remove_base64_images is True


def test_fetch_explicit_flag_sets_true():
    req = _capture_fetch_request([
        "fetch", "https://example.com/", "--remove-base64-images",
    ])
    assert req.remove_base64_images is True


def test_fetch_no_flag_negation_sets_false():
    """BooleanOptionalAction auto-generates --no-remove-base64-images.
    Lets users explicitly restore v0.2 behavior — exactly the migration
    path documented in CHANGELOG.md for the breaking default flip."""
    req = _capture_fetch_request([
        "fetch", "https://example.com/", "--no-remove-base64-images",
    ])
    assert req.remove_base64_images is False


# -- search -----------------------------------------------------------------


def test_search_passes_args_through():
    captured = {}

    async def capture_search(req):
        captured["req"] = req
        return {
            "ok": True, "query": req.query, "backend_used": "fake",
            "depth_used": req.depth,
            "results": [],
            "metadata": {"elapsed_ms": 1, "estimated_cost_usd": 0, "result_count": 0},
        }

    with patch("lightcrawl.cli.SearchService") as SvcCls:
        SvcCls.return_value.search = capture_search
        SvcCls.return_value.close = AsyncMock()
        rc, out = _run([
            "search", "python asyncio",
            "--depth", "deep",
            "--backend", "brave",
            "--max-results", "7",
            "--profile", "twitter",
        ])
    assert rc == 0
    assert out["ok"] is True
    req = captured["req"]
    assert req.query == "python asyncio"
    assert req.depth == "deep"
    assert req.backend == "brave"
    assert req.max_results == 7
    assert req.profile == "twitter"


def test_search_failure_exits_one():
    async def fail_search(_req):
        return {
            "ok": False,
            "query": "x",
            "error_code": "RATE_LIMITED",
            "error_detail": "brave: 429",
            "attempts": [],
            "suggestions": [],
        }

    with patch("lightcrawl.cli.SearchService") as SvcCls:
        SvcCls.return_value.search = fail_search
        SvcCls.return_value.close = AsyncMock()
        rc, out = _run(["search", "x"])
    assert rc == 1
    assert out["error_code"] == "RATE_LIMITED"


# -- search-and-read --------------------------------------------------------


def test_search_and_read_passes_args_through():
    captured = {}

    async def capture(req):
        captured["req"] = req
        return {
            "ok": True, "query": req.query,
            "search_results": [], "fetched_pages": [], "fetch_failures": [],
            "metadata": {"search_elapsed_ms": 1, "fetch_elapsed_ms": 1,
                         "total_tokens_returned": 0},
        }

    with patch("lightcrawl.cli.SearchService") as SvcCls:
        SvcCls.return_value.search_and_read = capture
        SvcCls.return_value.close = AsyncMock()
        rc, _ = _run([
            "search-and-read", "what is X",
            "--read-top-n", "5",
            "--read-max-inline-tokens", "2000",
            "--timeout-ms", "90000",
        ])
    assert rc == 0
    req = captured["req"]
    assert req.query == "what is X"
    assert req.read_top_n == 5
    assert req.read_max_inline_tokens == 2000
    assert req.timeout_ms == 90_000


def test_search_and_read_accepts_max_results_alias():
    """`--max-results` is the conventional CLI flag name and was the most
    common wrong guess users made (issue #42). Accept it as an alias for
    `--read-top-n` so the command isn't gated on knowing the v0.2 name."""
    captured = {}

    async def capture(req):
        captured["req"] = req
        return {
            "ok": True, "query": req.query,
            "search_results": [], "fetched_pages": [], "fetch_failures": [],
            "metadata": {"search_elapsed_ms": 1, "fetch_elapsed_ms": 1,
                         "total_tokens_returned": 0},
        }

    with patch("lightcrawl.cli.SearchService") as SvcCls:
        SvcCls.return_value.search_and_read = capture
        SvcCls.return_value.close = AsyncMock()
        rc, _ = _run([
            "search-and-read", "what is X", "--max-results", "7",
        ])
    assert rc == 0
    assert captured["req"].read_top_n == 7


# -- auth (existing commands; smoke test the entry point still works) -------


def test_auth_list_empty_has_ok_envelope():
    """`auth list` must include `ok: true` so skills can branch on it
    uniformly across all commands."""
    rc, out = _run(["auth", "list"])
    assert rc == 0
    assert out == {"ok": True, "profiles": []}


def test_auth_show_wraps_single_profile_in_profiles_array():
    """`auth show <name>` must return the same shape as `auth list` —
    `{ok: true, profiles: [meta]}` — not a bare meta dict."""
    from lightcrawl import auth as auth_mod
    auth_mod.save_profile("twitter", {"cookies": [], "origins": []}, "x.com")

    rc, out = _run(["auth", "show", "twitter"])
    assert rc == 0
    assert out["ok"] is True
    assert isinstance(out["profiles"], list)
    assert len(out["profiles"]) == 1
    assert out["profiles"][0]["name"] == "twitter"
    assert out["profiles"][0]["bound_domain"] == "x.com"


def test_auth_show_missing_profile_returns_error_envelope():
    rc, out = _run(["auth", "show", "nope"])
    assert rc == 1
    assert out["ok"] is False
    assert out["error_code"] == "PROFILE_NOT_FOUND"


# -- safety net -------------------------------------------------------------


def test_unexpected_exception_converted_to_json_envelope():
    """A surprise exception (third-party bug, OOM, etc.) inside an async
    command must NOT print a Python traceback to stdout — it must come out
    as the same JSON error envelope as planned failures, so skills can
    parse every CLI invocation uniformly."""
    async def boom(*_a, **_kw):
        raise RuntimeError("kaboom")

    with patch("lightcrawl.cli.Router") as RouterCls:
        RouterCls.return_value.fetch = boom
        RouterCls.return_value.close = AsyncMock()
        rc, out = _run(["fetch", "https://example.com/"])
    assert rc == 1
    assert out["ok"] is False
    assert out["error_code"] == "UNKNOWN"
    assert "kaboom" in out["error_detail"]


def test_list_backends_calls_close_for_cleanup_uniformity():
    """`list-backends` now routes through the same try/finally as the
    other subcommands so SearchService.close() always runs, even if
    a future change makes the service hold a resource."""
    close_mock = AsyncMock()
    with patch("lightcrawl.cli.SearchService") as SvcCls:
        SvcCls.return_value.list_backends = lambda: []
        SvcCls.return_value.close = close_mock
        rc, _ = _run(["list-backends"])
    assert rc == 0
    close_mock.assert_awaited_once()


# -- map --------------------------------------------------------------------


def test_map_serializes_result_and_passes_flags():
    """The CLI's job is flag parsing + MapResult serialization; run_map is
    unit-tested separately in test_sitemap.py, so stub it here."""
    from lightcrawl.sitemap import MapResult, SitemapEntry

    res = MapResult(
        source="sitemap",
        urls=[SitemapEntry("https://ex.com/a", None, None, None)],
        count=1,
        notes=None,
    )
    fake = AsyncMock(return_value=res)
    with patch("lightcrawl.cli.sitemap.run_map", fake), \
         patch("lightcrawl.cli.Router") as RouterCls:
        RouterCls.return_value.close = AsyncMock()
        rc, out = _run(["map", "https://ex.com/", "--search", "docs", "--limit", "10"])
    assert rc == 0
    assert out["ok"] is True
    assert out["source"] == "sitemap"
    assert out["count"] == 1
    assert out["urls"][0]["url"] == "https://ex.com/a"
    assert "notes" not in out  # None notes are omitted from the envelope
    _, kwargs = fake.call_args
    assert kwargs["search_filter"] == "docs"
    assert kwargs["limit"] == 10
