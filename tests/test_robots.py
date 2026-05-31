"""robots.txt allow/disallow subsystem tests (v0.3 PR 6.1). Fully offline:
every fetch goes through ``Router.fetch`` → ``fetch_http.fetch``, patched with
a per-URL routing table. ``socket.gethostbyname`` is patched so the SSRF guard
sees a routable public IP. No network, no disk."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from lightcrawl import robots
from lightcrawl.fetch_http import HttpResult
from lightcrawl.router import Router


def _http(url: str, *, status: int = 200, text: str = "", ctype: str = "text/plain") -> HttpResult:
    return HttpResult(
        final_url=url, status_code=status, text=text,
        content_type=ctype, elapsed_ms=1,
    )


@contextmanager
def _routes(table: dict[str, HttpResult], counter: dict | None = None):
    """Patch the network so ``fetch_http.fetch(url, ...)`` returns a canned
    HttpResult per URL (trailing slash insensitive); unknown URLs 404. If
    ``counter`` is given, count fetches per URL."""
    def _fetch(url, **_kw):
        if counter is not None:
            counter[url] = counter.get(url, 0) + 1
        res = table.get(url) or table.get(url.rstrip("/"))
        if res is not None:
            return res
        return _http(url, status=404, text="Not Found")

    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", side_effect=_fetch):
        yield


@pytest.fixture
def router() -> Router:
    return Router()


_ROBOTS_WILDCARD = "User-agent: *\nDisallow: /private\n"

_ROBOTS_MULTI_GROUP = (
    "User-agent: googlebot\nDisallow: /\n\n"
    "User-agent: *\nDisallow: /private\n"
)


# -- fetch_robots ----------------------------------------------------------


async def test_disallow_blocks_matching_path(router):
    with _routes({
        "https://ex.com/robots.txt": _http("https://ex.com/robots.txt", text=_ROBOTS_WILDCARD),
    }):
        rules = await robots.fetch_robots("ex.com", router=router)
    assert rules.allows("https://ex.com/private/secret") is False
    assert rules.allows("https://ex.com/public/page") is True


async def test_wildcard_group_governs_default_ua(router):
    # Our default UA "*" must fall to the wildcard group, NOT the googlebot
    # group that disallows everything.
    with _routes({
        "https://ex.com/robots.txt": _http("https://ex.com/robots.txt", text=_ROBOTS_MULTI_GROUP),
    }):
        rules = await robots.fetch_robots("ex.com", router=router)
    assert rules.allows("https://ex.com/anything") is True
    assert rules.allows("https://ex.com/private/x") is False


async def test_missing_robots_is_fail_open(router):
    # robots.txt 404 → no restrictions.
    with _routes({}):
        rules = await robots.fetch_robots("ex.com", router=router)
    assert rules.allows("https://ex.com/private/x") is True


async def test_failed_fetch_is_fail_open(router):
    # Whole fetch fails (DNS) → permissive, never raises.
    import socket

    def _boom(_host):
        raise socket.gaierror("dns down")

    with patch("lightcrawl.url_safety.socket.gethostbyname", side_effect=_boom):
        rules = await robots.fetch_robots("ex.com", router=router)
    assert rules.allows("https://ex.com/private/x") is True


async def test_empty_robots_is_fail_open(router):
    with _routes({
        "https://ex.com/robots.txt": _http("https://ex.com/robots.txt", text=""),
    }):
        rules = await robots.fetch_robots("ex.com", router=router)
    assert rules.allows("https://ex.com/private/x") is True


# -- RobotsCache -----------------------------------------------------------


async def test_cache_fetches_host_once(router):
    counter: dict = {}
    with _routes({
        "https://ex.com/robots.txt": _http("https://ex.com/robots.txt", text=_ROBOTS_WILDCARD),
    }, counter=counter):
        cache = robots.RobotsCache(router=router)
        assert await cache.allows("https://ex.com/a") is True
        assert await cache.allows("https://ex.com/private/x") is False
        assert await cache.allows("https://ex.com/b") is True
    assert counter["https://ex.com/robots.txt"] == 1


async def test_cache_separates_hosts(router):
    with _routes({
        "https://a.com/robots.txt": _http("https://a.com/robots.txt", text="User-agent: *\nDisallow: /x\n"),
        "https://b.com/robots.txt": _http("https://b.com/robots.txt", text="User-agent: *\nDisallow: /y\n"),
    }):
        cache = robots.RobotsCache(router=router)
        assert await cache.allows("https://a.com/x") is False
        assert await cache.allows("https://a.com/y") is True
        assert await cache.allows("https://b.com/x") is True
        assert await cache.allows("https://b.com/y") is False


async def test_ignore_skips_fetch_and_allows_all(router):
    counter: dict = {}
    with _routes({
        "https://ex.com/robots.txt": _http("https://ex.com/robots.txt", text=_ROBOTS_WILDCARD),
    }, counter=counter):
        cache = robots.RobotsCache(router=router, ignore=True)
        assert await cache.allows("https://ex.com/private/x") is True
    assert counter == {}  # no robots.txt fetch performed


# -- RFC 9309 path matching (wildcards / longest-match / anchors) -----------


async def test_star_wildcard_in_path_is_honored(router):
    # `Disallow: /*.php` must block /script.php — the case the stdlib parser
    # silently allowed.
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt", text="User-agent: *\nDisallow: /*.php\n"),
    }):
        rules = await robots.fetch_robots("ex.com", router=router)
    assert rules.allows("https://ex.com/script.php") is False
    assert rules.allows("https://ex.com/page.html") is True


async def test_mid_path_wildcard_is_honored(router):
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt", text="User-agent: *\nDisallow: /*/admin\n"),
    }):
        rules = await robots.fetch_robots("ex.com", router=router)
    assert rules.allows("https://ex.com/foo/admin") is False
    assert rules.allows("https://ex.com/foo/public") is True


async def test_dollar_anchor_is_honored(router):
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt", text="User-agent: *\nDisallow: /path$\n"),
    }):
        rules = await robots.fetch_robots("ex.com", router=router)
    assert rules.allows("https://ex.com/path") is False
    assert rules.allows("https://ex.com/path/more") is True


async def test_longest_match_allow_overrides_broad_disallow(router):
    # Google's published idiom: broad Disallow, narrow Allow. Longest match wins.
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt",
            text="User-agent: *\nDisallow: /search\nAllow: /search/about\n"),
    }):
        rules = await robots.fetch_robots("ex.com", router=router)
    assert rules.allows("https://ex.com/search/about") is True
    assert rules.allows("https://ex.com/search/results") is False


async def test_allow_wins_equal_length_tie(router):
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt",
            text="User-agent: *\nDisallow: /a\nAllow: /a\n"),
    }):
        rules = await robots.fetch_robots("ex.com", router=router)
    assert rules.allows("https://ex.com/a") is True


async def test_bom_prefixed_robots_is_parsed(router):
    # A UTF-8 BOM must not swallow the first User-agent line.
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt", text="﻿User-agent: *\nDisallow: /private\n"),
    }):
        rules = await robots.fetch_robots("ex.com", router=router)
    assert rules.allows("https://ex.com/private/x") is False


async def test_cache_key_normalizes_host(router):
    # Uppercase host and an explicit default port must hit the same cache entry.
    counter: dict = {}
    with _routes({
        "https://ex.com/robots.txt": _http("https://ex.com/robots.txt", text=_ROBOTS_WILDCARD),
    }, counter=counter):
        cache = robots.RobotsCache(router=router)
        assert await cache.allows("https://EX.com/a") is True
        assert await cache.allows("https://ex.com:443/private/x") is False
    assert counter["https://ex.com/robots.txt"] == 1
