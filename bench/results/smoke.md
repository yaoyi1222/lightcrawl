# WebFetch token-consumption benchmark

_Token counter: `tiktoken-cl100k_base`_

Two columns matter: **tokens returned to the model** (what eats your context window) and **success**. `plus_auto` is `fetch_url(url)` with no extra hints; `plus_selector` adds a CSS selector chosen from the router's `suggested_selectors` hint (i.e. what a model would naturally do on the second call).

## Per-URL results

| URL | Category | Baseline tok | Plus auto tok | Plus selector tok | Saving (auto) | Saving (selector) | Baseline ok | Plus auto ok | Plus selector ok | Plus strategy |
|---|---|---:|---:|---:|---:|---:|:-:|:-:|:-:|---|
| https://en.wikipedia.org/wiki/Claude_Shannon | wiki | 62.8k | 8.0k | 8.1k | ↓87.3% | ↓87.1% | ✅ | ✅ | ✅ | http |
| https://raw.githubusercontent.com/python/cpython/mai… | github | 1.8k | 1.8k | — | ↓0.0% | — | ✅ | ✅ | — | http |
| https://news.ycombinator.com/ | news | 3.8k | 3.8k | 3.8k | ↓0.1% | ↓0.1% | ✅ | ✅ | ✅ | http |

## Category roll-up (mean tokens, successful fetches only)

| Category | n | Baseline | Plus auto | Plus selector | Saving auto | Saving selector |
|---|---:|---:|---:|---:|---:|---:|
| wiki | 1 | 62.8k | 8.0k | 8.1k | ↓87.3% | ↓87.1% |
| github | 1 | 1.8k | 1.8k | — | ↓0.0% | — |
| news | 1 | 3.8k | 3.8k | 3.8k | ↓0.1% | ↓0.1% |

## Success rates

- **baseline**: 3/3  (100%)
- **plus_auto**: 3/3  (100%)
- **plus_selector**: 2/2  (100%)

## Notes

- `tokens_returned` is what the model actually sees in the response. When `truncated=true`, `plus` writes the full content to a dump file instead of returning it inline — that's deliberate and counts as a saving (the model can read the dump file selectively).
- Baseline failure on a URL counts as 0 tokens; the row still appears so you can see *why* it failed (the cell shows the HTTP error).
- Run multiple `--rounds` to smooth out network jitter; tokens are deterministic per response so only `elapsed_ms` benefits from averaging.
