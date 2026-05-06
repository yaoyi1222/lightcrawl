"""Baseline fetcher that mimics the built-in WebFetch tool.

Built-in WebFetch behavior (best public approximation):
- Plain HTTP GET with a generic UA, no TLS fingerprint impersonation.
- No JS execution.
- Converts the *entire* HTML body to markdown (no readability, no selector).
- Returns the full markdown blob to the model.

This is intentionally naive — it's what we are comparing against.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from markdownify import markdownify

DEFAULT_UA = (
    "Mozilla/5.0 (compatible; WebFetch/1.0; +https://anthropic.com)"
)
TIMEOUT = 30.0
MAX_BYTES = 10 * 1024 * 1024


@dataclass
class BaselineResult:
    ok: bool
    status_code: int
    final_url: str
    markdown: str
    error: str | None
    elapsed_ms: int


def fetch(url: str) -> BaselineResult:
    started = time.monotonic()
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=TIMEOUT,
            headers={"User-Agent": DEFAULT_UA, "Accept": "text/html,*/*"},
        ) as client:
            r = client.get(url)
        elapsed = int((time.monotonic() - started) * 1000)
        if len(r.content) > MAX_BYTES:
            return BaselineResult(
                ok=False,
                status_code=r.status_code,
                final_url=str(r.url),
                markdown="",
                error=f"response too large: {len(r.content)} bytes",
                elapsed_ms=elapsed,
            )
        if r.status_code >= 400:
            return BaselineResult(
                ok=False,
                status_code=r.status_code,
                final_url=str(r.url),
                markdown="",
                error=f"HTTP {r.status_code}",
                elapsed_ms=elapsed,
            )
        md = markdownify(r.text, heading_style="ATX")
        return BaselineResult(
            ok=True,
            status_code=r.status_code,
            final_url=str(r.url),
            markdown=md,
            error=None,
            elapsed_ms=elapsed,
        )
    except Exception as e:
        return BaselineResult(
            ok=False,
            status_code=0,
            final_url=url,
            markdown="",
            error=f"{type(e).__name__}: {e}",
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
