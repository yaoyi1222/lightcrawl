from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from refetch import auth as auth_mod
from refetch.router import Router
from refetch.search.backends.base import BackendError
from refetch.search.service import (
    SearchAndReadRequest,
    SearchRequest,
    SearchService,
)
from refetch.search.types import SearchResult


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("refetch.paths.ROOT", tmp_path)
    monkeypatch.setattr("refetch.paths.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("refetch.paths.PROFILES", tmp_path / "profiles")
    monkeypatch.setattr("refetch.paths.LOGS", tmp_path / "logs")
    monkeypatch.setattr("refetch.content.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("refetch.search.service.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("refetch.auth.PROFILES", tmp_path / "profiles")
    (tmp_path / "dumps").mkdir(parents=True)
    (tmp_path / "profiles").mkdir(parents=True)


class FakeBackend:
    name = "fake"
    cost_per_call_usd = 0.001

    def __init__(self, results=None, raise_=None, configured=True):
        self._results = results or []
        self._raise = raise_
        self._configured = configured
        self.calls = 0

    def configured(self):
        return self._configured

    async def search(self, query, *, max_results, time_range=(None, None), timeout=10.0):
        self.calls += 1
        if self._raise:
            raise self._raise
        return self._results[:max_results]


def _svc(*backends, router: Router | None = None) -> SearchService:
    return SearchService(router=router or Router(), backends=list(backends))


async def test_search_no_backend_configured():
    svc = _svc(FakeBackend(configured=False))
    out = await svc.search(SearchRequest(query="x"))
    assert out["ok"] is False
    assert out["error_code"] == "NO_BACKEND_CONFIGURED"
    await svc.close()


async def test_search_empty_results():
    svc = _svc(FakeBackend(results=[]))
    out = await svc.search(SearchRequest(query="x"))
    assert out["ok"] is False
    assert out["error_code"] == "EMPTY_RESULTS"
    await svc.close()


async def test_search_rate_limited_passes_through():
    svc = _svc(FakeBackend(raise_=BackendError("RATE_LIMITED", "fake: 429")))
    out = await svc.search(SearchRequest(query="x"))
    assert out["ok"] is False
    assert out["error_code"] == "RATE_LIMITED"
    assert any("retry" in s for s in out["suggestions"])
    await svc.close()


async def test_search_returns_annotated_results():
    fake = FakeBackend(results=[
        SearchResult(rank=1, title="A", url="https://a.example/1",
                     snippet="snippet A " * 30, page_age_days=3),
        SearchResult(rank=2, title="B", url="https://b.example/2",
                     snippet="short", page_age_days=None),
    ])
    svc = _svc(fake)
    out = await svc.search(SearchRequest(query="x", depth="quick"))
    assert out["ok"] is True
    assert out["backend_used"] == "fake"
    assert len(out["results"]) == 2
    r0 = out["results"][0]
    assert r0["fetch_hint"] == {"needs_login": False, "cache_status": "cold"}
    assert "page_age_days" in r0
    await svc.close()


async def test_snippet_enhancement_from_dump(tmp_path):
    import hashlib
    url = "https://a.example/1"
    digest = hashlib.sha1(url.encode()).hexdigest()[:16]
    (tmp_path / "dumps" / f"{digest}.md").write_text(
        "First paragraph with substantial content describing the article.\n"
        "It is more than two hundred characters long so the enhancer can\n"
        "use it to extend the original short snippet returned by the backend.\n"
        "This is the body."
    )
    fake = FakeBackend(results=[
        SearchResult(rank=1, title="A", url=url, snippet="too short")
    ])
    svc = _svc(fake)
    out = await svc.search(SearchRequest(query="x"))
    assert out["results"][0]["fetch_hint"]["cache_status"] == "warm"
    assert len(out["results"][0]["snippet"]) > 50
    await svc.close()


async def test_needs_login_hint_when_profile_active(tmp_path):
    auth_mod.save_profile("twitter", {"cookies": [], "origins": []}, "x.com")
    fake = FakeBackend(results=[
        SearchResult(rank=1, title="T", url="https://x.com/foo/status/1", snippet="ok")
    ])
    svc = _svc(fake)
    out = await svc.search(SearchRequest(query="x"))
    assert out["results"][0]["fetch_hint"]["needs_login"] is True
    await svc.close()


async def test_list_backends_reports_configuration():
    svc = _svc(FakeBackend(configured=False), FakeBackend(configured=True))
    backends = svc.list_backends()
    # Both have name="fake"; we just want shape correctness here.
    assert all("name" in b and "configured" in b for b in backends)
    await svc.close()


async def test_search_and_read_enforces_url_provenance():
    """search_and_read must only fetch URLs that were in the search results."""
    fake = FakeBackend(results=[
        SearchResult(rank=1, title="A", url="https://a.example/1",
                     snippet="snip"),
    ])
    svc = _svc(fake)

    fake_fetch_calls = []

    async def fake_router_fetch(req):
        fake_fetch_calls.append(req.url)
        return {
            "ok": True, "url": req.url, "final_url": req.url,
            "strategy_used": "http", "title": "A", "content": "body",
            "content_truncated": False, "dump_path": None,
            "metadata": {"status_code": 200, "elapsed_ms": 10,
                         "needs_js_hint": False, "suggested_selectors": []},
            "attempts": [],
        }

    with patch.object(svc.router, "fetch", new=fake_router_fetch):
        out = await svc.search_and_read(
            SearchAndReadRequest(query="x", read_top_n=3)
        )

    assert out["ok"] is True
    assert len(fake_fetch_calls) == 1
    assert fake_fetch_calls[0] == "https://a.example/1"
    assert len(out["fetched_pages"]) == 1
    assert out["fetched_pages"][0]["content_markdown"] == "body"
    await svc.close()


async def test_search_and_read_records_fetch_failures():
    fake = FakeBackend(results=[
        SearchResult(rank=1, title="A", url="https://a.example/1", snippet="snip"),
        SearchResult(rank=2, title="B", url="https://b.example/2", snippet="snip"),
    ])
    svc = _svc(fake)

    async def fake_router_fetch(req):
        if "a.example" in req.url:
            return {
                "ok": True, "url": req.url, "final_url": req.url,
                "strategy_used": "http", "title": "A", "content": "ok",
                "content_truncated": False, "dump_path": None,
                "metadata": {"status_code": 200, "elapsed_ms": 1,
                             "needs_js_hint": False, "suggested_selectors": []},
                "attempts": [],
            }
        return {
            "ok": False, "url": req.url,
            "error_code": "BLOCKED_BY_CLOUDFLARE",
            "error_detail": "blocked",
            "attempts": [], "suggestions": [],
        }

    with patch.object(svc.router, "fetch", new=fake_router_fetch):
        out = await svc.search_and_read(SearchAndReadRequest(query="x", read_top_n=2))

    assert len(out["fetched_pages"]) == 1
    assert len(out["fetch_failures"]) == 1
    assert out["fetch_failures"][0]["error_code"] == "BLOCKED_BY_CLOUDFLARE"
    await svc.close()
