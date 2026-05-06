"""Offline tests for the bench report renderer (no network, no playwright)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench import report, tokens


def test_token_counter_works():
    assert tokens.count("") == 0
    assert tokens.count("hello world") > 0
    assert isinstance(tokens.strategy(), str)


def test_render_table_baseline_wins_savings():
    data = {
        "token_strategy": "test",
        "rows": [
            {
                "url": "https://example.com/a",
                "category": "wiki",
                "note": "x",
                "selector": "article",
                "outcomes": [
                    {
                        "mode": "baseline", "ok": True, "status_code": 200,
                        "strategy_used": "httpx-raw", "elapsed_ms": 100,
                        "tokens_returned": 10000, "tokens_full": 10000,
                        "truncated": False, "dump_path": None,
                        "error_code": None, "error_detail": None,
                    },
                    {
                        "mode": "plus_auto", "ok": True, "status_code": 200,
                        "strategy_used": "http", "elapsed_ms": 110,
                        "tokens_returned": 4000, "tokens_full": 4000,
                        "truncated": False, "dump_path": None,
                        "error_code": None, "error_detail": None,
                    },
                    {
                        "mode": "plus_selector", "ok": True, "status_code": 200,
                        "strategy_used": "http", "elapsed_ms": 105,
                        "tokens_returned": 1500, "tokens_full": 1500,
                        "truncated": False, "dump_path": None,
                        "error_code": None, "error_detail": None,
                    },
                ],
            },
        ],
    }
    md = report.render(data)
    assert "WebFetch token-consumption benchmark" in md
    assert "example.com" in md
    assert "↓60.0%" in md   # 10000 → 4000
    assert "↓85.0%" in md   # 10000 → 1500
    assert "Category roll-up" in md
    assert "Success rates" in md


def test_render_handles_baseline_failure():
    data = {
        "token_strategy": "test",
        "rows": [
            {
                "url": "https://blocked.example/", "category": "cloudflare",
                "note": "", "selector": None,
                "outcomes": [
                    {
                        "mode": "baseline", "ok": False, "status_code": 403,
                        "strategy_used": "httpx-raw", "elapsed_ms": 50,
                        "tokens_returned": 0, "tokens_full": 0,
                        "truncated": False, "dump_path": None,
                        "error_code": "BASELINE_FAIL", "error_detail": "HTTP 403",
                    },
                    {
                        "mode": "plus_auto", "ok": True, "status_code": 200,
                        "strategy_used": "http", "elapsed_ms": 300,
                        "tokens_returned": 800, "tokens_full": 800,
                        "truncated": False, "dump_path": None,
                        "error_code": None, "error_detail": None,
                    },
                ],
            },
        ],
    }
    md = report.render(data)
    assert "❌" in md
    assert "✅" in md
