from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

import pytest

from refetch import cli


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # All CLI commands call ensure_dirs() and may write profiles/dumps.
    monkeypatch.setattr("refetch.paths.ROOT", tmp_path)
    monkeypatch.setattr("refetch.paths.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("refetch.paths.PROFILES", tmp_path / "profiles")
    monkeypatch.setattr("refetch.paths.LOGS", tmp_path / "logs")
    monkeypatch.setattr("refetch.auth.PROFILES", tmp_path / "profiles")


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
    with patch("refetch.cli.Router") as RouterCls:
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
    with patch("refetch.cli.Router") as RouterCls:
        RouterCls.return_value.fetch = fake
        RouterCls.return_value.close = AsyncMock()
        rc, out = _run(["fetch", "https://blocked.example/"])
    assert rc == 1
    assert out["error_code"] == "BLOCKED_BY_CLOUDFLARE"


def test_fetch_closes_router_even_on_failure():
    """We always tear down the BrowserPool — otherwise a one-shot CLI
    invocation leaks a Chromium subprocess on exit."""
    close_mock = AsyncMock()

    async def boom(*_a, **_kw):
        raise RuntimeError("explode")

    with patch("refetch.cli.Router") as RouterCls:
        RouterCls.return_value.fetch = boom
        RouterCls.return_value.close = close_mock
        with pytest.raises(RuntimeError):
            _run(["fetch", "https://example.com/"])
    close_mock.assert_awaited_once()


def test_fetch_passes_wait_for_selector_through():
    captured = {}

    async def capture(req):
        captured["wait_for"] = req.wait_for
        captured["selector"] = req.selector
        return {"ok": True, "url": req.url, "final_url": req.url,
                "strategy_used": "browser", "title": "", "content": "",
                "content_truncated": False, "dump_path": None,
                "metadata": {}, "attempts": [], "headings": []}

    with patch("refetch.cli.Router") as RouterCls:
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

    with patch("refetch.cli.SearchService") as SvcCls:
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

    with patch("refetch.cli.SearchService") as SvcCls:
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

    with patch("refetch.cli.SearchService") as SvcCls:
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


# -- auth (existing commands; smoke test the entry point still works) -------


def test_auth_list_empty():
    rc, out = _run(["auth", "list"])
    assert rc == 0
    assert out == {"profiles": []}
