# PR 1 — `canonical.py` + 翻转 `remove_base64_images` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 v0.3 的第一块基石:一个纯函数模块 `canonical.py`(URL 规范化 + 带 profile 维度的 cache key 哈希),并把 `remove_base64_images` 默认值从 False 翻为 True;同时同步必要的代码注释与 CHANGELOG。

**Architecture:** `canonical.py` 是 v0.3 的**单一规范化真理来源** —— cache key、crawl 去重、map 输出去重、search-and-read 的潜在合并都共用此函数。纯函数、无 I/O、表驱动测试 30+。`url_hash` 把 profile 维度纳入 sha1 输入,确保 `twitter` profile 抓的页面不会被无 profile 的调用方回放(v0.3-design.md §5.2 安全不变量)。默认翻转是 v0.3 唯一破坏性变更,提前在 PR 1 完成,后续 PR 在新默认上构建。

**Tech Stack:** Python 3.10+,标准库 `urllib.parse` + `hashlib`,pytest(已配置 `asyncio_mode=auto`),ruff(已有项目规则)。**不引入新依赖**(psutil 留给 PR 5)。

**Spec source:** `v0.3-design.md` §1, §5.1, §5.2, §6, §12 (PR 1 行),§13;`v0.3-review.md` A2 / nit "test_pr1a_params 默认更新"。

**Prerequisites:** repo 处于 `main` 分支干净状态;`.venv` 已 `pip install -e ".[dev,bench]"`;`pytest -q` 全绿(270 测试基线)。

---

## File Structure

| 文件 | 操作 | 责任 |
|---|---|---|
| `src/lightcrawl/canonical.py` | **Create** | URL 规范化 + url_hash(含 profile)+ URL 形态用途表(module docstring) |
| `tests/test_canonical.py` | **Create** | 表驱动测试,覆盖 30+ 用例:scheme/host/port、path、query、tracking、IPv6、profile 隔离、idempotency |
| `src/lightcrawl/router.py` | **Modify** L56-58 | 翻转 `FetchRequest.remove_base64_images` 默认值 + 更新注释 |
| `src/lightcrawl/content.py` | **Modify** L550 | 翻转 `html_to_markdown(remove_base64_images=False)` 函数级默认,与 FetchRequest 一致 |
| `tests/test_pr1b_mobile.py` | **Modify** L315-323, L355-374 | 重写两个固定 v0.1 默认行为的测试,改测 v0.3 新默认 |
| `CHANGELOG.md` | **Create** | 项目首个 CHANGELOG,记录 v0.3 进行中变更 |

新增模块 `canonical.py` 没有运行时依赖任何已有模块,可独立测试 / 提交。`remove_base64_images` 翻转触发 `test_pr1b_mobile.py` 中两个测试失败 —— 这是预期的(测试在主动锁定旧默认),需要重写。

---

## Task 1: canonical.py 骨架 + 基础规范化(scheme / host / port / path / fragment)

**Files:**
- Create: `src/lightcrawl/canonical.py`
- Test: `tests/test_canonical.py`

- [ ] **Step 1.1: 写第一组失败测试 — scheme / host 小写、默认端口剥离、path 处理、fragment 丢弃**

写入 `tests/test_canonical.py`:

```python
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
```

- [ ] **Step 1.2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_canonical.py -q`
Expected: `ModuleNotFoundError: No module named 'lightcrawl.canonical'`(12 个 collection errors)。

- [ ] **Step 1.3: 实现 canonical.py 第一版,通过 step 1.1 的所有测试**

写入 `src/lightcrawl/canonical.py`:

```python
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
```

- [ ] **Step 1.4: 跑测试确认全过**

Run: `.venv/bin/pytest tests/test_canonical.py -q`
Expected: 12 passed.

- [ ] **Step 1.5: 提交**

```bash
git add src/lightcrawl/canonical.py tests/test_canonical.py
git commit -m "feat(canonical): scaffold URL canonicalization (scheme/host/port/path/fragment)

First slice of v0.3 PR 1. Pure-function module that will become the single
source of truth for cache keys and crawl dedup. Twelve table-driven tests
cover scheme/host lowercase, default port stripping, path normalization,
and fragment dropping. Query handling stub deferred to Task 2; url_hash
to Task 3."
```

---

## Task 2: canonical.py — query handling(sort / drop_tracking / ignore_query)

**Files:**
- Modify: `src/lightcrawl/canonical.py` — replace the query stub in `canonicalize_url`
- Modify: `tests/test_canonical.py` — append query tests

- [ ] **Step 2.1: 追加失败测试**

Append to `tests/test_canonical.py`:

```python
# ----- query handling --------------------------------------------------------

def test_keeps_single_query_param():
    assert canonicalize_url("https://example.com/p?a=1") == "https://example.com/p?a=1"


def test_sorts_query_params_by_key():
    assert canonicalize_url("https://example.com/p?b=2&a=1") == "https://example.com/p?a=1&b=2"


def test_preserves_percent_encoded_chars():
    # %20 (space) should pass through after a parse_qsl+urlencode round-trip.
    assert canonicalize_url("https://example.com/p?q=hello%20world") == "https://example.com/p?q=hello+world"
    # Note: urlencode emits '+' for space in query, which is RFC-3986 equivalent.
    # We document this as canonical form.


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
```

- [ ] **Step 2.2: 跑测试确认新测试失败**

Run: `.venv/bin/pytest tests/test_canonical.py -q`
Expected: 12 passed (旧), 11 failed (新 query 测试)。具体失败原因:`drop_tracking` 还没生效、query 还没排序。

- [ ] **Step 2.3: 实现 query handling,替换 `canonicalize_url` 中的 query 分支**

修改 `src/lightcrawl/canonical.py` —— 在 `_DEFAULT_PORTS` 下方加 `_TRACKING_PARAMS` 常量,并替换 `canonicalize_url` 函数中的 query 分支:

```python
# Tracking query params dropped during canonicalization (drop_tracking=True).
# Sources: GA / Meta / LinkedIn / Twitter / Mailchimp common params. Extend
# carefully — every addition is a backwards-incompatible change to cache keys.
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name",
    "fbclid", "gclid", "dclid", "msclkid", "yclid",
    "ref", "ref_src", "ref_url",
    "mc_cid", "mc_eid",
    "_ga", "_gl",
})
```

并把 `canonicalize_url` 中的:
```python
    # query handled in Task 2 ...
    query = "" if ignore_query else parsed.query
```
替换为:
```python
    if ignore_query:
        query = ""
    else:
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        if drop_tracking:
            pairs = [(k, v) for k, v in pairs if k.lower() not in _TRACKING_PARAMS]
        pairs.sort(key=lambda kv: kv[0])
        query = urlencode(pairs)
```

- [ ] **Step 2.4: 跑测试确认全过**

Run: `.venv/bin/pytest tests/test_canonical.py -q`
Expected: 23 passed.

- [ ] **Step 2.5: 提交**

```bash
git add src/lightcrawl/canonical.py tests/test_canonical.py
git commit -m "feat(canonical): query handling — sort, drop tracking params, ignore_query

Adds _TRACKING_PARAMS frozenset (utm_*, fbclid, gclid, ref, mc_cid, _ga,
etc., ~16 entries). Default drop_tracking=True. ignore_query=True drops
the whole query string. parse_qsl(keep_blank_values=True) preserves
?flag bare keys. 11 new tests; total 23."
```

---

## Task 3: canonical.py — `url_hash` with profile dimension

**Files:**
- Modify: `src/lightcrawl/canonical.py` — implement `url_hash`
- Modify: `tests/test_canonical.py` — append url_hash tests

- [ ] **Step 3.1: 追加失败测试,锁定 profile 隔离不变量**

Append to `tests/test_canonical.py`:

```python
# ----- url_hash with profile dimension --------------------------------------

def test_url_hash_is_40_hex_chars():
    h = url_hash("https://example.com/p", profile=None)
    assert len(h) == 40
    assert all(c in "0123456789abcdef" for c in h)


def test_url_hash_deterministic():
    h1 = url_hash("https://example.com/p", profile=None)
    h2 = url_hash("https://example.com/p", profile=None)
    assert h1 == h2


def test_url_hash_profile_none_equals_empty_string():
    # API ergonomics: None and "" are both "no profile" — must hash same.
    h_none = url_hash("https://example.com/p", profile=None)
    h_empty = url_hash("https://example.com/p", profile="")
    assert h_none == h_empty


def test_url_hash_different_profile_yields_different_hash():
    # The core security invariant. v0.3-design.md §5.2: a profile=twitter
    # fetch of x.com/private must not be served back to a profile=None caller.
    h_none = url_hash("https://x.com/private", profile=None)
    h_twitter = url_hash("https://x.com/private", profile="twitter")
    h_github = url_hash("https://x.com/private", profile="github")
    assert h_none != h_twitter
    assert h_twitter != h_github
    assert h_none != h_github


def test_url_hash_separator_prevents_collision():
    # A naive concat (url + profile) would collide:
    #   url="x.com/a",  profile="b"     and
    #   url="x.com/ab", profile=""
    # The "\0" separator must make these distinct.
    h1 = url_hash("https://x.com/a", profile="b")
    h2 = url_hash("https://x.com/ab", profile="")
    assert h1 != h2
```

- [ ] **Step 3.2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_canonical.py -q`
Expected: 23 passed (旧), 5 errors (新测试),原因 `NotImplementedError: implemented in Task 3`。

- [ ] **Step 3.3: 实现 `url_hash`,替换 stub**

修改 `src/lightcrawl/canonical.py`,把 `url_hash` 函数体替换为:

```python
def url_hash(canonical_url: str, *, profile: str | None) -> str:
    """Cache key for (canonical_url, profile) pairs. 40-hex sha1.

    The profile dimension is a security boundary, not an optimization. A
    `profile=twitter` fetch of x.com/private produces a different hash from
    a `profile=None` call to the same URL, preventing cross-profile data
    leak via cache replay. See v0.3-design.md §5.2.

    profile=None and profile="" both mean "no profile" and hash identically.
    The "\\0" separator between url and profile prevents collisions where
    a longer url + empty profile would equal a shorter url + non-empty
    profile under naive concatenation.
    """
    profile_str = profile or ""
    payload = canonical_url + "\0" + profile_str
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 3.4: 跑测试确认全过**

Run: `.venv/bin/pytest tests/test_canonical.py -q`
Expected: 28 passed.

- [ ] **Step 3.5: 提交**

```bash
git add src/lightcrawl/canonical.py tests/test_canonical.py
git commit -m "feat(canonical): url_hash with profile dimension (cache key safety)

profile participates in the sha1 input so cross-profile cache replay
is impossible (v0.3-design.md §5.2 security invariant). \"\\0\" separator
between canonical_url and profile prevents naive-concat collisions. None
and \"\" both map to the same hash for API ergonomics. 5 new tests; total 28."
```

---

## Task 4: canonical.py — IPv6 + idempotency + edge cases

**Files:**
- Modify: `tests/test_canonical.py` — append edge-case tests
- canonical.py 的 IPv6 分支已在 Task 1 中预埋(`":" in hostname` 检测),本任务**主要靠测试覆盖**;若测试发现 bug 则改实现。

- [ ] **Step 4.1: 追加边角测试**

Append to `tests/test_canonical.py`:

```python
# ----- edge cases ------------------------------------------------------------

def test_ipv4_literal_host():
    assert canonicalize_url("http://127.0.0.1/p") == "http://127.0.0.1/p"


def test_ipv4_literal_with_port():
    assert canonicalize_url("http://127.0.0.1:8080/p") == "http://127.0.0.1:8080/p"


def test_ipv6_literal_host():
    assert canonicalize_url("http://[::1]/p") == "http://[::1]/p"


def test_ipv6_literal_with_port():
    assert canonicalize_url("http://[::1]:8080/p") == "http://[::1]:8080/p"


def test_ipv6_default_port_stripped():
    # urlparse should expose port=80; we strip it because http default is 80.
    assert canonicalize_url("http://[::1]:80/p") == "http://[::1]/p"


def test_mixed_case_scheme_normalized():
    assert canonicalize_url("HTTP://Example.com:80/") == "http://example.com/"


def test_canonicalize_is_idempotent():
    # canonicalize(canonicalize(u)) == canonicalize(u). Critical property:
    # otherwise cache key would drift on re-canonicalization.
    samples = [
        "HTTPS://Example.COM:443/Foo/?utm_source=x&b=2&a=1#frag",
        "http://[::1]:80/",
        "https://example.com/p?flag&other=1",
        "https://example.com/foo/",
    ]
    for u in samples:
        once = canonicalize_url(u)
        twice = canonicalize_url(once)
        assert once == twice, f"non-idempotent: {u!r} -> {once!r} -> {twice!r}"


def test_url_without_path_idempotent():
    # "https://example.com" has empty path; first pass adds "/", second
    # must not double it or strip it.
    assert canonicalize_url(canonicalize_url("https://example.com")) == "https://example.com/"


def test_query_only_url():
    # No path, only query. Canonicalize path to "/" and keep query.
    assert canonicalize_url("https://example.com?a=1") == "https://example.com/?a=1"


def test_userinfo_in_url_is_dropped():
    # urlparse keeps userinfo in netloc; parsed.hostname extracts host only.
    # Our reconstruction uses hostname, effectively dropping userinfo.
    # This is intentional: userinfo is sensitive and rarely correct in fetched URLs.
    assert canonicalize_url("https://user:pass@example.com/p") == "https://example.com/p"
```

- [ ] **Step 4.2: 跑测试**

Run: `.venv/bin/pytest tests/test_canonical.py -q`
Expected: 38 passed.

如果有失败:大概率是 IPv6 端口检测分支。读取 `canonical.py` 中 `host_part` 计算逻辑,检查 `parsed.hostname` 对 `[::1]` 是否返回 `"::1"`(无方括号),`parsed.port` 是否正确解析。Python `urlparse` 的标准行为应该已满足,但若测试失败,在本步骤内迭代修复 — 不开新 commit。

- [ ] **Step 4.3: 提交**

```bash
git add tests/test_canonical.py
git commit -m "test(canonical): IPv6 literals, idempotency, userinfo, mixed-case edge cases

Locks the canonicalize(canonicalize(u)) == canonicalize(u) invariant
across representative samples. IPv6 bracket reconstruction tested with
and without ports, including default-port stripping. Userinfo is
intentionally dropped (security; v0.3-design.md §5.1). 10 new tests;
total 38."
```

---

## Task 5: canonical.py — module docstring (URL form usage table) 已就位的最后核对

The module docstring was written in Task 1 (Step 1.3) with the full URL form usage table. This task verifies it and cross-references it from elsewhere if needed.

- [ ] **Step 5.1: 验证 docstring 与设计文档一致**

```bash
.venv/bin/python -c "import lightcrawl.canonical as c; print(c.__doc__)"
```

Expected: 输出的 docstring 包含 "URL form usage map" 表,5 行(cache key / crawl dedup / include-exclude / robots / domain filter)。如果缺失或不一致,修订 `canonical.py` 顶部 docstring 与 `v0.3-design.md` §5.1 表对齐。

- [ ] **Step 5.2: 检查 lint**

Run: `.venv/bin/ruff check src/lightcrawl/canonical.py tests/test_canonical.py`
Expected: `All checks passed!`

如有问题立刻修(通常是 import 顺序或行长),不开新 commit。

- [ ] **Step 5.3: 跑全套 canonical 测试 + 总 lint**

```bash
.venv/bin/pytest tests/test_canonical.py -q
.venv/bin/ruff check src tests
```
Expected: 38 passed; ruff 通过。

本任务无新提交 —— docstring 已在 Task 1 落地。

---

## Task 6: 翻转 `remove_base64_images` 默认值

**Files:**
- Modify: `src/lightcrawl/router.py:56-58`(FetchRequest 字段 + 注释)
- Modify: `src/lightcrawl/content.py:550`(html_to_markdown 函数级默认)
- Modify: `tests/test_pr1b_mobile.py:315-323, 355-374`(重写两个测旧默认的用例)

- [ ] **Step 6.1: 先确认基线 — 跑 PR1b 相关测试,看清旧行为绿色**

```bash
.venv/bin/pytest tests/test_pr1b_mobile.py -q
```
Expected: 全部通过(基线绿)。

- [ ] **Step 6.2: 翻转 FetchRequest 默认值 + 更新注释**

修改 `src/lightcrawl/router.py`,定位到 v0.2 PR 1b 块(L50-58 附近),把:

```python
    # v0.2 PR 1b — mobile emulation + base64 image stripping
    # mobile=True switches both layers: L1 uses curl_cffi's iOS Safari
    # impersonate profile (UA + TLS fingerprint together — flipping UA
    # alone is itself a bot signal); L2 uses Playwright's "iPhone 13"
    # device descriptor.
    mobile: bool = False
    # Default False preserves byte-identical v0.1 responses. v0.3 plans
    # to flip the default to True with a README announcement.
    remove_base64_images: bool = False
```

替换为:

```python
    # v0.2 PR 1b — mobile emulation + base64 image stripping
    # mobile=True switches both layers: L1 uses curl_cffi's iOS Safari
    # impersonate profile (UA + TLS fingerprint together — flipping UA
    # alone is itself a bot signal); L2 uses Playwright's "iPhone 13"
    # device descriptor.
    mobile: bool = False
    # v0.3 default flip: was False in v0.2 (byte-identical to v0.1).
    # Now True because base64 data: URIs explode token cost and cache
    # size while contributing nothing to LLM consumption. External <img>
    # tags survive into markdown. See v0.3-design.md §6.
    remove_base64_images: bool = True
```

- [ ] **Step 6.3: 翻转 html_to_markdown 函数级默认**

修改 `src/lightcrawl/content.py:550`,把:

```python
    remove_base64_images: bool = False,
```

替换为:

```python
    remove_base64_images: bool = True,  # v0.3 default flip; see router.FetchRequest
```

- [ ] **Step 6.4: 跑测试,看预期失败**

```bash
.venv/bin/pytest tests/test_pr1b_mobile.py -q
```
Expected: 2 个测试失败 —— `test_default_strips_all_images_v01_behavior` 和 `test_default_behavior_strips_picture_source_img_together`。这两个测试**主动锁定旧默认**,翻转后理应失败。这正是要修的。

如果失败的测试数量 ≠ 2,先停下检查为什么 —— 可能漏了某处或多翻了某处。

- [ ] **Step 6.5: 重写两个固定旧默认的测试**

修改 `tests/test_pr1b_mobile.py`。

定位 L315-323 `test_default_strips_all_images_v01_behavior`,完整替换为:

```python
def test_default_v03_keeps_external_strips_only_base64():
    """v0.3 default `remove_base64_images=True`: data: URIs are stripped,
    external <img> tags survive into markdown. This replaces the v0.2
    `test_default_strips_all_images_v01_behavior` test — same input HTML,
    inverted expectations to match the new default."""
    out = content_mod.html_to_markdown(_HTML_WITH_IMAGES)
    assert "iVBORw0K" not in out.markdown            # base64 payload gone
    assert "data:image" not in out.markdown          # no data: URI
    assert "example.com/logo.png" in out.markdown    # external image survived
    assert "Pictures" in out.markdown                # body intact
```

定位 L355-374 `test_default_behavior_strips_picture_source_img_together`,完整替换为:

```python
def test_default_v03_keeps_picture_source_img():
    """v0.3 default keeps the external <img> even when nested inside
    <picture><source>...</picture>. <svg> remains always stripped (it's
    in _REMOVE_TAGS regardless of the flag). Replaces v0.2's
    `test_default_behavior_strips_picture_source_img_together`."""
    html = (
        "<html><body>"
        "<picture>"
        '<source srcset="https://e.com/x.webp">'
        '<img src="https://e.com/x.png" alt="x">'
        "</picture>"
        '<svg><path d="M0,0"/></svg>'
        "<p>body text long enough to bypass the tiny-body escalation "
        "heuristic and produce stable markdown.</p>"
        "</body></html>"
    )
    out = content_mod.html_to_markdown(html)  # default: True in v0.3
    assert "e.com/x.png" in out.markdown      # external <img> survives
    assert "M0,0" not in out.markdown         # <svg> always stripped
    assert "body text" in out.markdown        # body intact
```

- [ ] **Step 6.6: 跑测试确认全过**

```bash
.venv/bin/pytest tests/test_pr1b_mobile.py -q
```
Expected: 全部通过。

- [ ] **Step 6.7: 跑全部测试套件确认无其他回归**

```bash
.venv/bin/pytest -q
```
Expected: 全过(原 270 测试 + 38 canonical = 308),零失败。

如果其它测试文件因为默认翻转失败:**不要在本任务里修**。停下,记录失败列表,在 PR 1 内为这些追加修复 commit(如 Step 6.8)。

- [ ] **Step 6.8: (Conditional) 修复其它意外的默认相关测试**

如果 Step 6.7 出现 `test_pr1b_mobile.py` 之外的失败:逐个核查,通常是某个集成测试隐式依赖"默认 strip 一切" 行为。修复方式:在该测试调用 `html_to_markdown` 或 `FetchRequest` 时显式传 `remove_base64_images=False`(若它在测旧行为),或更新期望(若它在测新行为)。每个文件单独 commit。如果**没有**新的失败,跳过本步。

- [ ] **Step 6.9: 提交**

```bash
git add src/lightcrawl/router.py src/lightcrawl/content.py tests/test_pr1b_mobile.py
git commit -m "feat!: flip remove_base64_images default to True (v0.3 breaking change)

The only intentionally-breaking default change in v0.3. Rationale:
base64 data: URIs explode token count and cache size with negligible
LLM value; external <img> tags continue to land in markdown. v0.2
README pre-announced this; v0.3 README will carry the changelog entry.

- src/lightcrawl/router.py: FetchRequest.remove_base64_images: False -> True
- src/lightcrawl/content.py: html_to_markdown(remove_base64_images=...) likewise
- tests/test_pr1b_mobile.py: replaced two v0.1-pinned tests with v0.3-default
  equivalents. Coverage of remove_base64_images=False is still present via
  the explicit-flag tests elsewhere in the file.

See v0.3-design.md §6."
```

---

## Task 7: 文档同步 — CHANGELOG.md + router.py comment 已就位的最后核对

**Files:**
- Create: `CHANGELOG.md`(项目首个 CHANGELOG 文件)

`router.py:58` 的注释已在 Task 6 更新,无需再动。

- [ ] **Step 7.1: 创建 CHANGELOG.md**

写入 `CHANGELOG.md`(repo 根目录):

```markdown
# Changelog

All notable changes to lightcrawl are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); dates are
ISO 8601.

## [Unreleased] — v0.3 (in progress)

v0.3 upgrades lightcrawl from "enhanced WebFetch" to "local firecrawl"
with map / crawl / cache as the headline features. See `v0.3-design.md`
for the full plan. This entry is updated PR-by-PR.

### Breaking changes

- **`remove_base64_images` default flipped from `False` to `True`.**
  Affects both `FetchRequest.remove_base64_images` and the
  `html_to_markdown(remove_base64_images=...)` function-level default.
  v0.2 stripped every `<img>` by default for byte-identical v0.1 output;
  v0.3 strips only `data:` URI images, letting external `<img>` tags
  flow into markdown. To restore v0.2 behavior, pass
  `remove_base64_images=False` explicitly.

### Added

- `src/lightcrawl/canonical.py` — pure-function URL canonicalization and
  `url_hash(canonical_url, profile=...)` used as the single source of
  truth for cache keys and crawl dedup. The `profile` dimension is a
  security boundary: an authed fetch of a URL with `profile=twitter`
  produces a different hash than an unauthed fetch of the same URL,
  preventing cross-profile cache replay.

## [0.2.0] — 2026-05-18

See `git log v0.2.0` and PR #16–#21 for the full v0.2 changeset.

## [0.1.0]

Initial public CLI + skill release.
```

- [ ] **Step 7.2: 提交**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): create CHANGELOG.md; record PR 1 (canonical + base64 flip)

First CHANGELOG entry for the project. Tracks v0.3 in-progress changes
PR-by-PR. Subsequent v0.3 PRs append to the [Unreleased] section; PR 8
will rename to a versioned heading and bump pyproject."
```

---

## Task 8: 最终验证

**Files:** none (verification only)

- [ ] **Step 8.1: 全套测试**

```bash
.venv/bin/pytest -q
```
Expected: 全过。新增测试数:38(canonical) + 0(test_pr1b_mobile 净增 0,2 改 2),总数应为 v0.2 基线 + 38。

- [ ] **Step 8.2: Lint**

```bash
.venv/bin/ruff check src tests bench
```
Expected: `All checks passed!`

- [ ] **Step 8.3: Smoke test — canonical.py 可被 router 导入(确保模块级语法 / import 健康)**

```bash
.venv/bin/python -c "
from lightcrawl.canonical import canonicalize_url, url_hash
print(canonicalize_url('HTTPS://Example.COM/Path?utm_source=x&a=1#frag'))
print(url_hash('https://x.com/p', profile=None))
print(url_hash('https://x.com/p', profile='twitter'))
"
```
Expected:
```
https://example.com/Path?a=1
<40-hex>
<40-hex different from previous line>
```

- [ ] **Step 8.4: Smoke test — fetch 子命令默认行为变了**

```bash
.venv/bin/lightcrawl fetch https://example.com/ 2>&1 | head -c 200
```
Expected: 单 JSON 行开头 `{"ok": true, ...}`。**注意**:此步骤需要网络;如在离线环境,跳过本步骤但在 PR 描述中标注。

- [ ] **Step 8.5: Commit 链核对**

```bash
git log --oneline main..HEAD
```
Expected 顺序(顶到底,新到旧):
```
<sha> docs(changelog): create CHANGELOG.md...
<sha> feat!: flip remove_base64_images default to True...
<sha> test(canonical): IPv6 literals, idempotency...
<sha> feat(canonical): url_hash with profile dimension...
<sha> feat(canonical): query handling — sort, drop tracking...
<sha> feat(canonical): scaffold URL canonicalization...
```

6 个 commits。每个独立可还原、独立通过测试。

- [ ] **Step 8.6: 准备 PR 描述**

模板:

```markdown
## v0.3 PR 1 — canonical.py + remove_base64_images default flip

First PR in the v0.3 series (issue #22). Lays the URL canonicalization
foundation that cache (PR 2), crawl (PR 6), map (PR 4), and batch-fetch
(PR 7) all depend on. Also lands the only intentionally-breaking default
change of v0.3 — `remove_base64_images: False -> True`.

### Changes
- New module `src/lightcrawl/canonical.py` (~70 LOC) — pure functions
  `canonicalize_url` and `url_hash(profile=...)`. The profile dimension
  is a security boundary; see v0.3-design.md §5.2.
- 38 table-driven offline tests in `tests/test_canonical.py`.
- `FetchRequest.remove_base64_images` and `html_to_markdown(remove_base64_images=...)`
  default flipped to True.
- 2 tests in `test_pr1b_mobile.py` rewritten to match new default
  (explicit-flag coverage for old behavior remains).
- `CHANGELOG.md` created with [Unreleased] section.

### Testing
- `pytest -q`: 308 passing (270 v0.2 baseline + 38 canonical).
- `ruff check src tests bench`: clean.

### Risks
- The base64 default flip is breaking. v0.2 README pre-announced it.
  Callers needing v0.2 behavior pass `remove_base64_images=False`
  explicitly.

### What this PR does NOT do
- No `Cache` implementation yet (PR 2).
- No `cache_only` / `max_age_ms` fields on FetchRequest (PR 2).
- No CLI flag changes (`--max-age` etc. come in PR 2).
```

PR 1 完成。

---

## Self-Review Checklist(plan author 在交付前自查 — 已完成)

**Spec coverage:**
- v0.3-design.md §5.1 `canonical.py` scope:Task 1-4 ✓;URL form usage table:Task 1 docstring ✓
- v0.3-design.md §5.2 `url_hash` with profile:Task 3 ✓
- v0.3-design.md §6 默认翻转 + html_to_markdown 联动:Task 6 ✓
- v0.3-design.md §12 PR 1 行"文档同步":Task 6 (router.py 注释) + Task 7 (CHANGELOG) ✓
- v0.3-design.md §9 测试矩阵 `test_canonical.py`:Task 1-4 共 38 测试 ✓
- v0.3-review.md A2(cache key 含 profile,安全不变量):Task 3 测试明确覆盖 ✓
- v0.3-review.md nit "test_pr1a_params 等已有 默认 remove_base64_images=True 后所有断言更新":Task 6 Step 6.7 + 6.8 兜底 ✓

**Placeholder scan:** 无 TODO / TBD / "implement later" / "similar to Task N" 等空洞表述。所有代码块都是完整可粘贴内容。

**Type consistency:** `canonicalize_url(url, *, ignore_query=False, drop_tracking=True)` 与 `url_hash(canonical_url, *, profile)` 签名在 Task 1 / Task 3 / docstring / tests 中一致;FetchRequest 字段名 `remove_base64_images` 在 router.py / content.py / 测试 / CHANGELOG 中拼写一致。

**Granularity:** 8 个 task,平均 4-6 步,每步 2-5 分钟。每个 task 独立 commit,可还原。

**Out-of-scope guardrails:** 本计划**不**触碰 cache.py / sitemap.py / jobs.py / crawl.py / CLI 新子命令 / psutil 依赖 —— 这些都属于后续 PR。Task 6 Step 6.8 明确若发现意外的测试失败,只做"最小修复" commit,不顺手重构。
