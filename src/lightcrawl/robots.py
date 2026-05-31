"""robots.txt allow/disallow subsystem for ``lightcrawl crawl`` (v0.3 PR 6.1).

The crawl engine (PR 6.2) consumes this to answer "may I fetch this URL?".
robots.txt is fetched through ``Router`` so the read inherits the SSRF guard
and the L1→L2→L3 escalation ladder (design §5.5 #3 / §C2).

Matching is a small RFC 9309 engine (``_Group`` / ``_path_allowed`` /
``_select_group``) rather than ``urllib.robotparser``: the stdlib parser does
NOT implement ``*``/``$`` wildcards or longest-match-wins precedence — it does
a literal ``startswith`` on the first matching rule in declaration order. That
silently *under-blocks* the very common ``Disallow: /*.ext`` / ``Disallow:
/*/path`` patterns (fetching pages the site disallowed) and *over-blocks* the
standard broad-``Disallow`` + narrow-``Allow`` idiom. For a polite crawler the
under-block is the dangerous direction, so we match per the spec instead.
(``protego``, used by Scrapy, is the RFC-correct library alternative; we vendor
the ~40-line matcher to keep the module zero-dependency.)

Contract: **fail-open**. A missing, unreachable, or unparseable robots.txt
means "no restrictions" — an expected crawl branch, never a hard failure.
robots.txt is fetched at most once per host (cached in ``RobotsCache``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .router import FetchRequest, Router

# Keep robots.txt inline instead of letting content.maybe_dump truncate it
# (same rationale as sitemap._RAW_BODY_BUDGET).
_RAW_BODY_BUDGET = 10**9

_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass
class _Group:
    """One ``User-agent`` group: the agent tokens it covers (lowercased) and
    its ordered ``(allow, pattern)`` rules."""

    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)


def _parse(text: str) -> list[_Group]:
    """Parse robots.txt into groups. Consecutive ``User-agent`` lines share the
    following rule block; the first rule line after a group closes that group,
    so the next ``User-agent`` starts a fresh one. Empty ``Allow``/``Disallow``
    values impose no restriction (RFC 9309) and are dropped."""
    groups: list[_Group] = []
    cur: _Group | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if cur is None or cur.rules:
                cur = _Group()
                groups.append(cur)
            cur.agents.append(value.lower())
        elif key in ("allow", "disallow") and cur is not None and value:
            cur.rules.append((key == "allow", value))
    return groups


def _select_group(groups: list[_Group], user_agent: str) -> _Group | None:
    """RFC 9309 §2.2.1: pick the group whose agent token is the longest
    case-insensitive prefix of ``user_agent``; fall back to the ``*`` group.
    Our default UA ``"*"`` therefore lands on the wildcard group."""
    ua = user_agent.lower()
    best: _Group | None = None
    best_len = -1
    star: _Group | None = None
    for g in groups:
        for agent in g.agents:
            if agent == "*":
                star = g
            elif ua.startswith(agent) and len(agent) > best_len:
                best, best_len = g, len(agent)
    return best if best is not None else star


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """Translate a robots path pattern to an anchored regex. ``*`` matches any
    run of characters; a trailing ``$`` anchors the end; everything else is
    literal. Matched with ``.match`` so it anchors at the path start."""
    end_anchor = pattern.endswith("$")
    body = pattern[:-1] if end_anchor else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile(regex + ("$" if end_anchor else ""))


def _path_allowed(group: _Group, path: str) -> bool:
    """RFC 9309 §2.2.2 longest-match-wins, ``Allow`` wins an exact-length tie.
    Specificity is the pattern length in characters (``*``/``$`` included)."""
    best_len = -1
    decision = True  # no matching rule → allowed
    for allow, pattern in group.rules:
        if _pattern_to_regex(pattern).match(path) is None:
            continue
        length = len(pattern)
        if length > best_len or (length == best_len and allow):
            best_len, decision = length, allow
    return decision


def _match_path(url: str) -> str:
    """The path (plus query) robots matches against, per canonical.py's URL map
    ('robots.txt allow check → raw path+query')."""
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return path


def _host_key(url: str) -> tuple[str, str]:
    """Return ``(scheme, host_key)`` where ``host_key`` is normalized the same
    way canonical.py treats host identity: lowercased host, default port
    stripped. Keeps the per-host robots cache from fetching ``EXAMPLE.COM`` and
    ``example.com`` (or ``:443`` vs bare) twice."""
    parts = urlsplit(url)
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    if parts.port is not None and parts.port != _DEFAULT_PORTS.get(scheme):
        host = f"{host}:{parts.port}"
    return scheme, host


@dataclass
class RobotsRules:
    host: str
    groups: list[_Group] | None  # None = no restrictions (fail-open)

    def allows(self, url: str, *, user_agent: str = "*") -> bool:
        if self.groups is None:
            return True
        group = _select_group(self.groups, user_agent)
        if group is None:
            return True
        return _path_allowed(group, _match_path(url))


async def fetch_robots(host: str, *, scheme: str = "https", router: Router) -> RobotsRules:
    """Fetch and parse ``{scheme}://{host}/robots.txt`` via Router. A 200 with a
    non-empty body is parsed into rules; any non-200, failed fetch, empty body,
    or parse error degrades to permissive (``groups=None``)."""
    resp = await router.fetch(FetchRequest(
        url=f"{scheme}://{host}/robots.txt",
        strategy="http",
        output_format="html",
        max_inline_tokens=_RAW_BODY_BUDGET,
    ))
    if not resp.get("ok"):
        return RobotsRules(host, None)
    status = resp.get("metadata", {}).get("status_code")
    body = resp.get("content", "") or ""
    # Strip a leading UTF-8 BOM (IIS / some WordPress installs serve one); left
    # in place it makes the first "User-agent" line unrecognized and drops every
    # rule, silently failing open on a site that actually has restrictions.
    body = body.lstrip("﻿")
    if status != 200 or not body.strip():
        return RobotsRules(host, None)
    try:
        groups = _parse(body)
    except (ValueError, UnicodeDecodeError):
        # Narrowed from bare `Exception` so programming errors (TypeError on a
        # bad body shape, etc.) surface instead of silently failing open.
        return RobotsRules(host, None)
    return RobotsRules(host, groups)


class RobotsCache:
    """Per-host lazy-fetch + cache of robots rules. The crawl engine holds one
    instance and calls ``allows()`` before enqueuing each URL. ``ignore=True``
    (``--ignore-robots-txt``) skips the subsystem entirely."""

    def __init__(self, *, router: Router, ignore: bool = False, user_agent: str = "*"):
        self._router = router
        self._ignore = ignore
        self._ua = user_agent
        self._cache: dict[str, RobotsRules] = {}

    async def allows(self, url: str) -> bool:
        if self._ignore:
            return True
        scheme, host = _host_key(url)
        if host not in self._cache:
            self._cache[host] = await fetch_robots(host, scheme=scheme, router=self._router)
        return self._cache[host].allows(url, user_agent=self._ua)
