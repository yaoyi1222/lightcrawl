from __future__ import annotations

import pytest

from lightcrawl.router import Router
from lightcrawl.search.service import SearchRequest, SearchService
from lightcrawl.search.snippet import recover_gbk_mojibake
from lightcrawl.search.types import SearchResult


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("lightcrawl.paths.ROOT", tmp_path)
    monkeypatch.setattr("lightcrawl.paths.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("lightcrawl.paths.PROFILES", tmp_path / "profiles")
    monkeypatch.setattr("lightcrawl.paths.LOGS", tmp_path / "logs")
    monkeypatch.setattr("lightcrawl.content.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("lightcrawl.search.service.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("lightcrawl.auth.PROFILES", tmp_path / "profiles")
    (tmp_path / "dumps").mkdir(parents=True)
    (tmp_path / "profiles").mkdir(parents=True)


# -- pure helper tests ----------------------------------------------------


def test_recover_restores_gbk_chinese():
    # The exact sample from issue #38 — GBK bytes of '司聘幕师冢' that
    # arrived as UTF-8-decoded chars in the U+0080-U+04FF mojibake zone.
    assert recover_gbk_mojibake("˾ƸĻʦڣ") == "司聘幕师冢"


def test_recover_restores_gbk_snippet_with_ascii_separators():
    # Mojibake'd payload interleaved with ASCII pipes / spaces (the
    # finance.sina.com.cn snippet shape from #38).
    raw = "˾ƸĻʦڣ | | ͬʦͨϻ"
    out = recover_gbk_mojibake(raw)
    assert "司聘幕师冢" in out
    assert " | | " in out  # ASCII separators preserved verbatim


def test_recover_skips_legitimate_utf8_chinese():
    # When the text already has valid CJK code points, we must not
    # touch it — the recovery would corrupt it.
    text = "公司公告 2025 年半年度报告"
    assert recover_gbk_mojibake(text) == text


def test_recover_skips_pure_ascii():
    assert recover_gbk_mojibake("Hello world!") == "Hello world!"


def test_recover_skips_latin_extended_text():
    # Spanish, French, German etc. have a few chars in U+0080-U+04FF but
    # encode-utf8 / decode-gbk wouldn't yield any CJK, so the result is
    # unchanged.
    text = "café résumé naïve"
    assert recover_gbk_mojibake(text) == text


def test_recover_skips_cyrillic():
    # Cyrillic chars live in U+0400-U+04FF, outside the U+0080-U+02FF
    # suspect window — so they never enter the recovery path. (Without
    # the narrowed window the encode-utf8/decode-gbk round-trip turns
    # Cyrillic into garbage CJK.)
    text = "Привет мир"
    assert recover_gbk_mojibake(text) == text


def test_recover_skips_greek():
    # Greek (U+0370-U+03FF) is likewise outside the suspect window.
    text = "Καλημέρα κόσμε"
    assert recover_gbk_mojibake(text) == text


def test_recover_skips_legit_text_that_round_trips_to_low_cjk_density():
    # Spanish-style text with several Latin-Extended diacritics passes
    # the suspect-zone guard but the encode-utf8/decode-gbk round-trip
    # only produces one CJK per accented letter — far below the 50%
    # density floor. Without that floor, ``café résumé naïve`` would be
    # corrupted to ``caf茅 r茅sum茅 na茂ve``.
    text = "café résumé naïve épée"
    assert recover_gbk_mojibake(text) == text


def test_recover_skips_empty():
    assert recover_gbk_mojibake("") == ""


def test_recover_skips_short_suspect_text():
    # One or two suspect chars is below the threshold — could just be a
    # stray punctuation mark in otherwise-ASCII text.
    assert recover_gbk_mojibake("price: 12€") == "price: 12€"


# -- integration: recovery runs inside SearchService.search ---------------


class _FakeBackend:
    name = "fake"
    cost_per_call_usd = 0.001

    def __init__(self, results):
        self._results = results

    def configured(self):
        return True

    async def search(self, query, *, max_results, time_range=(None, None), timeout=10.0):
        return self._results[:max_results]


async def test_search_recovers_mojibake_snippet():
    raw_snippet = "˾ƸĻʦڣ | ͬʦͨϻ"
    fake = _FakeBackend([
        SearchResult(rank=1, title="T", url="https://finance.sina.com.cn/x",
                     snippet=raw_snippet),
    ])
    svc = SearchService(router=Router(), backends=[fake])
    try:
        out = await svc.search(SearchRequest(query="健康元"))
        recovered = out["results"][0]["snippet"]
        assert "司聘幕师冢" in recovered
        assert "˾" not in recovered
    finally:
        await svc.close()


async def test_search_leaves_valid_chinese_alone():
    """Sanity: a snippet that arrives correctly encoded must not be
    silently mutated by the recovery pass."""
    fake = _FakeBackend([
        SearchResult(rank=1, title="T", url="https://example.com/",
                     snippet="健康元发布 2025 年半年度报告"),
    ])
    svc = SearchService(router=Router(), backends=[fake])
    try:
        out = await svc.search(SearchRequest(query="健康元"))
        assert out["results"][0]["snippet"] == "健康元发布 2025 年半年度报告"
    finally:
        await svc.close()
