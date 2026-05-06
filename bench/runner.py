"""Run baseline vs refetch over a URL set and emit JSON results.

Usage:
  .venv/bin/python -m bench.runner [--urls bench/urls.toml] [--out bench/results/run.json]
                                   [--with-selector] [--rounds 1]

By default we run TWO plus modes per URL:
  - plus_auto       : fetch_url(url)              (no selector)
  - plus_selector   : fetch_url(url, selector=…)  (the hint from urls.toml)
This shows the savings from selector usage on top of router improvements.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Make src/ importable when running from repo root without install
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refetch.router import FetchRequest, Router  # noqa: E402

from . import baseline, tokens  # noqa: E402


@dataclass
class Outcome:
    mode: str
    ok: bool
    status_code: int | None
    strategy_used: str | None
    elapsed_ms: int
    tokens_returned: int        # tokens delivered to the model in response.content
    tokens_full: int            # tokens of the full content (incl. dump if any)
    truncated: bool
    dump_path: str | None
    error_code: str | None
    error_detail: str | None


@dataclass
class URLRow:
    url: str
    category: str
    note: str
    selector: str | None
    outcomes: list[Outcome] = field(default_factory=list)


def _load_urls(path: Path) -> list[dict]:
    with path.open("rb") as f:
        return tomllib.load(f)["urls"]


def _baseline_outcome(url: str) -> Outcome:
    r = baseline.fetch(url)
    n = tokens.count(r.markdown)
    return Outcome(
        mode="baseline",
        ok=r.ok,
        status_code=r.status_code,
        strategy_used="httpx-raw",
        elapsed_ms=r.elapsed_ms,
        tokens_returned=n,
        tokens_full=n,
        truncated=False,
        dump_path=None,
        error_code=None if r.ok else "BASELINE_FAIL",
        error_detail=r.error,
    )


async def _plus_outcome(router: Router, url: str, *, selector: str | None, mode: str) -> Outcome:
    started = time.monotonic()
    req = FetchRequest(url=url, selector=selector)
    out = await router.fetch(req)
    elapsed = int((time.monotonic() - started) * 1000)

    if not out["ok"]:
        return Outcome(
            mode=mode,
            ok=False,
            status_code=None,
            strategy_used=None,
            elapsed_ms=elapsed,
            tokens_returned=0,
            tokens_full=0,
            truncated=False,
            dump_path=None,
            error_code=out.get("error_code"),
            error_detail=out.get("error_detail"),
        )

    inline = out["content"] or ""
    dump_path = out.get("dump_path")
    if dump_path and Path(dump_path).exists():
        full_text = Path(dump_path).read_text()
    else:
        full_text = inline
    return Outcome(
        mode=mode,
        ok=True,
        status_code=out["metadata"]["status_code"],
        strategy_used=out["strategy_used"],
        elapsed_ms=elapsed,
        tokens_returned=tokens.count(inline),
        tokens_full=tokens.count(full_text),
        truncated=bool(out.get("content_truncated")),
        dump_path=dump_path,
        error_code=None,
        error_detail=None,
    )


async def run(urls: list[dict], with_selector: bool, rounds: int) -> list[URLRow]:
    router = Router()
    rows: list[URLRow] = []
    try:
        for entry in urls:
            row = URLRow(
                url=entry["url"],
                category=entry.get("category", "?"),
                note=entry.get("note", ""),
                selector=entry.get("selector"),
            )
            for _ in range(rounds):
                row.outcomes.append(_baseline_outcome(row.url))
                row.outcomes.append(
                    await _plus_outcome(router, row.url, selector=None, mode="plus_auto")
                )
                if with_selector and row.selector:
                    row.outcomes.append(
                        await _plus_outcome(
                            router, row.url, selector=row.selector, mode="plus_selector"
                        )
                    )
            rows.append(row)
            print(f"  done: {row.url}", file=sys.stderr)
    finally:
        await router.close()
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--urls", default="bench/urls.toml", type=Path)
    p.add_argument("--out", default="bench/results/run.json", type=Path)
    p.add_argument("--with-selector", action="store_true", default=True)
    p.add_argument("--no-selector", dest="with_selector", action="store_false")
    p.add_argument("--rounds", type=int, default=1)
    args = p.parse_args(argv)

    urls = _load_urls(args.urls)
    print(f"loaded {len(urls)} URLs from {args.urls}", file=sys.stderr)
    print(f"token strategy: {tokens.strategy()}", file=sys.stderr)

    rows = asyncio.run(run(urls, args.with_selector, args.rounds))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {
            "token_strategy": tokens.strategy(),
            "rows": [
                {**{k: v for k, v in asdict(r).items() if k != "outcomes"},
                 "outcomes": [asdict(o) for o in r.outcomes]}
                for r in rows
            ],
        },
        indent=2,
    ))
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
