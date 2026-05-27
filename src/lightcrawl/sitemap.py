"""Domain URL discovery for ``lightcrawl map`` (v0.3 PR 4).

Sitemap-first, homepage-fallback enumeration of in-domain URLs. Everything
fetches through ``Router.fetch`` so it inherits the SSRF guard and the
L1→L2→L3 escalation ladder for free (design §5.3 / §5.6).

Two deliberate choices that differ from a naive implementation:

- **`strategy="http"`** on sitemap/robots fetches: these are XML / plain text,
  L1 (curl_cffi) is sufficient, and skipping the browser saves cost and avoids
  the low-text-density escalation heuristic firing on tag-heavy XML.
- **A very high `max_inline_tokens`**: the content pipeline dumps any body over
  the budget to disk and truncates the inline copy (``content.maybe_dump``).
  A 50k-entry sitemap would be truncated and unparseable, so we keep the raw
  bytes inline by raising the budget for these fetches only.

robots.txt is read **only** to harvest ``Sitemap:`` lines. Allow/disallow
enforcement belongs to crawl (PR 6), not to map.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple
from urllib.parse import urlparse

from lxml import etree

from .canonical import canonicalize_url
from .errors import ErrorCode, FetchError
from .router import FetchRequest, Router

# Memory guard: Cloudflare et al. ship sitemaps up to the 50k spec limit.
MAX_ENTRIES = 50_000
# Index → sub-index → urlset is the deepest legitimate nesting; cap there.
_MAX_DEPTH = 3
# Keep raw XML/robots inline instead of letting content.maybe_dump truncate it.
_RAW_BODY_BUDGET = 10**9


class SitemapEntry(NamedTuple):
    url: str
    lastmod: datetime | None
    changefreq: str | None
    priority: float | None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "lastmod": self.lastmod.isoformat() if self.lastmod else None,
            "changefreq": self.changefreq,
            "priority": self.priority,
        }


@dataclass
class MapResult:
    source: str  # "sitemap" | "homepage"
    urls: list[SitemapEntry]
    count: int  # post dedupe/filter, PRE --limit truncation
    notes: str | None = None

    def to_dict(self) -> dict:
        out: dict = {
            "ok": True,
            "source": self.source,
            "count": self.count,
            "urls": [e.to_dict() for e in self.urls],
        }
        if self.notes is not None:
            out["notes"] = self.notes
        return out


async def _fetch_raw(url: str, *, router: Router) -> tuple[int | None, str]:
    """Fetch ``url`` as raw text via L1. Returns ``(status_code, body)``;
    ``status_code`` is None when the fetch failed outright (DNS, timeout,
    SSRF reject). Note: a 404 is a *successful* fetch with status 404 and
    an error-page body — callers must check the status, not just the body."""
    resp = await router.fetch(FetchRequest(
        url=url,
        strategy="http",
        output_format="html",
        max_inline_tokens=_RAW_BODY_BUDGET,
    ))
    if not resp.get("ok"):
        return None, ""
    status = resp.get("metadata", {}).get("status_code")
    return status, resp.get("content", "") or ""


def _localname(el) -> str:
    if not isinstance(el.tag, str):  # comments / processing instructions
        return ""
    return etree.QName(el).localname


def _child_text(el, name: str) -> str | None:
    for c in el:
        if _localname(c) == name:
            return (c.text or "").strip() or None
    return None


def _parse_lastmod(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_priority(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _looks_like_sitemap(text: str) -> bool:
    low = text.lower()
    return "<urlset" in low or "<sitemapindex" in low


async def discover_sitemaps(seed: str, *, router: Router) -> list[str]:
    """robots.txt ``Sitemap:`` lines first; if none, probe ``/sitemap.xml``
    then ``/sitemap_index.xml``. Returns absolute sitemap URLs (possibly
    empty — a site with no sitemap is a normal homepage-fallback case)."""
    parsed = urlparse(seed)
    base = f"{parsed.scheme}://{parsed.netloc}"

    status, body = await _fetch_raw(f"{base}/robots.txt", router=router)
    if status == 200 and body:
        found: list[str] = []
        for line in body.splitlines():
            if line.strip().lower().startswith("sitemap:"):
                _, _, value = line.partition(":")
                value = value.strip()
                if value and value not in found:
                    found.append(value)
        if found:
            return found

    discovered: list[str] = []
    for path in ("/sitemap.xml", "/sitemap_index.xml"):
        candidate = f"{base}{path}"
        status, body = await _fetch_raw(candidate, router=router)
        if status == 200 and _looks_like_sitemap(body):
            discovered.append(candidate)
    return discovered


async def parse_sitemap(
    url: str, *, router: Router, max_entries: int = MAX_ENTRIES, _depth: int = 0,
) -> list[SitemapEntry]:
    """Parse a sitemap or sitemap index into ``SitemapEntry`` records.

    A ``<sitemapindex>`` recurses into its children (depth-capped). Malformed
    XML raises ``FetchError(SITEMAP_PARSE_ERROR)``; ``run_map`` treats that as
    a soft signal and downgrades to the homepage fallback. A child sitemap that
    fails to parse is skipped so one bad shard doesn't void the whole index."""
    if _depth >= _MAX_DEPTH or max_entries <= 0:
        return []

    status, body = await _fetch_raw(url, router=router)
    if status != 200 or not body:
        return []

    try:
        root = etree.fromstring(body.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        raise FetchError(ErrorCode.SITEMAP_PARSE_ERROR, f"{url}: {e}") from e

    entries: list[SitemapEntry] = []
    root_kind = _localname(root)

    if root_kind == "sitemapindex":
        for sm in root:
            if _localname(sm) != "sitemap" or len(entries) >= max_entries:
                continue
            loc = _child_text(sm, "loc")
            if not loc:
                continue
            try:
                entries.extend(await parse_sitemap(
                    loc, router=router,
                    max_entries=max_entries - len(entries), _depth=_depth + 1,
                ))
            except FetchError as e:
                if e.code != ErrorCode.SITEMAP_PARSE_ERROR:
                    raise
                # skip a malformed child shard, keep the rest
    elif root_kind == "urlset":
        for u in root:
            if _localname(u) != "url" or len(entries) >= max_entries:
                continue
            loc = _child_text(u, "loc")
            if not loc:
                continue
            entries.append(SitemapEntry(
                url=loc,
                lastmod=_parse_lastmod(_child_text(u, "lastmod")),
                changefreq=_child_text(u, "changefreq"),
                priority=_parse_priority(_child_text(u, "priority")),
            ))

    return entries[:max_entries]


def dedupe_canonical(entries: list[SitemapEntry]) -> list[SitemapEntry]:
    """Collapse entries that share a canonical form (trailing slash, tracking
    params, etc.), preserving first-seen order. Uses the same canonicalizer as
    the cache key so map dedup and crawl-visited dedup agree."""
    seen: set[str] = set()
    out: list[SitemapEntry] = []
    for e in entries:
        key = canonicalize_url(e.url)
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


async def run_map(
    seed: str, *, search_filter: str | None, limit: int | None, router: Router,
) -> MapResult:
    """Discover in-domain URLs for ``seed``: sitemap-first, homepage-link
    fallback. ``count`` reflects the deduped/filtered total before any
    ``limit`` truncation; ``notes`` explains an empty or truncated result."""
    entries: list[SitemapEntry] = []
    source = "homepage"

    sitemaps = await discover_sitemaps(seed, router=router)
    if sitemaps:
        for sm in sitemaps:
            if len(entries) >= MAX_ENTRIES:
                break
            try:
                entries.extend(await parse_sitemap(
                    sm, router=router, max_entries=MAX_ENTRIES - len(entries),
                ))
            except FetchError as e:
                if e.code != ErrorCode.SITEMAP_PARSE_ERROR:
                    raise
                # downgrade: leave entries as-is, fall through to homepage below
        if entries:
            source = "sitemap"

    if not entries:
        source = "homepage"
        resp = await router.fetch(FetchRequest(url=seed, output_format="links"))
        links = resp.get("metadata", {}).get("links", []) if resp.get("ok") else []
        entries = [
            SitemapEntry(url=link["url"], lastmod=None, changefreq=None, priority=None)
            for link in links
            if link.get("rel") == "internal"
        ]

    entries = dedupe_canonical(entries)
    if search_filter:
        needle = search_filter.lower()
        entries = [e for e in entries if needle in e.url.lower()]

    count = len(entries)
    notes: str | None = None
    if count == 0:
        if search_filter:
            notes = f"no URLs matched search filter {search_filter!r}"
        elif source == "homepage":
            notes = "no sitemap found and no internal links discovered on the homepage"
        else:
            notes = "sitemap(s) discovered but contained no URLs"
    if limit is not None and count > limit:
        entries = entries[:limit]
        notes = f"truncated to {limit} of {count} discovered URLs"

    return MapResult(source=source, urls=entries, count=count, notes=notes)
