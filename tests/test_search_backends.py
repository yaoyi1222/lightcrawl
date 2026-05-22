"""HTTP-mocked unit tests for SerperBackend and TavilyBackend.

Uses httpx.MockTransport (built-in) so we exercise the request construction
and response parsing without hitting the network.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from lightcrawl.search.backends.base import BackendError
from lightcrawl.search.backends.serper import SerperBackend
from lightcrawl.search.backends.tavily import TavilyBackend


def _mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# -- SerperBackend ----------------------------------------------------------


async def test_serper_happy_path():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.content.decode())
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "Result A",
                        "link": "https://a.example/1",
                        "snippet": "snippet A " * 30,
                        "date": "2 days ago",
                        "position": 1,
                    },
                    {
                        "title": "Result B",
                        "link": "https://b.example/2",
                        "snippet": "snippet B",
                        "position": 2,
                    },
                    {
                        # Missing link → must be filtered out
                        "title": "ghost",
                        "snippet": "no url",
                    },
                ]
            },
        )

    backend = SerperBackend(api_key="fake-key", transport=_mock(handler))
    results = await backend.search("hello world", max_results=10)

    assert captured["url"] == "https://google.serper.dev/search"
    assert captured["headers"]["x-api-key"] == "fake-key"
    assert captured["body"]["q"] == "hello world"
    assert captured["body"]["num"] == 10
    assert "tbs" not in captured["body"]

    assert len(results) == 2
    assert results[0].rank == 1
    assert results[0].url == "https://a.example/1"
    assert results[0].title == "Result A"
    assert results[0].page_age_days == 2
    assert results[1].rank == 2
    assert results[1].page_age_days is None


async def test_serper_429_raises_rate_limited():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    backend = SerperBackend(api_key="fake-key", transport=_mock(handler))
    with pytest.raises(BackendError) as exc:
        await backend.search("x", max_results=5)
    assert exc.value.code == "RATE_LIMITED"


async def test_serper_401_raises_no_backend_configured():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    backend = SerperBackend(api_key="fake-key", transport=_mock(handler))
    with pytest.raises(BackendError) as exc:
        await backend.search("x", max_results=5)
    assert exc.value.code == "NO_BACKEND_CONFIGURED"


async def test_serper_time_range_after_only_maps_to_qdr():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode())
        return httpx.Response(200, json={"organic": []})

    backend = SerperBackend(api_key="k", transport=_mock(handler))
    after = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
    await backend.search("x", max_results=5, time_range=(after, None))

    # 3 days ago → "qdr:w" (≤7-day bucket)
    assert captured["body"].get("tbs") == "qdr:w"


async def test_serper_time_range_with_both_bounds_uses_cdr():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode())
        return httpx.Response(200, json={"organic": []})

    backend = SerperBackend(api_key="k", transport=_mock(handler))
    await backend.search(
        "x",
        max_results=5,
        time_range=("2024-01-01", "2024-12-31"),
    )
    tbs = captured["body"].get("tbs")
    assert tbs is not None
    assert tbs.startswith("cdr:1,cd_min:01/01/2024,cd_max:12/31/2024")


# -- TavilyBackend ----------------------------------------------------------


async def test_tavily_happy_path():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.content.decode())
        return httpx.Response(
            200,
            json={
                "query": "hello world",
                "results": [
                    {
                        "title": "Result A",
                        "url": "https://a.example/1",
                        "content": "long llm-tuned snippet " * 20,
                        "score": 0.95,
                        "published_date": (
                            datetime.now(timezone.utc) - timedelta(days=5)
                        ).isoformat(),
                    },
                    {
                        "title": "Result B",
                        "url": "https://b.example/2",
                        "content": "shorter content",
                        "score": 0.5,
                    },
                ],
            },
        )

    backend = TavilyBackend(api_key="tvly-fake", transport=_mock(handler))
    results = await backend.search("hello world", max_results=10)

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["headers"]["authorization"] == "Bearer tvly-fake"
    assert captured["body"]["query"] == "hello world"
    assert captured["body"]["search_depth"] == "basic"
    assert captured["body"]["include_raw_content"] is False
    assert captured["body"]["include_answer"] is False
    assert "days" not in captured["body"]

    assert len(results) == 2
    assert results[0].url == "https://a.example/1"
    assert "llm-tuned snippet" in results[0].snippet
    assert results[0].page_age_days == 5
    assert results[1].page_age_days is None


async def test_tavily_429_raises_rate_limited():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "Too many requests"})

    backend = TavilyBackend(api_key="k", transport=_mock(handler))
    with pytest.raises(BackendError) as exc:
        await backend.search("x", max_results=5)
    assert exc.value.code == "RATE_LIMITED"


async def test_tavily_401_raises_no_backend_configured():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Invalid API key"})

    backend = TavilyBackend(api_key="k", transport=_mock(handler))
    with pytest.raises(BackendError) as exc:
        await backend.search("x", max_results=5)
    assert exc.value.code == "NO_BACKEND_CONFIGURED"


async def test_tavily_time_range_after_only_maps_to_days():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode())
        return httpx.Response(200, json={"results": []})

    backend = TavilyBackend(api_key="k", transport=_mock(handler))
    after = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    await backend.search("x", max_results=5, time_range=(after, None))

    assert captured["body"].get("days") == 10


async def test_tavily_configured_state(monkeypatch, tmp_path):
    assert TavilyBackend(api_key="x").configured() is True
    # When no explicit key is given and no env/config files exist, configured() is False
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert TavilyBackend(api_key=None).configured() is False
