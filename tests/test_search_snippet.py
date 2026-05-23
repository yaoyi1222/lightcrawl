from __future__ import annotations

import pytest

from lightcrawl.router import Router
from lightcrawl.search.service import SearchRequest, SearchService
from lightcrawl.search.snippet import sanitize_snippet
from lightcrawl.search.types import SearchResult


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # Mirror tests/test_search.py's isolation so dump-cache lookups don't
    # write outside the temp dir and don't accidentally enhance our
    # sanitised snippets.
    monkeypatch.setattr("lightcrawl.paths.ROOT", tmp_path)
    monkeypatch.setattr("lightcrawl.paths.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("lightcrawl.paths.PROFILES", tmp_path / "profiles")
    monkeypatch.setattr("lightcrawl.paths.LOGS", tmp_path / "logs")
    monkeypatch.setattr("lightcrawl.content.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("lightcrawl.search.service.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("lightcrawl.auth.PROFILES", tmp_path / "profiles")
    (tmp_path / "dumps").mkdir(parents=True)
    (tmp_path / "profiles").mkdir(parents=True)


# -- pure helper tests -----------------------------------------------------


def test_sanitize_strips_markdown_image_nav():
    # The exact sina snippet shape that triggered #37.
    raw = (
        "[![新浪网](http://i1.sinaimg.cn/dy/images/header/2009/standardl2nav_sina_new.gif)]"
        "(http://www.sina.com.cn/)"
        "[![新浪财经](http://i1.sinaimg.cn/dy/images/header/2009/standardl2nav_finance.gif)]"
        "(http://finance.sina.com.cn/)"
    )
    assert sanitize_snippet(raw) == ""


def test_sanitize_keeps_link_text():
    assert sanitize_snippet("Read the [annual report](https://example.com/r.pdf) now.") == \
        "Read the annual report now."


def test_sanitize_drops_inline_image_but_keeps_surrounding_text():
    assert sanitize_snippet("Foo ![logo](http://x/y.gif) bar") == "Foo bar"


def test_sanitize_strips_html_tags():
    assert sanitize_snippet("Hello <strong>world</strong>!") == "Hello world!"


def test_sanitize_strips_anchor_with_inner_image():
    assert sanitize_snippet('<a href="/x"><img src="/y.png" alt="L"></a>X') == "X"


def test_sanitize_collapses_whitespace():
    assert sanitize_snippet("a   b\n\nc\td") == "a b c d"


def test_sanitize_empty_and_none_safe():
    assert sanitize_snippet("") == ""
    # None would only happen via a buggy backend, but the helper shouldn't crash.
    assert sanitize_snippet(None) is None  # type: ignore[arg-type]


def test_sanitize_preserves_plain_text():
    text = "健康元药业 2025 年半年度报告:营收同比增长 12.3%。"
    assert sanitize_snippet(text) == text


# -- integration: snippet sanitation runs inside SearchService.search ------


class _FakeBackend:
    name = "fake"
    cost_per_call_usd = 0.001

    def __init__(self, results):
        self._results = results

    def configured(self):
        return True

    async def search(self, query, *, max_results, time_range=(None, None), timeout=10.0):
        return self._results[:max_results]


async def test_search_sanitises_snippet_before_returning():
    raw_snippet = (
        "[![新浪网](http://i1.sinaimg.cn/x.gif)](http://www.sina.com.cn/) "
        "公司公告"
    )
    fake = _FakeBackend([
        SearchResult(rank=1, title="T", url="https://finance.sina.com.cn/x",
                     snippet=raw_snippet),
    ])
    svc = SearchService(router=Router(), backends=[fake])
    try:
        out = await svc.search(SearchRequest(query="健康元"))
        assert out["ok"] is True
        assert out["results"][0]["snippet"] == "公司公告"
    finally:
        await svc.close()
