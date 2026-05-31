"""robots.txt allow/disallow subsystem for ``lightcrawl crawl`` (v0.3 PR 6.1).

The crawl engine (PR 6.2) consumes this to answer "may I fetch this URL?".
Parsing/matching is delegated to the stdlib ``urllib.robotparser`` — we only
supply the robots.txt text, fetched through ``Router`` so the read inherits
the SSRF guard and the L1→L2→L3 escalation ladder (design §5.5 #3 / §C2).

Contract: **fail-open**. A missing, unreachable, or unparseable robots.txt
means "no restrictions" — an expected crawl branch, never a hard failure.
robots.txt is fetched at most once per host (cached in ``RobotsCache``).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .router import FetchRequest, Router

# Keep robots.txt inline instead of letting content.maybe_dump truncate it
# (same rationale as sitemap._RAW_BODY_BUDGET).
_RAW_BODY_BUDGET = 10**9


@dataclass
class RobotsRules:
    host: str
    rfp: RobotFileParser | None  # None = no restrictions (fail-open)

    def allows(self, url: str, *, user_agent: str = "*") -> bool:
        if self.rfp is None:
            return True
        return self.rfp.can_fetch(user_agent, url)


async def fetch_robots(host: str, *, scheme: str = "https", router: Router) -> RobotsRules:
    """Fetch and parse ``{scheme}://{host}/robots.txt`` via Router. A 200 with a
    non-empty body is parsed into rules; any non-200, failed fetch, empty body,
    or parse error degrades to permissive (``rfp=None``)."""
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
    if status != 200 or not body.strip():
        return RobotsRules(host, None)
    try:
        rfp = RobotFileParser()
        rfp.parse(body.splitlines())
    except Exception:
        # A malformed robots.txt degrades to permissive rather than aborting.
        return RobotsRules(host, None)
    return RobotsRules(host, rfp)


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
        parsed = urlparse(url)
        host = parsed.netloc
        if host not in self._cache:
            self._cache[host] = await fetch_robots(
                host, scheme=parsed.scheme or "https", router=self._router,
            )
        return self._cache[host].allows(url, user_agent=self._ua)
