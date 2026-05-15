# Contributing to Refetch

## Architecture

```
                Claude Code / Codex / Gemini / any agent
                      │
                      │  Bash tool → `refetch <subcmd>` → JSON on stdout
                      ▼
┌───────────────────────────────────────────────────┐
│           refetch CLI (one Python process per invocation) │
│                                                   │
│   ┌─────────────────┐    ┌────────────────────┐   │
│   │ Search Service  │    │ Fetch Router       │   │
│   │  · Brave        │───▶│  L1 curl_cffi      │   │
│   │  · Serper       │    │  L2 Playwright +   │   │
│   │  · Tavily       │    │     stealth        │   │
│   │  · search()     │    │  L3 + storage      │   │
│   │  · search_      │    │     state (auth)   │   │
│   │     and_read()  │    │                    │   │
│   └─────────────────┘    └────────────────────┘   │
│           │                       │               │
│           └────────┬──────────────┘               │
│                    ▼                              │
│   ┌─────────────────────────────────────────┐     │
│   │  Shared layer                           │     │
│   │  · BrowserPool (single Chromium,        │     │
│   │      multi-context)                     │     │
│   │  · Auth profiles  (eTLD+1 bound, 0600)  │     │
│   │  · SSRF guard, URL safety               │     │
│   │  · Content pipeline                     │     │
│   │  · Errors & honesty contract            │     │
│   └─────────────────────────────────────────┘     │
└───────────────────────────────────────────────────┘
                      │
                      ▼
                ~/.refetch/
                ├── dumps/
                ├── profiles/
                └── logs/
```

Every public CLI subcommand routes through `cli._safe_run()`, which converts a `FetchError` or any uncaught exception into the same `{"ok": false, "error_code": "...", "error_detail": "..."}` envelope. Skills parse one JSON object per invocation; exit code mirrors `ok`.

**Fetch escalation policy** (`router.py`): every request goes L1 → L2 → L3 only as far as needed. The router decides escalation via two signals:

1. `_should_escalate_to_browser(status, html)` — escalates on 403/429/503, on Cloudflare challenge detection (a 2-level keyword system: `_CF_CHALLENGE_STRONG` and `_CF_CHALLENGE_WEAK`), and on `visible_text_ratio(html) < 0.01` for HTML > 2000 bytes (catches SPA shells).
2. Login-wall detection in `content.py` — escalates to authed strategy if the page text matches "sign in to continue" / etc.

**Single Browser, multi-context** (`fetch_browser.py`): one Chromium instance is reused for the whole process; each fetch gets a fresh `BrowserContext`. Authed fetches load a `storage_state` JSON from `~/.refetch/profiles/<name>.json`.

**Profile binding** (`auth.py` + `url_safety.py`): each profile is bound to the eTLD+1 of the login URL (computed via `tldextract`). A `twitter` profile bound to `x.com` cannot fetch `attacker.com/x.com/...` — `domain_matches()` enforces this in the router before any fetch.

**SSRF guard** (`url_safety.py`): every `validate_url()` call resolves the host. Loopback / private / link-local IPs are blocked unless `allow_private=True` or in `extra_allowlist`.

**Content pipeline** (`content.py`):
- `_clean_dom(doc)` strips `<script>/<style>/<iframe>/<svg>/<form>/<img>/<noscript>/...` plus elements with `aria-hidden=true` (case-insensitive) and `style="display:none"` (case-insensitive, whitespace-tolerant). Mutating during iteration is forbidden; collect into a `to_remove` list and remove in a second pass.
- `_select_target(doc, selector)` auto-scopes to a single `<main>` or `<article>` when present.
- `_dom_headings(target)` extracts `<h1>`–`<h6>` directly from DOM.
- `_locate_headings_in_markdown` matches DOM heading text to ATX heading lines using `_strip_md_formatting()`.
- `detect_spa_shell(html)` detects empty `<div id="root">` / `<div id="__next">` regardless of page length.
- Overflow handling: anything over `max_inline_tokens` is dumped to `~/.refetch/dumps/<sha1>.md`; the response carries `dump_path` plus the heading list with line numbers.

**Search service** (`search/service.py`): `search_and_read` runs `search` then fans out `Router.fetch` calls via `asyncio.gather(..., return_exceptions=True)` with each fetch wrapped in a `try/except` that returns a failure dict — one crash cannot lose the other in-flight results.

## Project layout

```
src/refetch/
├── cli.py               # argparse entry; one async subcommand per public op + _safe_run envelope
├── router.py            # Strategy router (L1 → L2 → L3)
├── fetch_http.py        # L1: curl_cffi
├── fetch_browser.py     # L2: Playwright + stealth, single browser / multi context
├── auth.py              # L3: profile manager, interactive_login
├── content.py           # deep DOM cleaning + markdownify + DOM-based headings + dump-on-overflow
├── url_safety.py        # SSRF guard, eTLD+1
├── paths.py             # ~/.refetch/
├── errors.py            # ErrorCode enum
└── search/
    ├── service.py       # search(), search_and_read()
    ├── types.py         # SearchResult, FetchHint
    └── backends/
        ├── base.py
        ├── brave.py
        ├── serper.py
        └── tavily.py
skills/refetch/SKILL.md
tests/                   # fully offline unit tests
bench/                   # tiktoken-based token comparison harness
```

## Benchmarks

Run a 10-URL benchmark comparing the naive built-in fetcher (`httpx` + markdownify whole page) against Refetch:

```bash
.venv/bin/python -m bench.runner --out bench/results/full.json
.venv/bin/python -m bench.report bench/results/full.json > bench/results/full.md
```

Latest results (counted with tiktoken `cl100k_base`):

| Category | Baseline tokens | Refetch auto | Refetch + selector | Saving (auto) | Saving (selector) |
|---|---:|---:|---:|---:|---:|
| Wikipedia (long article) | 67.1k | 9.6k | 8.0k | ↓85.7% | **↓88.1%** |
| Static doc (Python docs) | 22.7k | 4.8k | 4.5k | ↓78.8% | ↓80.1% |
| GitHub repo page | 4.3k | 2.5k | 0.3k | ↓41.4% | **↓94.0%** |
| Cloudflare SPA (`alltrails`) | 9.3k | 2.2k | — | ↓76.5% | — |
| SPA (`react.dev`) | 5.8k | 3.7k | 3.5k | ↓35.6% | ↓39.7% |
| News (HN, CNN Lite) | 4.0k | 4.0k | 3.8k | ↓0.3% | ↓4.7%¹ |

¹ Pages that are mostly content with little boilerplate get little extraction benefit.

`Refetch auto` is `refetch fetch <url>` with no hint — what the agent gets on the first call. `Refetch + selector` adds a `--selector` from the response's `suggested_selectors` field.

Success rate: **10/10 baseline, 10/10 Refetch auto, 7/7 Refetch + selector**. Full per-URL table in [`bench/results/full_v2.md`](bench/results/full_v2.md).

## Development

```bash
.venv/bin/pytest -q                    # all tests (~115, fully offline)
.venv/bin/pytest tests/test_search.py  # subset
.venv/bin/ruff check src tests bench   # lint
```

### Conventions

- **Errors are values, not exceptions, at the public boundary.** `Router.fetch()` and `SearchService.*` always return a dict with `ok: bool` + `error_code` (from `errors.py::ErrorCode`). Internal code raises `FetchError(code, detail)`; the router/service catches and converts.
- **L1 timeout has a known thread leak** (Bug 6 in `bug.md`, marked wontfix): `asyncio.wait_for(asyncio.to_thread(curl_cffi.fetch, ...))` cannot cancel curl_cffi's blocking I/O. The auto-escalation to L2 prevents repeated leaks on the same URL.
- **DOM mutation requires a two-pass collect-then-remove.** `lxml`'s `doc.iter()` invalidates if you remove elements mid-iteration. See `_clean_dom` for the canonical pattern.
- **No fabricated content; surface real failures.** The skill enforces an honesty contract: when a fetch fails, return the structured `error_code` rather than papering over with training data.
- **Tests must stay offline.** Network-touching code lives in `bench/` (opt-in, not run by `pytest`).
- **`readability-lxml` and `trafilatura` are bench-only.** They are listed under `[bench]` extras; the production pipeline does NOT depend on them.

## How to contribute

Contributions welcome — especially:

- New search backends (one file in `src/refetch/search/backends/`, follow `brave.py` as a template, ~80 lines)
- Benchmark URLs that exercise interesting failure modes
- Bug reports with a reproducer URL

Please run `pytest` before opening a PR. The project favours small surface area; new tools or parameters need a real motivating use case.
