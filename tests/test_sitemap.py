"""Sitemap discovery + parse + `run_map` tests (v0.3 PR 4).

Fully offline: every fetch goes through ``Router.fetch`` → ``fetch_http.fetch``,
which we patch with a tiny routing table keyed on URL. ``socket.gethostbyname``
is patched so the SSRF guard sees a routable public IP. No network, no disk.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import pytest

from lightcrawl import sitemap
from lightcrawl.errors import ErrorCode, FetchError
from lightcrawl.fetch_http import HttpResult
from lightcrawl.router import Router


def _http(url: str, *, status: int = 200, text: str = "", ctype: str = "text/html") -> HttpResult:
    return HttpResult(
        final_url=url, status_code=status, text=text,
        content_type=ctype, elapsed_ms=1,
    )


@contextmanager
def _routes(table: dict[str, HttpResult]):
    """Patch the network so ``fetch_http.fetch(url, ...)`` returns a canned
    HttpResult per URL (trailing slash insensitive); unknown URLs 404."""
    def _fetch(url, **_kw):
        res = table.get(url) or table.get(url.rstrip("/"))
        if res is not None:
            return res
        return _http(url, status=404, text="<html><body>Not Found</body></html>")

    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", side_effect=_fetch):
        yield


@pytest.fixture
def router() -> Router:
    return Router()


def _homepage(links_html: str) -> str:
    """Wrap anchor markup in a realistically-sized page. A sub-200-byte body
    trips the router's "tiny body → needs JS" browser escalation; real
    homepages never do, so pad with enough visible text to stay on L1."""
    filler = "<h1>Example</h1><p>" + ("Welcome to the homepage. " * 6) + "</p>"
    return f"<html><head><title>Example</title></head><body>{filler}{links_html}</body></html>"


_URLSET_NS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    '<url><loc>https://ex.com/a</loc><lastmod>2024-01-02</lastmod>'
    '<changefreq>daily</changefreq><priority>0.8</priority></url>'
    '<url><loc>https://ex.com/b</loc></url>'
    '</urlset>'
)

_URLSET_NO_NS = (
    '<urlset>'
    '<url><loc>https://ex.com/x</loc></url>'
    '<url><loc>https://ex.com/y</loc></url>'
    '</urlset>'
)

_ROBOTS_WITH_SITEMAPS = (
    "User-agent: *\nDisallow: /private\n"
    "Sitemap: https://ex.com/sitemap.xml\n"
    "sitemap: https://ex.com/sitemap-news.xml\n"
)


# -- discover_sitemaps -----------------------------------------------------


async def test_discover_reads_sitemap_lines_from_robots(router):
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt", text=_ROBOTS_WITH_SITEMAPS, ctype="text/plain",
        ),
    }):
        found = await sitemap.discover_sitemaps("https://ex.com/", router=router)
    assert found == [
        "https://ex.com/sitemap.xml",
        "https://ex.com/sitemap-news.xml",
    ]


async def test_discover_probes_well_known_paths_when_robots_silent(router):
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt", text="User-agent: *\nDisallow:\n", ctype="text/plain",
        ),
        "https://ex.com/sitemap.xml": _http(
            "https://ex.com/sitemap.xml", text=_URLSET_NS, ctype="application/xml",
        ),
        # /sitemap_index.xml is absent → 404, must be skipped
    }):
        found = await sitemap.discover_sitemaps("https://ex.com/", router=router)
    assert found == ["https://ex.com/sitemap.xml"]


async def test_discover_skips_404_probe_pages(router):
    # robots 404 AND both well-known paths 404 → nothing discovered.
    with _routes({}):
        found = await sitemap.discover_sitemaps("https://ex.com/", router=router)
    assert found == []


# -- parse_sitemap ---------------------------------------------------------


async def test_parse_urlset_with_namespace(router):
    with _routes({
        "https://ex.com/sitemap.xml": _http(
            "https://ex.com/sitemap.xml", text=_URLSET_NS, ctype="application/xml",
        ),
    }):
        entries = await sitemap.parse_sitemap("https://ex.com/sitemap.xml", router=router)
    assert [e.url for e in entries] == ["https://ex.com/a", "https://ex.com/b"]
    assert entries[0].lastmod == datetime(2024, 1, 2)
    assert entries[0].changefreq == "daily"
    assert entries[0].priority == 0.8
    assert entries[1].lastmod is None and entries[1].priority is None


async def test_parse_urlset_without_namespace(router):
    with _routes({
        "https://ex.com/sitemap.xml": _http(
            "https://ex.com/sitemap.xml", text=_URLSET_NO_NS, ctype="application/xml",
        ),
    }):
        entries = await sitemap.parse_sitemap("https://ex.com/sitemap.xml", router=router)
    assert [e.url for e in entries] == ["https://ex.com/x", "https://ex.com/y"]


async def test_parse_sitemap_index_recurses_into_children(router):
    index = (
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<sitemap><loc>https://ex.com/sm1.xml</loc></sitemap>'
        '<sitemap><loc>https://ex.com/sm2.xml</loc></sitemap>'
        '</sitemapindex>'
    )
    sm2 = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://ex.com/c</loc></url></urlset>'
    )
    with _routes({
        "https://ex.com/sitemap_index.xml": _http("https://ex.com/sitemap_index.xml", text=index, ctype="application/xml"),
        "https://ex.com/sm1.xml": _http("https://ex.com/sm1.xml", text=_URLSET_NS, ctype="application/xml"),
        "https://ex.com/sm2.xml": _http("https://ex.com/sm2.xml", text=sm2, ctype="application/xml"),
    }):
        entries = await sitemap.parse_sitemap("https://ex.com/sitemap_index.xml", router=router)
    assert [e.url for e in entries] == [
        "https://ex.com/a", "https://ex.com/b", "https://ex.com/c",
    ]


async def test_parse_sitemap_honors_max_entries(router):
    big = "<urlset>" + "".join(
        f"<url><loc>https://ex.com/p{i}</loc></url>" for i in range(5)
    ) + "</urlset>"
    with _routes({
        "https://ex.com/sitemap.xml": _http("https://ex.com/sitemap.xml", text=big, ctype="application/xml"),
    }):
        entries = await sitemap.parse_sitemap(
            "https://ex.com/sitemap.xml", router=router, max_entries=2,
        )
    assert len(entries) == 2


async def test_parse_malformed_xml_raises_sitemap_parse_error(router):
    with _routes({
        "https://ex.com/sitemap.xml": _http(
            "https://ex.com/sitemap.xml", text="<urlset><url><loc>oops",
            ctype="application/xml",
        ),
    }):
        with pytest.raises(FetchError) as ei:
            await sitemap.parse_sitemap("https://ex.com/sitemap.xml", router=router)
    assert ei.value.code == ErrorCode.SITEMAP_PARSE_ERROR


# -- run_map (end to end) --------------------------------------------------


async def test_run_map_sitemap_source(router):
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt",
            text="Sitemap: https://ex.com/sitemap.xml\n", ctype="text/plain",
        ),
        "https://ex.com/sitemap.xml": _http(
            "https://ex.com/sitemap.xml", text=_URLSET_NS, ctype="application/xml",
        ),
    }):
        res = await sitemap.run_map(
            "https://ex.com/", search_filter=None, limit=None, router=router,
        )
    assert res.source == "sitemap"
    assert res.count == 2
    assert [e.url for e in res.urls] == ["https://ex.com/a", "https://ex.com/b"]
    assert res.notes is None


async def test_run_map_homepage_fallback_keeps_only_internal(router):
    homepage = _homepage(
        '<a href="https://ex.com/about">about</a>'
        '<a href="/contact">contact</a>'
        '<a href="https://other.com/x">external</a>'
    )
    with _routes({
        # robots + well-known probes all 404 → homepage fallback
        "https://ex.com/": _http("https://ex.com/", text=homepage),
    }):
        res = await sitemap.run_map(
            "https://ex.com/", search_filter=None, limit=None, router=router,
        )
    assert res.source == "homepage"
    urls = {e.url for e in res.urls}
    assert "https://ex.com/about" in urls
    assert "https://ex.com/contact" in urls
    assert "https://other.com/x" not in urls


async def test_run_map_downgrades_to_homepage_on_parse_error(router):
    homepage = _homepage('<a href="https://ex.com/z">z</a>')
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt",
            text="Sitemap: https://ex.com/sitemap.xml\n", ctype="text/plain",
        ),
        "https://ex.com/sitemap.xml": _http(
            "https://ex.com/sitemap.xml", text="<urlset><broken", ctype="application/xml",
        ),
        "https://ex.com/": _http("https://ex.com/", text=homepage),
    }):
        res = await sitemap.run_map(
            "https://ex.com/", search_filter=None, limit=None, router=router,
        )
    assert res.source == "homepage"
    assert [e.url for e in res.urls] == ["https://ex.com/z"]


async def test_run_map_dedupes_canonical_duplicates(router):
    dup = (
        '<urlset>'
        '<url><loc>https://ex.com/a</loc></url>'
        '<url><loc>https://ex.com/a/</loc></url>'
        '<url><loc>https://ex.com/a?utm_source=x</loc></url>'
        '</urlset>'
    )
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt",
            text="Sitemap: https://ex.com/sitemap.xml\n", ctype="text/plain",
        ),
        "https://ex.com/sitemap.xml": _http("https://ex.com/sitemap.xml", text=dup, ctype="application/xml"),
    }):
        res = await sitemap.run_map(
            "https://ex.com/", search_filter=None, limit=None, router=router,
        )
    # All three collapse to one canonical URL.
    assert res.count == 1


async def test_run_map_applies_search_filter(router):
    body = (
        '<urlset>'
        '<url><loc>https://ex.com/docs/intro</loc></url>'
        '<url><loc>https://ex.com/blog/post</loc></url>'
        '<url><loc>https://ex.com/docs/api</loc></url>'
        '</urlset>'
    )
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt",
            text="Sitemap: https://ex.com/sitemap.xml\n", ctype="text/plain",
        ),
        "https://ex.com/sitemap.xml": _http("https://ex.com/sitemap.xml", text=body, ctype="application/xml"),
    }):
        res = await sitemap.run_map(
            "https://ex.com/", search_filter="docs", limit=None, router=router,
        )
    assert res.count == 2
    assert all("docs" in e.url for e in res.urls)


async def test_run_map_limit_truncates_and_notes(router):
    body = "<urlset>" + "".join(
        f"<url><loc>https://ex.com/p{i}</loc></url>" for i in range(5)
    ) + "</urlset>"
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt",
            text="Sitemap: https://ex.com/sitemap.xml\n", ctype="text/plain",
        ),
        "https://ex.com/sitemap.xml": _http("https://ex.com/sitemap.xml", text=body, ctype="application/xml"),
    }):
        res = await sitemap.run_map(
            "https://ex.com/", search_filter=None, limit=2, router=router,
        )
    assert len(res.urls) == 2       # truncated output
    assert res.count == 5           # count reflects pre-truncation total
    assert res.notes is not None and "2" in res.notes


async def test_run_map_count_zero_is_ok_with_notes(router):
    # No sitemap, homepage has no internal links → empty but not a failure.
    with _routes({
        "https://ex.com/": _http(
            "https://ex.com/", text=_homepage('<a href="https://other.com/x">ext</a>'),
        ),
    }):
        res = await sitemap.run_map(
            "https://ex.com/", search_filter=None, limit=None, router=router,
        )
    assert res.count == 0
    assert res.notes is not None


async def test_run_map_raises_when_homepage_fetch_fails(router):
    # An unreachable seed (DNS failure) must NOT report ok:true count:0 — it is a
    # real failure and has to surface as a FetchError so the CLI exits 1.
    import socket

    def _boom(_host):
        raise socket.gaierror("name resolution failed")

    with patch("lightcrawl.url_safety.socket.gethostbyname", side_effect=_boom), \
         patch("lightcrawl.fetch_http.fetch",
               side_effect=AssertionError("network must not be reached")):
        with pytest.raises(FetchError) as ei:
            await sitemap.run_map(
                "https://ex.com/", search_filter=None, limit=None, router=router,
            )
    assert ei.value.code == ErrorCode.DNS_FAILED


async def test_run_map_note_distinguishes_sitemap_parse_failure(router):
    # A sitemap WAS discovered but every shard failed to parse, and the homepage
    # fallback found nothing. The note must not claim "no sitemap found".
    with _routes({
        "https://ex.com/robots.txt": _http(
            "https://ex.com/robots.txt",
            text="Sitemap: https://ex.com/sitemap.xml\n", ctype="text/plain",
        ),
        "https://ex.com/sitemap.xml": _http(
            "https://ex.com/sitemap.xml", text="<urlset><broken", ctype="application/xml",
        ),
        "https://ex.com/": _http(
            "https://ex.com/", text=_homepage('<a href="https://other.com/x">ext</a>'),
        ),
    }):
        res = await sitemap.run_map(
            "https://ex.com/", search_filter=None, limit=None, router=router,
        )
    assert res.count == 0
    assert res.notes is not None
    assert "parse" in res.notes.lower()
    assert "no sitemap found" not in res.notes.lower()
