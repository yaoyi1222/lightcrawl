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


# ----- query handling --------------------------------------------------------

def test_keeps_single_query_param():
    assert canonicalize_url("https://example.com/p?a=1") == "https://example.com/p?a=1"


def test_sorts_query_params_by_key():
    assert canonicalize_url("https://example.com/p?b=2&a=1") == "https://example.com/p?a=1&b=2"


def test_preserves_percent_encoded_chars():
    # %20 (space) round-trips via parse_qsl+urlencode → "+" (RFC-3986 equivalent
    # in application/x-www-form-urlencoded). We document "+" as canonical form.
    assert canonicalize_url("https://example.com/p?q=hello%20world") == "https://example.com/p?q=hello+world"


def test_drops_utm_source_by_default():
    assert canonicalize_url("https://example.com/p?utm_source=newsletter") == "https://example.com/p"


def test_drops_all_utm_params():
    u = "https://example.com/p?utm_source=x&utm_medium=y&utm_campaign=z&a=1"
    assert canonicalize_url(u) == "https://example.com/p?a=1"


def test_drops_fbclid_gclid_ref():
    u = "https://example.com/p?fbclid=abc&gclid=def&ref=hn&keep=1"
    assert canonicalize_url(u) == "https://example.com/p?keep=1"


def test_drop_tracking_false_keeps_tracking_params():
    u = "https://example.com/p?utm_source=x&a=1"
    assert canonicalize_url(u, drop_tracking=False) == "https://example.com/p?a=1&utm_source=x"


def test_ignore_query_drops_everything():
    u = "https://example.com/p?a=1&b=2"
    assert canonicalize_url(u, ignore_query=True) == "https://example.com/p"


def test_ignore_query_drops_tracking_too():
    u = "https://example.com/p?a=1&utm_source=x"
    assert canonicalize_url(u, ignore_query=True) == "https://example.com/p"


def test_blank_value_query_param_preserved():
    # ?flag&other=1 — flag has blank value; should not be dropped
    assert canonicalize_url("https://example.com/p?flag&other=1") == "https://example.com/p?flag=&other=1"


def test_empty_query_no_question_mark():
    # All params dropped → no trailing "?"
    assert canonicalize_url("https://example.com/p?utm_source=x") == "https://example.com/p"
