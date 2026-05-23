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


def test_sanitize_empty_input():
    assert sanitize_snippet("") == ""


def test_sanitize_preserves_plain_text():
    text = "健康元药业 2025 年半年度报告:营收同比增长 12.3%。"
    assert sanitize_snippet(text) == text


# -- regression: PR #51 review --------------------------------------------


def test_sanitize_link_with_parens_in_url():
    # Wikipedia-style URL has a literal ``(...)`` inside the href.
    # The naive ``[^)]*`` regex stops at the first ``)`` and leaves
    # a stray ``)`` after the link text. (#51 HIGH)
    assert sanitize_snippet(
        "Read [Python](https://en.wikipedia.org/wiki/Python_(programming_language))."
    ) == "Read Python."


def test_sanitize_image_with_parens_in_url():
    assert sanitize_snippet(
        "Logo ![icon](http://example.com/img_(v1).png) here"
    ) == "Logo here"


def test_sanitize_nested_image_link_with_parens_in_url():
    # Sina-style nav where the inner image URL itself has a ``(``.
    assert sanitize_snippet(
        "[![logo](http://example.com/img_(1).gif)](http://example.com/)"
    ) == ""


def test_sanitize_unwraps_markdown_autolink():
    # ``<https://...>`` is markdown autolink syntax. We unwrap to the
    # raw URL so the rendered snippet reads naturally; the surrounding
    # ``<>`` are presentational only. (#51 follow-up — replaces the
    # earlier "keep autolink with brackets" behaviour.)
    assert sanitize_snippet("Visit <https://example.com/page> for details") == \
        "Visit https://example.com/page for details"


def test_sanitize_unwraps_autolink_with_parens_in_url():
    assert sanitize_snippet(
        "See <https://en.wikipedia.org/wiki/Python_(programming_language)>."
    ) == "See https://en.wikipedia.org/wiki/Python_(programming_language)."


def test_sanitize_unwraps_mailto_autolink():
    assert sanitize_snippet("Contact <mailto:foo@example.com> please") == \
        "Contact mailto:foo@example.com please"


def test_sanitize_strips_html_comment():
    # Pre-#51-MEDIUM the catch-all ``<[^>]+>`` regex covered comments
    # incidentally; the tightened tag regex no longer does. Cover them
    # explicitly so the fix doesn't introduce a regression. (#51 follow-up)
    assert sanitize_snippet("<!-- tracking pixel --> Real content") == \
        "Real content"


def test_sanitize_strips_multiple_html_comments():
    # Non-greedy: adjacent comments should each match independently
    # rather than the first ``-->`` swallowing everything to the last.
    assert sanitize_snippet("<!-- a --> middle <!-- b --> tail") == \
        "middle tail"


def test_sanitize_preserves_math_angle_brackets():
    # Lone ``<`` / ``>`` are not tags and must survive verbatim.
    assert sanitize_snippet("5 < 10 and 20 > 15") == "5 < 10 and 20 > 15"


def test_sanitize_strips_self_closing_html_tag():
    assert sanitize_snippet("a<br/>b<img src=x />c") == "abc"


def test_sanitize_collapses_unicode_whitespace():
    # NBSP (U+00A0) and ideographic space (U+3000) are whitespace under
    # ``\s``. Confirm the comment matches the actual behaviour after the
    # ``ASCII whitespace`` wording fix. (#51 LOW)
    assert sanitize_snippet("a b　c") == "a b c"


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


async def test_enhancer_sanitises_dump_content(tmp_path):
    """Regression for #51 HIGH 2: when the dump-cache enhancer pulls
    cached content into a too-short snippet, the cached markdown can
    itself contain raw nav markup. The enhancer must route the result
    through sanitize_snippet so it can't re-inject what the initial
    sanitation pass already removed."""
    import hashlib
    url = "https://finance.sina.com.cn/x"
    digest = hashlib.sha1(url.encode()).hexdigest()[:16]
    # Dump first paragraph is raw nav markup that, untouched, would be
    # written straight back to ``snippet`` after sanitation. The first
    # paragraph also needs to be long enough to clear ``len(head) >
    # len(r.snippet)`` once sanitised — otherwise the enhancer
    # legitimately keeps the original.
    nav_markup = "[![新浪网](http://i1.sinaimg.cn/x.gif)](http://www.sina.com.cn/)"
    real_body = "健康元药业 2025 年半年度报告:营业收入同比增长 12.3%,净利润 5.6 亿元。"
    (tmp_path / "dumps" / f"{digest}.md").write_text(f"{nav_markup}{real_body}")
    fake = _FakeBackend([
        SearchResult(rank=1, title="T", url=url, snippet="short"),
    ])
    svc = SearchService(router=Router(), backends=[fake])
    try:
        out = await svc.search(SearchRequest(query="健康元"))
        enhanced = out["results"][0]["snippet"]
        # Sanitation drops the nav markup; the body survives.
        assert "新浪网" not in enhanced
        assert "![" not in enhanced
        assert "营业收入" in enhanced
    finally:
        await svc.close()
