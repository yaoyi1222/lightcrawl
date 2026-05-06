# WebFetch token-consumption benchmark

_Token counter: `tiktoken-cl100k_base`_

Two columns matter: **tokens returned to the model** (what eats your context window) and **success**. `plus_auto` is `fetch_url(url)` with no extra hints; `plus_selector` adds a CSS selector chosen from the router's `suggested_selectors` hint (i.e. what a model would naturally do on the second call).

## Per-URL results

| URL | Category | Baseline tok | Plus auto tok | Plus selector tok | Saving (auto) | Saving (selector) | Baseline ok | Plus auto ok | Plus selector ok | Plus strategy |
|---|---|---:|---:|---:|---:|---:|:-:|:-:|:-:|---|
| https://en.wikipedia.org/wiki/Claude_Shannon | wiki | 62.8k | 10.0k | 8.1k | ↓84.0% | ↓87.1% | ✅ | ✅ | ✅ | http |
| https://en.wikipedia.org/wiki/Transformer_(deep_lear… | wiki | 71.5k | 9.1k | 7.8k | ↓87.2% | ↓89.1% | ✅ | ✅ | ✅ | http |
| https://docs.python.org/3/library/asyncio.html | static_doc | 1.7k | 1.6k | 992 | ↓4.3% | ↓40.1% | ✅ | ✅ | ✅ | http |
| https://docs.python.org/3/library/typing.html | static_doc | 43.7k | 8.0k | 8.0k | ↓81.6% | ↓81.6% | ✅ | ✅ | ✅ | http |
| https://raw.githubusercontent.com/python/cpython/mai… | github | 1.8k | 1.8k | — | ↓0.0% | — | ✅ | ✅ | — | http |
| https://github.com/anthropics/anthropic-sdk-python | github | 4.3k | 2.5k | 262 | ↓41.4% | ↓94.0% | ✅ | ✅ | ✅ | http |
| https://news.ycombinator.com/ | news | 3.8k | 3.8k | 3.8k | ↓0.2% | ↓0.2% | ✅ | ✅ | ✅ | http |
| https://lite.cnn.com/ | news | 4.2k | 4.2k | — | ↓0.4% | — | ✅ | ✅ | — | http |
| https://react.dev/learn | spa | 5.8k | 3.7k | 3.5k | ↓35.6% | ↓39.7% | ✅ | ✅ | ✅ | http |
| https://www.alltrails.com/ | cloudflare | 9.3k | 2.2k | — | ↓76.5% | — | ✅ | ✅ | — | http |

## Category roll-up (mean tokens, successful fetches only)

| Category | n | Baseline | Plus auto | Plus selector | Saving auto | Saving selector |
|---|---:|---:|---:|---:|---:|---:|
| wiki | 2 | 67.1k | 9.6k | 8.0k | ↓85.7% | ↓88.1% |
| static_doc | 2 | 22.7k | 4.8k | 4.5k | ↓78.8% | ↓80.1% |
| github | 2 | 3.1k | 2.2k | 262 | ↓29.2% | ↓91.5% |
| news | 2 | 4.0k | 4.0k | 3.8k | ↓0.3% | ↓4.7% |
| spa | 1 | 5.8k | 3.7k | 3.5k | ↓35.6% | ↓39.7% |
| cloudflare | 1 | 9.3k | 2.2k | — | ↓76.5% | — |

## Success rates

- **baseline**: 10/10  (100%)
- **plus_auto**: 10/10  (100%)
- **plus_selector**: 7/7  (100%)

## Notes

- `tokens_returned` is what the model actually sees in the response. When `truncated=true`, `plus` writes the full content to a dump file instead of returning it inline — that's deliberate and counts as a saving (the model can read the dump file selectively).
- Baseline failure on a URL counts as 0 tokens; the row still appears so you can see *why* it failed (the cell shows the HTTP error).
- Run multiple `--rounds` to smooth out network jitter; tokens are deterministic per response so only `elapsed_ms` benefits from averaging.
