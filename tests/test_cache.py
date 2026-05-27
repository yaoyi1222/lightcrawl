"""Single-process unit tests for ``lightcrawl.cache`` (v0.3 PR 2.2).

Concurrency / multiprocess WAL contention lives in
``tests/test_cache_concurrency.py`` (PR 2.5). These tests cover the
happy paths, the age / profile / atomicity invariants, and GC.

Time is faked via a monkeypatched ``cache.time_ms`` so age-based logic
is deterministic. Filesystem state is isolated under ``tmp_path``.
"""

from __future__ import annotations

import json

import pytest

from lightcrawl import cache as cache_mod
from lightcrawl.cache import Cache


@pytest.fixture
def fake_clock(monkeypatch):
    """Monkeypatch ``cache.time_ms`` to a controllable counter.

    Yields a single-element list — tests mutate ``clock[0]`` to advance.
    """
    clock = [1_000_000]
    monkeypatch.setattr(cache_mod, "time_ms", lambda: clock[0])
    return clock


@pytest.fixture
def cache(tmp_path) -> Cache:
    return Cache(root=tmp_path / "cache")


def _response(
    *, content: str = "# hello\n\nbody", headers: dict | None = None,
    dump_path: str | None = None, screenshot_path: str | None = None,
) -> dict:
    return {
        "ok": True,
        "url": "https://example.com/x",
        "status_code": 200,
        "content": content,
        "headers": headers or {},
        "headings": [{"level": 1, "text": "hello", "line": 1}],
        "metadata": {"links": [], "images": []},
        "dump_path": dump_path,
        "screenshot_path": screenshot_path,
    }


# -- init / schema ---------------------------------------------------------


def test_cache_creates_directory_layout(tmp_path):
    Cache(root=tmp_path / "cache")
    root = tmp_path / "cache"
    assert (root / "index.sqlite").exists()
    assert (root / "payloads").is_dir()
    assert (root / "dumps").is_dir()
    assert (root / "screenshots").is_dir()


def test_cache_schema_idempotent(tmp_path):
    """Constructing Cache twice on the same root must not error."""
    Cache(root=tmp_path / "cache")
    Cache(root=tmp_path / "cache")


# -- store + lookup --------------------------------------------------------


def test_store_then_lookup_returns_hit(cache: Cache, fake_clock):
    url = "https://example.com/article"
    cache.store(url, profile=None, response=_response(content="real body"))
    hit = cache.lookup(url, profile=None, max_age_ms=60_000)
    assert hit is not None
    assert hit.markdown == "real body"
    assert hit.canonical_url == "https://example.com/article"
    assert hit.age_ms == 0


def test_lookup_returns_none_when_max_age_none(cache: Cache, fake_clock):
    """``max_age_ms=None`` is a defensive no-op — caller should
    short-circuit, but the cache must also refuse to read."""
    cache.store("https://example.com/x", profile=None, response=_response())
    assert cache.lookup("https://example.com/x", profile=None, max_age_ms=None) is None


def test_lookup_misses_when_no_entry(cache: Cache, fake_clock):
    assert cache.lookup("https://nope.example/", profile=None, max_age_ms=60_000) is None


def test_lookup_expires_past_max_age(cache: Cache, fake_clock):
    cache.store("https://example.com/x", profile=None, response=_response())
    fake_clock[0] += 120_000  # 120 s
    assert cache.lookup(
        "https://example.com/x", profile=None, max_age_ms=60_000,
    ) is None
    # Same entry within budget still hits.
    assert cache.lookup(
        "https://example.com/x", profile=None, max_age_ms=180_000,
    ) is not None


def test_lookup_age_ms_reflects_elapsed(cache: Cache, fake_clock):
    cache.store("https://example.com/x", profile=None, response=_response())
    fake_clock[0] += 5_000
    hit = cache.lookup("https://example.com/x", profile=None, max_age_ms=60_000)
    assert hit is not None
    assert hit.age_ms == 5_000


def test_lookup_for_revalidation_ignores_age(cache: Cache, fake_clock):
    """PR 3's conditional-request path needs the cached body regardless
    of age; the caller then sends If-None-Match / If-Modified-Since."""
    cache.store(
        "https://example.com/x", profile=None,
        response=_response(headers={"etag": "abc"}),
    )
    fake_clock[0] += 10_000_000  # absurdly stale
    hit = cache.lookup_for_revalidation("https://example.com/x", profile=None)
    assert hit is not None
    assert hit.headers["etag"] == "abc"


# -- profile isolation (design §5.2 A2) ------------------------------------


def test_profile_dimension_is_a_security_boundary(cache: Cache, fake_clock):
    """Same URL fetched with two different profiles must store two
    independent entries; the no-profile caller must never see the
    profiled body."""
    url = "https://x.com/private/123"
    cache.store(url, profile="twitter", response=_response(content="authed body"))
    cache.store(url, profile=None, response=_response(content="public body"))

    authed = cache.lookup(url, profile="twitter", max_age_ms=60_000)
    anon = cache.lookup(url, profile=None, max_age_ms=60_000)
    assert authed is not None and authed.markdown == "authed body"
    assert anon is not None and anon.markdown == "public body"
    assert cache.stats().entry_count == 2


def test_profile_none_and_empty_string_share_bucket(cache: Cache, fake_clock):
    """``profile=None`` and ``profile=""`` both mean "no profile" and
    must hash identically. Locked in by canonical.url_hash but worth
    asserting end-to-end."""
    url = "https://example.com/x"
    cache.store(url, profile=None, response=_response(content="first"))
    cache.store(url, profile="", response=_response(content="second"))
    hit = cache.lookup(url, profile=None, max_age_ms=60_000)
    assert hit is not None
    assert hit.markdown == "second"  # second write replaced first
    assert cache.stats().entry_count == 1


# -- touch / delete --------------------------------------------------------


def test_lookup_touches_accessed_at(cache: Cache, fake_clock):
    cache.store("https://example.com/x", profile=None, response=_response())
    fake_clock[0] += 1_000
    cache.lookup("https://example.com/x", profile=None, max_age_ms=60_000)
    # accessed_at should be the post-touch clock value, fetched_at the original.
    with __import__("sqlite3").connect(cache.db_path) as conn:
        row = conn.execute(
            "SELECT fetched_at, accessed_at FROM entries"
        ).fetchone()
    fetched_at, accessed_at = row
    assert accessed_at == 1_001_000
    assert fetched_at == 1_000_000


def test_lookup_for_revalidation_does_not_touch(cache: Cache, fake_clock):
    """Revalidation hasn't decided to keep the body yet — accessed_at
    should reflect the eventual commit, not the speculative read."""
    cache.store("https://example.com/x", profile=None, response=_response())
    fake_clock[0] += 5_000
    cache.lookup_for_revalidation("https://example.com/x", profile=None)
    with __import__("sqlite3").connect(cache.db_path) as conn:
        row = conn.execute("SELECT accessed_at FROM entries").fetchone()
    assert row[0] == 1_000_000  # unchanged


def test_delete_removes_index_row_and_payload(cache: Cache, fake_clock):
    url = "https://example.com/x"
    cache.store(url, profile=None, response=_response())
    payloads = list(cache.payloads_dir.glob("*.json"))
    assert len(payloads) == 1
    cache.delete(url, profile=None)
    assert cache.lookup(url, profile=None, max_age_ms=60_000) is None
    assert list(cache.payloads_dir.glob("*.json")) == []
    assert cache.stats().entry_count == 0


# -- atomicity / crash recovery -------------------------------------------


def test_orphan_payload_is_invisible_until_indexed(cache: Cache, fake_clock):
    """Simulate a crash between os.replace and the INSERT: payload file
    exists but no index row. ``lookup`` must treat this as miss so a
    half-written entry never leaks. (design §5.2 atomicity)"""
    from lightcrawl.canonical import canonicalize_url, url_hash
    url = "https://example.com/orphan"
    key = url_hash(canonicalize_url(url), profile=None)
    payload = {
        "url": url, "canonical_url": canonicalize_url(url), "profile": None,
        "fetched_at": 1_000_000, "status_code": 200, "headers": {},
        "markdown": "leaked", "headings": [], "metadata": {},
        "dump_path": None, "screenshot_path": None,
    }
    (cache.payloads_dir / f"{key}.json").write_text(json.dumps(payload))
    # No index INSERT.
    assert cache.lookup(url, profile=None, max_age_ms=60_000) is None


def test_store_overwrite_replaces_payload_atomically(cache: Cache, fake_clock):
    url = "https://example.com/x"
    cache.store(url, profile=None, response=_response(content="v1"))
    fake_clock[0] += 1_000
    cache.store(url, profile=None, response=_response(content="v2"))
    hit = cache.lookup(url, profile=None, max_age_ms=60_000)
    assert hit is not None
    assert hit.markdown == "v2"
    # Only one payload, no .tmp left behind.
    assert len(list(cache.payloads_dir.iterdir())) == 1


# -- gc -------------------------------------------------------------------


def test_gc_older_than(cache: Cache, fake_clock):
    cache.store("https://a.example/", profile=None, response=_response())
    fake_clock[0] += 100_000
    cache.store("https://b.example/", profile=None, response=_response())
    # b.example fetched 100s ago, a.example 100s+ ago.
    # older_than=50_000 → a removed, b kept.
    stats = cache.gc(older_than_ms=50_000)
    assert stats.deleted_entries == 1
    assert cache.stats().entry_count == 1
    remaining = cache.lookup("https://b.example/", profile=None, max_age_ms=200_000)
    assert remaining is not None


def test_gc_by_host(cache: Cache, fake_clock):
    cache.store("https://a.example/x", profile=None, response=_response())
    cache.store("https://b.example/x", profile=None, response=_response())
    stats = cache.gc(host="a.example")
    assert stats.deleted_entries == 1
    assert cache.lookup("https://a.example/x", profile=None, max_age_ms=60_000) is None
    assert cache.lookup("https://b.example/x", profile=None, max_age_ms=60_000) is not None


def test_gc_lru_drains_to_watermark(cache: Cache, fake_clock):
    """Insert 5 entries; cap total bytes so LRU drain trims to ≤ 80 %
    of the cap, not just ≤ cap. The 80 % watermark is the actual
    contract — without asserting against ``cap * 0.8`` the test would
    pass even if ``_gc_lru`` shaved a single byte under the cap."""
    for i in range(5):
        fake_clock[0] += 1_000
        cache.store(
            f"https://example.com/{i}", profile=None,
            response=_response(content="x" * 500),
        )
    before = cache.stats()
    cap = before.total_bytes // 2
    stats = cache.gc(max_total_bytes=cap)
    after = cache.stats()
    assert stats.deleted_entries > 0
    assert after.total_bytes <= int(cap * 0.8)
    # Oldest accessed_at should be the ones evicted; we wrote 0 → 4
    # without further reads, so /0 is the LRU candidate.
    assert cache.lookup("https://example.com/0", profile=None, max_age_ms=60_000) is None


def test_gc_lru_noop_when_under_cap(cache: Cache, fake_clock):
    cache.store("https://a.example/", profile=None, response=_response())
    stats = cache.gc(max_total_bytes=10_000_000)
    assert stats.deleted_entries == 0


# -- stats / legacy --------------------------------------------------------


def test_stats_aggregates_correctly(cache: Cache, fake_clock):
    cache.store("https://a.example/", profile=None, response=_response())
    cache.store("https://b.example/", profile=None, response=_response())
    cache.store("https://a.example/2", profile=None, response=_response())
    stats = cache.stats()
    assert stats.entry_count == 3
    assert stats.hosts == 2  # a.example, b.example
    assert stats.payload_bytes > 0


def test_legacy_dumps_usage_reports_size(tmp_path, monkeypatch):
    # cache.py reads ``paths.DUMPS`` at call time (not import time), so
    # patching ``lightcrawl.paths.DUMPS`` is enough — the module-level
    # ``from . import paths`` keeps a live reference to the module.
    legacy = tmp_path / "legacy_dumps"
    legacy.mkdir()
    (legacy / "a.md").write_bytes(b"x" * 100)
    (legacy / "b.md").write_bytes(b"y" * 200)
    monkeypatch.setattr("lightcrawl.paths.DUMPS", legacy)
    c = Cache(root=tmp_path / "cache")
    assert c.legacy_dumps_usage() == 300


def test_legacy_dumps_usage_zero_when_missing(tmp_path, monkeypatch):
    missing = tmp_path / "absent"
    monkeypatch.setattr("lightcrawl.paths.DUMPS", missing)
    c = Cache(root=tmp_path / "cache")
    assert c.legacy_dumps_usage() == 0


# -- dump / screenshot accounting -----------------------------------------


def test_store_records_dump_and_screenshot_sizes(cache: Cache, fake_clock, tmp_path):
    dump = tmp_path / "dump.md"
    dump.write_bytes(b"x" * 1234)
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"y" * 5678)
    cache.store(
        "https://example.com/x", profile=None,
        response=_response(dump_path=str(dump), screenshot_path=str(shot)),
    )
    stats = cache.stats()
    assert stats.dump_bytes == 1234
    assert stats.screenshot_bytes == 5678
    hit = cache.lookup("https://example.com/x", profile=None, max_age_ms=60_000)
    assert hit is not None
    assert hit.dump_path == str(dump)
    assert hit.screenshot_path == str(shot)


# -- side-file cleanup (dumps + screenshots) -------------------------------


def _write_side_files(cache: Cache, basename: str) -> tuple[str, str]:
    """Write a dump under ``cache.dumps_dir`` and a screenshot under
    ``cache.screenshots_dir`` so the cleanup path treats them as
    belonging to this cache."""
    dump = cache.dumps_dir / f"{basename}.md"
    dump.write_bytes(b"dump bytes")
    shot = cache.screenshots_dir / f"{basename}.png"
    shot.write_bytes(b"shot bytes")
    return str(dump), str(shot)


def test_delete_removes_dump_and_screenshot(cache: Cache, fake_clock):
    """``delete()`` must clear the payload AND the dump/screenshot files
    referenced by the payload. Without this, cache eviction leaks files
    forever under ``cache/dumps`` and ``cache/screenshots``."""
    url = "https://example.com/x"
    dump, shot = _write_side_files(cache, "del")
    cache.store(url, profile=None, response=_response(
        dump_path=dump, screenshot_path=shot,
    ))
    cache.delete(url, profile=None)
    assert not (cache.dumps_dir / "del.md").exists()
    assert not (cache.screenshots_dir / "del.png").exists()


def test_gc_by_host_removes_dump_and_screenshot(cache: Cache, fake_clock):
    dump, shot = _write_side_files(cache, "host")
    cache.store(
        "https://a.example/x", profile=None,
        response=_response(dump_path=dump, screenshot_path=shot),
    )
    cache.gc(host="a.example")
    assert not (cache.dumps_dir / "host.md").exists()
    assert not (cache.screenshots_dir / "host.png").exists()


def test_gc_lru_removes_dump_and_screenshot(cache: Cache, fake_clock):
    """LRU drain must also delete the dump/screenshot files of the
    evicted entries, not just the payload JSON."""
    for i in range(3):
        fake_clock[0] += 1_000
        dump, shot = _write_side_files(cache, f"lru-{i}")
        cache.store(
            f"https://example.com/{i}", profile=None,
            response=_response(
                content="x" * 500, dump_path=dump, screenshot_path=shot,
            ),
        )
    before = cache.stats()
    cache.gc(max_total_bytes=before.total_bytes // 3)
    # /0 was LRU so its files must be gone; the rest may or may not be
    # depending on watermark — just assert no leak for the evicted one.
    assert not (cache.dumps_dir / "lru-0.md").exists()
    assert not (cache.screenshots_dir / "lru-0.png").exists()


def test_unlink_skips_files_outside_cache_root(cache: Cache, fake_clock, tmp_path):
    """Cache must not delete files that aren't under its dumps/
    screenshots dirs — e.g. v0.2 dumps in ``~/.lightcrawl/dumps/``.
    The byte accounting is informational; the user owns those files."""
    foreign_dump = tmp_path / "outside.md"
    foreign_dump.write_bytes(b"keep me")
    foreign_shot = tmp_path / "outside.png"
    foreign_shot.write_bytes(b"keep me too")
    cache.store("https://example.com/x", profile=None, response=_response(
        dump_path=str(foreign_dump), screenshot_path=str(foreign_shot),
    ))
    cache.delete("https://example.com/x", profile=None)
    assert foreign_dump.exists()
    assert foreign_shot.exists()


# -- store() Router response-shape adapter ---------------------------------


def test_store_accepts_router_envelope_with_status_in_metadata(cache: Cache, fake_clock):
    """Router puts ``status_code`` under ``metadata``, not top-level.
    Cache must extract it from there so the DB column reflects the real
    response code (and PR 3's revalidation logic can trust it)."""
    cache.store("https://example.com/x", profile=None, response={
        "ok": True,
        "url": "https://example.com/x",
        "content": "body",
        "metadata": {"status_code": 503, "content_type": "text/html"},
        # No top-level status_code, no top-level headers.
    })
    import sqlite3 as _sqlite3
    with _sqlite3.connect(cache.db_path) as conn:
        row = conn.execute("SELECT status_code FROM entries").fetchone()
    assert row[0] == 503


def test_store_accepts_router_screenshots_list(cache: Cache, fake_clock, tmp_path):
    """Router exposes screenshots as a list of stage dicts. Cache must
    cache the ``stage="final"`` entry's path so screenshot fetches
    survive a round-trip through the cache."""
    final_shot = cache.screenshots_dir / "final.png"
    final_shot.write_bytes(b"png bytes" * 100)
    cache.store("https://example.com/x", profile=None, response={
        "ok": True,
        "url": "https://example.com/x",
        "content": "body",
        "screenshots": [
            {"stage": "action", "index": 0, "label": "click", "path": str(tmp_path / "act.png")},
            {"stage": "final", "path": str(final_shot)},
        ],
    })
    hit = cache.lookup("https://example.com/x", profile=None, max_age_ms=60_000)
    assert hit is not None
    assert hit.screenshot_path == str(final_shot)
    assert cache.stats().screenshot_bytes == final_shot.stat().st_size


# -- defensive parsing -----------------------------------------------------


def test_lookup_returns_none_on_corrupted_status_code(cache: Cache, fake_clock):
    """A payload with ``status_code: "ok"`` should not crash lookup —
    int() raises ValueError which the corrupted-payload guard catches."""
    from lightcrawl.canonical import canonicalize_url, url_hash
    url = "https://example.com/corrupt"
    cache.store(url, profile=None, response=_response())
    key = url_hash(canonicalize_url(url), profile=None)
    payload_path = cache.payloads_dir / f"{key}.json"
    data = json.loads(payload_path.read_text())
    data["status_code"] = "not an int"
    payload_path.write_text(json.dumps(data))
    assert cache.lookup(url, profile=None, max_age_ms=60_000) is None


def test_store_cleans_up_tmp_on_write_failure(cache: Cache, fake_clock, monkeypatch):
    """If ``write_bytes`` raises mid-write, the ``.tmp`` file must not
    be left behind to pile up across retries."""
    from pathlib import Path as _P

    def boom(self, data):
        raise OSError("disk full")

    monkeypatch.setattr(_P, "write_bytes", boom)
    with pytest.raises(OSError):
        cache.store("https://example.com/x", profile=None, response=_response())
    tmps = list(cache.payloads_dir.glob("*.tmp"))
    assert tmps == [], f"orphan tmp files: {tmps}"


# -- canonicalization (light sanity — exhaustive coverage in test_canonical) -


def test_lookup_canonicalizes_url(cache: Cache, fake_clock):
    """Trailing-slash / tracking-param differences must not split entries."""
    cache.store(
        "https://Example.com/page?utm_source=x", profile=None,
        response=_response(content="body"),
    )
    hit = cache.lookup("https://example.com/page", profile=None, max_age_ms=60_000)
    assert hit is not None
    assert hit.markdown == "body"
