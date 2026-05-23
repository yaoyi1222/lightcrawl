"""Router cache aspect tests (v0.3 PR 2.3).

End-to-end coverage of the entry/exit hooks in ``Router.fetch``. Uses
the same monkeypatch pattern as ``tests/test_router.py`` to keep
everything offline: ``fetch_http.fetch`` returns a canned HttpResult,
``socket.gethostbyname`` resolves to a routable IP, and the Router's
cache is pinned to a ``tmp_path`` directory via the constructor's
``cache=`` injection.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from lightcrawl import cache as cache_mod
from lightcrawl.cache import Cache
from lightcrawl.errors import ErrorCode
from lightcrawl.fetch_http import HttpResult
from lightcrawl.router import FetchRequest, Router


@pytest.fixture
def fake_clock(monkeypatch):
    clock = [1_000_000]
    monkeypatch.setattr(cache_mod, "time_ms", lambda: clock[0])
    return clock


@pytest.fixture
def router(tmp_path, monkeypatch) -> Router:
    """Router whose cache lives under ``tmp_path/cache`` so every test
    starts from an empty cache and writes never escape the temp dir."""
    # Match the isolation the existing test_router.py applies — DUMPS /
    # PROFILES / LOGS all under tmp_path so dump writes during ``store``
    # don't escape either.
    monkeypatch.setattr("lightcrawl.paths.ROOT", tmp_path)
    monkeypatch.setattr("lightcrawl.paths.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("lightcrawl.paths.PROFILES", tmp_path / "profiles")
    monkeypatch.setattr("lightcrawl.paths.LOGS", tmp_path / "logs")
    monkeypatch.setattr("lightcrawl.content.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("lightcrawl.auth.PROFILES", tmp_path / "profiles")
    (tmp_path / "dumps").mkdir(parents=True, exist_ok=True)
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    return Router(cache=Cache(root=tmp_path / "cache"))


_OK_HTML = (
    "<html><head><title>T</title></head><body>"
    "<article><h1>Hi</h1>"
    "<p>body text long enough to extract properly with readability "
    "and then markdownify it nicely. The router's escalation gate "
    "treats html shorter than 200 bytes as a JS shell, so we pad here "
    "to comfortably exceed that threshold and stay on the L1 path.</p>"
    "</article></body></html>"
)


def _ok_http_result(*, body: str = _OK_HTML) -> HttpResult:
    return HttpResult(
        final_url="https://example.com/",
        status_code=200,
        text=body,
        content_type="text/html",
        elapsed_ms=10,
    )


# -- entry hook: cache miss → goes to network ----------------------------


async def test_no_cache_lookup_when_max_age_ms_unset(router: Router, fake_clock):
    """Default FetchRequest has max_age_ms=None and cache_only=False —
    the router must not touch the cache at all (v0.2-compatible)."""
    fake = _ok_http_result()
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake) as fetch_mock:
        out = await router.fetch(FetchRequest(url="https://example.com/"))
    assert out["ok"] is True
    assert out["strategy_used"] == "http"
    assert "cache_hit" not in out
    assert fetch_mock.called


async def test_cache_only_empty_returns_cache_miss(router: Router, fake_clock):
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch") as fetch_mock:
        out = await router.fetch(
            FetchRequest(url="https://example.com/", cache_only=True),
        )
    assert out["ok"] is False
    assert out["error_code"] == ErrorCode.CACHE_MISS.value
    assert fetch_mock.called is False  # never hit network


# -- write path: store_in_cache=True --------------------------------------


async def test_store_in_cache_persists_response(router: Router, fake_clock):
    fake = _ok_http_result()
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake):
        out = await router.fetch(
            FetchRequest(url="https://example.com/", store_in_cache=True),
        )
    assert out["ok"] is True
    # And the cache now has the entry.
    hit = router.cache.lookup("https://example.com/", profile=None, max_age_ms=60_000)
    assert hit is not None
    assert "Hi" in hit.markdown
    assert hit.title == "T"  # from <title>T</title> in _OK_HTML


async def test_no_cache_disables_write(router: Router, fake_clock):
    """--no-cache must veto store_in_cache even if both are present —
    CLI argparse will normally enforce the mutex, but the router still
    treats no_cache as authoritative if both somehow arrive."""
    fake = _ok_http_result()
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake):
        await router.fetch(
            FetchRequest(
                url="https://example.com/",
                store_in_cache=True, no_cache=True,
            ),
        )
    assert router.cache.stats().entry_count == 0


# -- read path: max_age_ms hit --------------------------------------------


async def test_max_age_hit_returns_cached_body(router: Router, fake_clock):
    """First call populates the cache, second call within budget reads
    it back without hitting the network."""
    fake = _ok_http_result()
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake) as fetch_mock:
        await router.fetch(FetchRequest(
            url="https://example.com/", store_in_cache=True,
        ))
        assert fetch_mock.call_count == 1
        fake_clock[0] += 1_000  # 1 s later
        out = await router.fetch(FetchRequest(
            url="https://example.com/", max_age_ms=60_000,
        ))
    assert out["ok"] is True
    assert out["strategy_used"] == "cache"
    assert out["cache_hit"] is True
    assert out["cache_age_ms"] == 1_000
    assert "Hi" in out["content"]
    # Network was only called once — second fetch was served from cache.
    assert fetch_mock.call_count == 1


async def test_max_age_miss_when_expired(router: Router, fake_clock):
    fake = _ok_http_result()
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake) as fetch_mock:
        await router.fetch(FetchRequest(
            url="https://example.com/", store_in_cache=True,
        ))
        fake_clock[0] += 120_000  # 2 min later, exceeds 60 s budget
        out = await router.fetch(FetchRequest(
            url="https://example.com/", max_age_ms=60_000,
        ))
    assert out["strategy_used"] == "http"
    assert fetch_mock.call_count == 2


async def test_no_cache_skips_read_even_when_hot(router: Router, fake_clock):
    """A populated cache plus ``--max-age`` would normally hit, but
    ``--no-cache`` is authoritative."""
    fake = _ok_http_result()
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake) as fetch_mock:
        await router.fetch(FetchRequest(
            url="https://example.com/", store_in_cache=True,
        ))
        out = await router.fetch(FetchRequest(
            url="https://example.com/",
            max_age_ms=60_000,  # would normally hit
            no_cache=True,
        ))
    assert out["strategy_used"] == "http"
    assert fetch_mock.call_count == 2


# -- cache_only after a real fetch ----------------------------------------


async def test_cache_only_hits_after_populated(router: Router, fake_clock):
    fake = _ok_http_result()
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake) as fetch_mock:
        await router.fetch(FetchRequest(
            url="https://example.com/", store_in_cache=True,
        ))
        fake_clock[0] += 24 * 3600 * 1000  # one full day later
        out = await router.fetch(FetchRequest(
            url="https://example.com/", cache_only=True,
        ))
    assert out["ok"] is True
    assert out["strategy_used"] == "cache"
    assert out["cache_age_ms"] >= 24 * 3600 * 1000  # any age accepted
    assert fetch_mock.call_count == 1  # cache_only never went back to net


# -- profile dimension (security boundary) --------------------------------


async def test_profile_bound_cache_does_not_leak_to_anonymous(
    router: Router, fake_clock, tmp_path,
):
    """Cache an entry under profile=twitter, then try to read it with
    profile=None. Must miss — same URL, different cache key. Design §5.2 A2."""
    from lightcrawl import auth as auth_mod
    auth_mod.save_profile("twitter", {"cookies": [], "origins": []}, "x.com")

    fake = _ok_http_result()
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake), \
         patch("lightcrawl.fetch_browser.fetch", return_value=None):
        # Authed path uses the browser, but we never actually go to network
        # for THIS test — we just store directly to populate the profile entry.
        router.cache.store(
            "https://x.com/private", profile="twitter",
            response={
                "ok": True, "url": "https://x.com/private",
                "final_url": "https://x.com/private",
                "title": "Private", "content": "secret body",
                "content_truncated": False, "status_code": 200,
                "headers": {}, "headings": [], "metadata": {},
            },
        )
        # No-profile lookup must miss.
        out = await router.fetch(FetchRequest(
            url="https://x.com/private", cache_only=True,
        ))
    assert out["ok"] is False
    assert out["error_code"] == ErrorCode.CACHE_MISS.value


# -- failures don't poison cache ------------------------------------------


async def test_failed_fetch_does_not_write_to_cache(router: Router, fake_clock):
    """A failure envelope must NOT be cached — only ``ok=true`` writes."""
    from lightcrawl.errors import FetchError
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", side_effect=FetchError(
             ErrorCode.DNS_FAILED, "host not resolvable",
         )):
        out = await router.fetch(FetchRequest(
            url="https://example.com/", store_in_cache=True,
        ))
    assert out["ok"] is False
    assert router.cache.stats().entry_count == 0
