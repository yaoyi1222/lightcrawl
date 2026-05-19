"""URL canonicalization for cache keys, crawl dedup, and consistent hashing.

This module is the single source of truth for "what does this URL look like
in canonical form" — used by Cache.url_hash, Crawl visited / claimed sets,
Map dedup, and any future component that needs to recognize "same URL".

If two callers compute canonical form differently, cache hit rate and crawl
completeness drift apart. Don't reimplement; always import from here.

URL form usage map (cross-reference v0.3-design.md §5.1):

| Use case                              | URL form used                                          |
|---------------------------------------|--------------------------------------------------------|
| Cache key                             | canonicalize_url(u, ignore_query=False, drop_tracking=True) + profile |
| Crawl dedup (visited / claimed sets)  | same as cache key                                      |
| --include-paths / --exclude-paths     | ORIGINAL URL (pre-canonical) — users may want to filter on utm_*       |
| robots.txt allow check                | ORIGINAL URL (pre-canonical) — robots spec matches on raw path+query   |
| Host / eTLD+1 domain filter           | canonical (lowercased host, default port stripped)     |

Pure functions. No I/O. No mutation. All public functions are deterministic
and idempotent (canonicalize(canonicalize(u)) == canonicalize(u)).
"""
from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


_DEFAULT_PORTS = {"http": 80, "https": 443}


def canonicalize_url(url: str, *, ignore_query: bool = False,
                     drop_tracking: bool = True) -> str:
    """Return a canonical form of ``url`` for cache keys and dedup.

    Steps (order is fixed for testability):
    1. Parse via urllib.parse.urlparse.
    2. scheme & host lowercase. Strip default port (80 / 443).
    3. path: "" -> "/"; strip trailing "/" except for root.
    4. query: sort by key; drop tracking params if drop_tracking=True;
       drop entirely if ignore_query=True.
    5. fragment: always dropped.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    hostname = (parsed.hostname or "").lower()
    # IPv6 literal needs brackets when reconstructed into netloc.
    host_part = f"[{hostname}]" if ":" in hostname else hostname
    if parsed.port is not None and parsed.port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host_part}:{parsed.port}"
    else:
        netloc = host_part

    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # query handled in Task 2; for now pass through unchanged so step 1
    # tests can pass. The Task 2 step will replace this branch.
    query = "" if ignore_query else parsed.query

    return urlunparse((scheme, netloc, path, "", query, ""))


def url_hash(canonical_url: str, *, profile: str | None) -> str:
    """Stub for Task 3 — returns empty string for now."""
    raise NotImplementedError("implemented in Task 3")
