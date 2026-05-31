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

设计决定（与用户确认 + PR #61 review 更正）:
- **Parsing/matching via a vendored ~40-line RFC 9309 engine**, NOT stdlib
  `urllib.robotparser`. The original spec premise — "stdlib handles `*`/`$`
  wildcards + longest-match" — was **false** (verified on Python 3.11.15): the
  stdlib matcher is a literal `startswith` on the first matching rule in
  declaration order. It treats `*`/`$` as literal characters (so it *under-blocks*
  `Disallow: /*.php` / `Disallow: /*/admin` — silently fetching disallowed
  pages) and has no longest-match/Allow-wins-tie (so it *over-blocks* the
  broad-`Disallow` + narrow-`Allow` idiom). For a polite crawler the under-block
  is the dangerous direction. We therefore vendor a small matcher
  (`_parse`/`_select_group`/`_pattern_to_regex`/`_path_allowed`): `*`→`.*`,
  trailing `$` anchors, longest-pattern-wins with `Allow` winning ties. The
  robots.txt text is still fetched through `Router`. `protego` (Scrapy's
  RFC-correct parser) is the library alternative; we vendor to keep the module
  zero-dependency (the spec's stated intent).
- **Default `user_agent="*"`** — lightcrawl impersonates a real Chrome
  (chrome120) via curl_cffi, so for robots it behaves as a generic crawler
  obeying the wildcard group. `--user-agent` overrides flow in via 6.3.
- **fail-open** — a missing/unreachable/garbage robots.txt means "no
  restrictions" (design §5.5 #3), an expected branch, never a hard failure.

## 2. 模块形状

```python
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .router import FetchRequest, Router

_RAW_BODY_BUDGET = 10**9
_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass
class _Group:                 # one User-agent group
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)


# RFC 9309 matcher (vendored, ~40 LOC):
#   _parse(text)            -> list[_Group]   (groups User-agents + Allow/Disallow)
#   _select_group(groups, ua) -> _Group|None  (longest agent prefix, else `*`)
#   _pattern_to_regex(pat)  -> re.Pattern     (`*`→.*, trailing `$` anchors)
#   _path_allowed(group, p) -> bool           (longest-pattern wins, Allow wins tie)
#   _match_path(url)        -> str            (raw path + "?" + query)
#   _host_key(url)          -> (scheme, host) (lowercased host, default port stripped)


@dataclass
class RobotsRules:
    host: str
    groups: list[_Group] | None          # None = no restrictions (fail-open)

    def allows(self, url: str, *, user_agent: str = "*") -> bool:
        if self.groups is None:
            return True
        group = _select_group(self.groups, user_agent)
        if group is None:
            return True
        return _path_allowed(group, _match_path(url))


async def fetch_robots(host: str, *, scheme: str = "https", router: Router) -> RobotsRules:
    """Fetch + parse {scheme}://{host}/robots.txt via Router. 200 → parsed
    rules; any non-200 / failed fetch / empty body / parse error → permissive
    (groups=None)."""
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
        scheme, host = _host_key(url)          # normalized host identity
        if host not in self._cache:
            self._cache[host] = await fetch_robots(host, scheme=scheme, router=self._router)
        return self._cache[host].allows(url, user_agent=self._ua)
```

### `fetch_robots` 内部
- Build `{scheme}://{host}/robots.txt`, fetch via Router (strategy=http,
  output_format=html, high budget).
- Strip a leading UTF-8 BOM (`body.lstrip("﻿")`) — IIS / some WordPress
  installs serve one; left in place it makes the first `User-agent` line
  unrecognized and drops every rule (silent fail-open on a restricted site).
- If `resp["ok"]` and `metadata.status_code == 200` and body non-empty:
  `RobotsRules(host, _parse(body))`.
- Otherwise (failed fetch, non-200, empty body): `RobotsRules(host, None)`.
- Wrap `_parse` in `except (ValueError, UnicodeDecodeError)` (narrowed from a
  bare `Exception`, per router.py precedent, so programming errors surface).

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
- **RFC 9309** (PR #61 review): `Disallow: /*.php` blocks `/script.php`;
  `Disallow: /*/admin` blocks `/foo/admin`; `Disallow: /path$` blocks `/path`
  but not `/path/more`; broad `Disallow: /search` + narrow `Allow: /search/about`
  → longest-match allows `/search/about`, blocks `/search/results`; `Allow`
  wins an equal-length tie; BOM-prefixed robots.txt is parsed (not dropped)
- cache key normalizes host: `EX.com` and `ex.com:443` hit one cache entry

## 6. 验证

- `pytest tests/test_robots.py -q` green (15 tests)
- full suite zero regressions (532 → 539)
- `ruff check src/lightcrawl/robots.py src/lightcrawl/errors.py tests/test_robots.py`

## 7. 下游（本 PR 不做）

- 6.2 `crawl.py`: `run_crawl` BFS, `RobotsCache` integration, domain filter,
  include/exclude, `fetch_one` with cache, `pages_skipped_robots` accounting.
- 6.3 crawl CLI: 5 subcommands, signal handlers, `--async`/`--wait`,
  `--ignore-robots-txt` / `--user-agent` flag parsing, startup reconcile,
  `JOB_ALREADY_RUNNING`.
