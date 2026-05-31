# PR 6.1 — `robots.py` (robots.txt allow/disallow subsystem)

> v0.3 tracker #22 · design.md §5.5 #3 / §C2 / §7 · 2026-05-31

First slice of PR 6 (crawl). PR 6 was decomposed into three stacked PRs:
**6.1 robots** → 6.2 crawl engine → 6.3 crawl CLI. This spec covers 6.1 only.

## 1. 范围与边界

`robots.py` is the self-contained robots.txt subsystem the crawl engine (6.2)
will consume to answer "may I fetch this URL?". It parses allow/disallow rules
and caches them per host. No crawl business logic, no CLI.

**纳入 6.1:** `RobotsRules`, `fetch_robots`, `RobotsCache`, the `ROBOTS_DISALLOWED`
error code, and `tests/test_robots.py`.

**不在 6.1（留给 6.2 / 6.3）:** the BFS engine / `run_crawl`, the
`progress.pages_skipped_robots` accounting, the `--ignore-robots-txt` flag
*parsing*, and all CLI subcommands. 6.1 only supports the `ignore` parameter;
the flag is wired in 6.3.

设计决定（与用户确认）:
- **Parsing/matching via stdlib `urllib.robotparser.RobotFileParser`** — fetch
  robots.txt through `Router` (keeps SSRF guard + L1→L2 escalation), feed the
  pre-fetched text to `RobotFileParser.parse(lines)`, then judge with
  `rfp.can_fetch(ua, url)`. Battle-tested, zero new deps, handles UA groups and
  `*`/`$` wildcards. Rejected a hand-rolled parser (reinvents group selection /
  longest-match / anchoring).
- **Default `user_agent="*"`** — lightcrawl impersonates a real Chrome
  (chrome120) via curl_cffi, so for robots it behaves as a generic crawler
  obeying the wildcard group. `--user-agent` overrides flow in via 6.3.
- **fail-open** — a missing/unreachable/garbage robots.txt means "no
  restrictions" (design §5.5 #3), an expected branch, never a hard failure.

## 2. 模块形状

```python
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
    rfp: RobotFileParser | None          # None = no restrictions (fail-open)

    def allows(self, url: str, *, user_agent: str = "*") -> bool:
        if self.rfp is None:
            return True
        return self.rfp.can_fetch(user_agent, url)


async def fetch_robots(host: str, *, scheme: str = "https", router: Router) -> RobotsRules:
    """Fetch + parse {scheme}://{host}/robots.txt via Router. 200 → parsed
    rules; any non-200 / failed fetch / parse error → permissive (rfp=None)."""
    ...


class RobotsCache:
    """Per-host lazy-fetch + cache of robots rules. The crawl engine (6.2)
    holds one instance and calls allows() before enqueuing each URL."""

    def __init__(self, *, router: Router, ignore: bool = False, user_agent: str = "*"):
        self._router = router
        self._ignore = ignore
        self._ua = user_agent
        self._cache: dict[str, RobotsRules] = {}

    async def allows(self, url: str) -> bool:
        if self._ignore:                       # --ignore-robots-txt short-circuit
            return True
        parsed = urlparse(url)
        host = parsed.netloc
        if host not in self._cache:
            self._cache[host] = await fetch_robots(
                host, scheme=parsed.scheme or "https", router=self._router,
            )
        return self._cache[host].allows(url, user_agent=self._ua)
```

### `fetch_robots` 内部
- Build `{scheme}://{host}/robots.txt`.
- `await router.fetch(FetchRequest(url=..., strategy="http", output_format="html",
  max_inline_tokens=_RAW_BODY_BUDGET))`.
- If `resp["ok"]` and `metadata.status_code == 200` and body non-empty:
  `rfp = RobotFileParser(); rfp.parse(body.splitlines())` → `RobotsRules(host, rfp)`.
- Otherwise (failed fetch, non-200, or empty body): `RobotsRules(host, None)`.
- Wrap the `parse` in a try/except so a malformed robots.txt degrades to
  permissive rather than raising.

> **Raw fetch:** mirrors `sitemap._fetch_raw` (strategy=http, high budget) but
> robots.py keeps its own ~8-line fetch to avoid a robots↔sitemap cross-module
> coupling. Acceptable small duplication.

## 3. 契约

- **fail-open:** 404 / network failure / parse error → `allows()` returns True.
  This is an expected crawl branch, not a failure.
- **per-host lazy fetch:** each host's robots.txt is fetched at most once and
  cached (design review C2).
- **UA:** default `"*"`; `--user-agent` override threaded through in 6.3.
- **`ROBOTS_DISALLOWED`** added to `errors.py` (next to `SITEMAP_PARSE_ERROR` /
  the job codes). 6.1 only defines it; 6.2's engine attaches it to URLs skipped
  by robots and bumps `progress.pages_skipped_robots`. Convention (design §7):
  it is an "expected branch", `ok` may still be true.

## 4. 错误处理

- No raised errors at the public boundary of this subsystem — `allows()` and
  `fetch_robots()` always return a value (errors-as-values). A failed Router
  fetch is read from the returned envelope, never re-raised.

## 5. 测试（`tests/test_robots.py`，全离线）

Reuse the `test_sitemap.py` monkeypatch pattern (patch
`lightcrawl.url_safety.socket.gethostbyname` → public IP and
`lightcrawl.fetch_http.fetch` with a canned-robots.txt routing table).

- `User-agent: *` + `Disallow: /private` → `/private/x` denied, `/public` allowed
- multiple UA groups → the `*` group governs our default UA
- robots.txt 404 / failed fetch → fail-open (everything allowed)
- empty robots.txt → everything allowed
- `RobotsCache` fetches a host's robots.txt at most once (assert fetch call count)
- different hosts cached independently
- `ignore=True` → no fetch performed, everything allowed

## 6. 验证

- `pytest tests/test_robots.py -q` green
- full suite zero regressions (524 → ~534)
- `ruff check src/lightcrawl/robots.py src/lightcrawl/errors.py tests/test_robots.py`

## 7. 下游（本 PR 不做）

- 6.2 `crawl.py`: `run_crawl` BFS, `RobotsCache` integration, domain filter,
  include/exclude, `fetch_one` with cache, `pages_skipped_robots` accounting.
- 6.3 crawl CLI: 5 subcommands, signal handlers, `--async`/`--wait`,
  `--ignore-robots-txt` / `--user-agent` flag parsing, startup reconcile,
  `JOB_ALREADY_RUNNING`.
