"""Tests for src/lightcrawl/canonical.py — pure-function URL canonicalization.

All tests are table-driven and offline (no network, no I/O). The cache key
and crawl visited-set both depend on this module being deterministic, so
every documented behavior gets a regression test.
"""
from lightcrawl.canonical import canonicalize_url, url_hash


def test_lowercases_scheme():
    assert canonicalize_url("HTTPS://example.com/") == "https://example.com/"


def test_lowercases_host():
    assert canonicalize_url("https://Example.COM/Path") == "https://example.com/Path"


def test_preserves_path_case():
    assert canonicalize_url("https://example.com/Foo/Bar") == "https://example.com/Foo/Bar"


def test_strips_default_http_port():
    assert canonicalize_url("http://example.com:80/p") == "http://example.com/p"


def test_strips_default_https_port():
    assert canonicalize_url("https://example.com:443/p") == "https://example.com/p"


def test_keeps_non_default_port():
    assert canonicalize_url("https://example.com:8080/p") == "https://example.com:8080/p"


def test_empty_path_becomes_root():
    assert canonicalize_url("https://example.com") == "https://example.com/"


def test_root_path_preserved():
    assert canonicalize_url("https://example.com/") == "https://example.com/"


def test_strips_trailing_slash_on_non_root_path():
    assert canonicalize_url("https://example.com/foo/") == "https://example.com/foo"


def test_does_not_strip_root_slash():
    # Edge: path is just "/" — must NOT become "" (would break urlunparse)
    assert canonicalize_url("https://example.com/") == "https://example.com/"


def test_drops_fragment():
    assert canonicalize_url("https://example.com/p#section") == "https://example.com/p"


def test_drops_empty_fragment():
    assert canonicalize_url("https://example.com/p#") == "https://example.com/p"
