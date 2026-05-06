# Token-consumption benchmark

Compares the **built-in WebFetch** approach against **refetch** on the
same set of URLs, measuring how many tokens land in the model's context.

## What "baseline" simulates

We can't call Anthropic's actual WebFetch tool from a script (it lives inside
the agent harness). So `baseline.py` reproduces its publicly observable
behavior:

1. Plain HTTP GET with a generic UA — no TLS fingerprint impersonation
2. No JS execution
3. The **entire** HTML body is converted to markdown and returned

That's intentionally naive — it's what we want to measure against. If the real
WebFetch later does readability or chunking, this benchmark will overstate the
savings; rerun against an updated baseline when that happens.

## What "plus" measures

Two modes per URL:

- `plus_auto`     — `fetch_url(url)` with no extra hints (router + readability
                    + dump-on-overflow do all the work)
- `plus_selector` — `fetch_url(url, selector=<hint>)` where the hint is what a
                    model would naturally pass after seeing
                    `metadata.suggested_selectors` from the first call

Both `tokens_returned` (what the model sees) and `tokens_full` (what landed
on disk including dumps) are recorded — the gap between them is the
context-window saving from auto-dump.

## Token counter

Uses `tiktoken` (`cl100k_base`) if installed; otherwise `chars/4`. Anthropic's
tokenizer differs slightly from cl100k_base, but the ratio between baseline
and plus will be very close. Both runs use the same counter, so comparisons
are fair.

To get the most accurate numbers:

```bash
.venv/bin/pip install tiktoken
```

## Run

```bash
.venv/bin/playwright install chromium    # one-time, needed for SPA URLs
.venv/bin/python -m bench.runner --out bench/results/run.json
.venv/bin/python -m bench.report bench/results/run.json > bench/results/report.md
open bench/results/report.md
```

Faster smoke test on a subset:

```bash
.venv/bin/python -m bench.runner --urls bench/urls_smoke.toml \
                                  --out bench/results/smoke.json
```

## What to look for

| Metric | Why it matters |
|---|---|
| `tokens_returned` (baseline vs plus) | Direct context-window saving per fetch |
| `truncated` + `dump_path` on plus | Long pages no longer blow your context — full content sits on disk for selective reads |
| Success column | Plus should succeed where baseline 403s (Cloudflare, Wikipedia) and on SPAs (React/Vue) |
| `strategy_used` | Confirms the router didn't over-escalate to a browser when L1 would have worked |
| `elapsed_ms` | Sanity check — plus should not be dramatically slower on cheap URLs |

## Caveats

- Network jitter: use `--rounds N` to average elapsed_ms.
- Cloudflare / SPA outcomes drift over time; refresh `urls.toml` periodically.
- Login-required URLs aren't in the default set — add with a profile if you
  want to compare logged-in sessions (baseline can't even attempt those).
