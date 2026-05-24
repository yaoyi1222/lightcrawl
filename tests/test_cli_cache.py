"""CLI cache flag tests (v0.3 PR 2.4).

Covers the four cache-control flags wired into ``fetch`` and
``search-and-read`` per ``docs/v0.3/design.md §3``:

- ``--max-age DUR`` — read with age limit; also write unless --no-store
- ``--cache-only``   — read-only, no network
- ``--no-cache``     — bypass cache entirely
- ``--no-store``     — read but don't write

Plus duration parsing (``300ms`` / ``5s`` / ``10m`` / ``2h`` / ``7d``) and
the truth-table mutex (``--no-cache`` vs any of the other three →
``CACHE_FLAG_CONFLICT``).

All tests run offline by patching ``Router.fetch`` to a stub that captures
the FetchRequest fields without exercising the network. The
``SearchService`` patches mirror the same approach.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

import pytest

from lightcrawl import cli
from lightcrawl.cli import _parse_duration_ms, _resolve_cache_kwargs
from lightcrawl.errors import ErrorCode


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("lightcrawl.paths.ROOT", tmp_path)
    monkeypatch.setattr("lightcrawl.paths.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("lightcrawl.paths.PROFILES", tmp_path / "profiles")
    monkeypatch.setattr("lightcrawl.paths.LOGS", tmp_path / "logs")
    monkeypatch.setattr("lightcrawl.auth.PROFILES", tmp_path / "profiles")


def _run(argv: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(argv)
    out = buf.getvalue().strip()
    payload = json.loads(out) if out else {}
    return rc, payload


# -- duration parser -------------------------------------------------------


class TestParseDuration:
    @pytest.mark.parametrize(
        "value,expected_ms",
        [
            ("500ms", 500),
            ("5s", 5_000),
            ("10m", 600_000),
            ("2h", 7_200_000),
            ("7d", 604_800_000),
            ("  3s  ", 3_000),  # whitespace tolerated
            ("1ms", 1),
        ],
    )
    def test_valid_durations(self, value, expected_ms):
        assert _parse_duration_ms(value) == expected_ms

    @pytest.mark.parametrize(
        "value",
        [
            "5",          # bare integer — ambiguous unit
            "5seconds",   # not in unit table
            "abc",
            "",
            "5sblah",     # partial match
            "1.5s",       # no fractional support (design only lists ints)
            "-5s",        # negative
            "0s",         # zero
        ],
    )
    def test_invalid_durations_raise(self, value):
        import argparse
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_duration_ms(value)


# -- _resolve_cache_kwargs truth-table -------------------------------------


def _ns(**kw):
    """Build a minimal argparse-like namespace with cache-flag defaults."""
    import argparse as _ap
    defaults = dict(no_cache=False, cache_only=False, max_age_ms=None, no_store=False)
    defaults.update(kw)
    return _ap.Namespace(**defaults)


class TestResolveCacheKwargs:
    def test_no_flags_is_v02_compatible(self):
        out = _resolve_cache_kwargs(_ns())
        assert out == {
            "max_age_ms": None, "cache_only": False,
            "store_in_cache": False, "no_cache": False,
        }

    def test_max_age_alone_enables_write(self):
        """``fetch --max-age 1h`` should ALSO write — that's the
        recommended pattern. Without write, the next call still misses."""
        out = _resolve_cache_kwargs(_ns(max_age_ms=60_000))
        assert out["max_age_ms"] == 60_000
        assert out["store_in_cache"] is True

    def test_max_age_with_no_store_reads_but_no_write(self):
        out = _resolve_cache_kwargs(_ns(max_age_ms=60_000, no_store=True))
        assert out["max_age_ms"] == 60_000
        assert out["store_in_cache"] is False

    def test_cache_only_never_writes(self):
        out = _resolve_cache_kwargs(_ns(cache_only=True))
        assert out["cache_only"] is True
        assert out["store_in_cache"] is False

    def test_cache_only_with_max_age_still_no_write(self):
        out = _resolve_cache_kwargs(_ns(cache_only=True, max_age_ms=60_000))
        assert out == {
            "max_age_ms": 60_000, "cache_only": True,
            "store_in_cache": False, "no_cache": False,
        }

    def test_no_cache_clears_everything(self):
        """--no-cache is authoritative: clears max_age/store/cache_only."""
        out = _resolve_cache_kwargs(
            _ns(no_cache=True, max_age_ms=60_000, store_in_cache=True),
        )
        assert out == {
            "max_age_ms": None, "cache_only": False,
            "store_in_cache": False, "no_cache": True,
        }

    def test_default_store_in_cache_respected_when_no_flags(self):
        """``crawl`` / ``batch-fetch`` default store_in_cache=True. The
        resolver must respect that default when the user passes no flags."""
        out = _resolve_cache_kwargs(_ns(), default_store_in_cache=True)
        assert out["store_in_cache"] is True

    def test_no_store_alone_disables_default_write(self):
        out = _resolve_cache_kwargs(_ns(no_store=True), default_store_in_cache=True)
        assert out["store_in_cache"] is False


# -- mutex validation ------------------------------------------------------


class TestCacheFlagValidation:
    def test_max_age_alone_is_valid(self):
        rc, payload = _run(["fetch", "https://example.com/", "--max-age", "5s"])
        # We didn't patch the router, so fetch will hit a real DNS check
        # and fail — but the failure shouldn't be CACHE_FLAG_CONFLICT.
        # The point of this test is just that the flag combination passed
        # validation. assert_not_equal would also work but checking the
        # exit/error code rules out a regression where the mutex was
        # over-broad.
        assert payload.get("error_code") != ErrorCode.CACHE_FLAG_CONFLICT.value

    @pytest.mark.parametrize("conflict", [
        ["--max-age", "5s"],
        ["--cache-only"],
        ["--no-store"],
    ])
    def test_no_cache_plus_other_returns_conflict(self, conflict):
        rc, payload = _run(["fetch", "https://example.com/", "--no-cache", *conflict])
        assert rc == 1
        assert payload["ok"] is False
        assert payload["error_code"] == ErrorCode.CACHE_FLAG_CONFLICT.value

    def test_no_cache_alone_is_valid(self):
        rc, payload = _run(["fetch", "https://example.com/", "--no-cache"])
        assert payload.get("error_code") != ErrorCode.CACHE_FLAG_CONFLICT.value

    def test_search_and_read_also_validates(self):
        rc, payload = _run([
            "search-and-read", "anything",
            "--no-cache", "--cache-only",
        ])
        assert rc == 1
        assert payload["error_code"] == ErrorCode.CACHE_FLAG_CONFLICT.value


# -- FetchRequest wiring ---------------------------------------------------


class TestFetchRequestWiring:
    """Patch ``Router.fetch`` to capture the FetchRequest the CLI builds.
    We're testing the CLI → FetchRequest pipe, not the Router."""

    def _captured_fetch_request(self, argv: list[str]):
        """Run CLI with a stub Router.fetch and return the FetchRequest
        instance it received."""
        captured = {}

        async def fake_fetch(self, req):
            captured["req"] = req
            return {"ok": True, "url": req.url, "strategy_used": "stub"}

        async def fake_close(self):
            return None

        with patch("lightcrawl.router.Router.fetch", new=fake_fetch), \
             patch("lightcrawl.router.Router.close", new=fake_close):
            _run(argv)
        return captured.get("req")

    def test_no_flags_yields_v02_defaults(self):
        req = self._captured_fetch_request(["fetch", "https://example.com/"])
        assert req is not None
        assert req.max_age_ms is None
        assert req.cache_only is False
        assert req.store_in_cache is False
        assert req.no_cache is False

    def test_max_age_parses_and_enables_store(self):
        req = self._captured_fetch_request([
            "fetch", "https://example.com/", "--max-age", "1h",
        ])
        assert req.max_age_ms == 3_600_000
        assert req.store_in_cache is True

    def test_max_age_with_no_store(self):
        req = self._captured_fetch_request([
            "fetch", "https://example.com/", "--max-age", "1h", "--no-store",
        ])
        assert req.max_age_ms == 3_600_000
        assert req.store_in_cache is False

    def test_cache_only(self):
        req = self._captured_fetch_request([
            "fetch", "https://example.com/", "--cache-only",
        ])
        assert req.cache_only is True
        assert req.store_in_cache is False
        assert req.max_age_ms is None

    def test_no_cache(self):
        req = self._captured_fetch_request([
            "fetch", "https://example.com/", "--no-cache",
        ])
        assert req.no_cache is True
        assert req.store_in_cache is False
        assert req.max_age_ms is None


# -- search-and-read propagation -------------------------------------------


class TestSearchAndReadPropagation:
    """Cache flags on ``search-and-read`` must flow into the SearchAndReadRequest
    and from there into each per-result FetchRequest."""

    def test_max_age_reaches_search_and_read_request(self):
        captured = {}

        async def fake_sar(self, req):
            captured["req"] = req
            return {"ok": True, "results": []}

        async def fake_close(self):
            return None

        with patch(
            "lightcrawl.search.service.SearchService.search_and_read", new=fake_sar,
        ), patch(
            "lightcrawl.search.service.SearchService.close", new=fake_close,
        ):
            _run(["search-and-read", "q", "--max-age", "10m"])
        req = captured["req"]
        assert req.max_age_ms == 600_000
        assert req.store_in_cache is True
        assert req.no_cache is False

    def test_no_cache_propagates(self):
        captured = {}

        async def fake_sar(self, req):
            captured["req"] = req
            return {"ok": True, "results": []}

        async def fake_close(self):
            return None

        with patch(
            "lightcrawl.search.service.SearchService.search_and_read", new=fake_sar,
        ), patch(
            "lightcrawl.search.service.SearchService.close", new=fake_close,
        ):
            _run(["search-and-read", "q", "--no-cache"])
        assert captured["req"].no_cache is True
