from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from curl_cffi import requests as ccr

from .errors import ErrorCode, FetchError

DEFAULT_TIMEOUT = 5.0
MAX_BYTES = 10 * 1024 * 1024  # 10MB


@dataclass
class HttpResult:
    final_url: str
    status_code: int
    text: str
    content_type: str
    elapsed_ms: int


def fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    impersonate: str = "chrome120",
    headers: dict[str, str] | None = None,
) -> HttpResult:
    """L1 fetch using curl_cffi with browser TLS fingerprint impersonation.

    `headers` are merged into the request after the impersonate profile sets
    its defaults — caller-supplied values win on key collision. Pass at your
    own risk: overriding `User-Agent` here desyncs UA from the TLS fingerprint
    (a known bot signal). For `mobile`-style switches, prefer changing the
    impersonate profile instead of the UA header (see 02.md PR 1b).
    """
    try:
        r = ccr.get(
            url,
            timeout=timeout,
            impersonate=impersonate,
            allow_redirects=True,
            max_recv_speed=0,
            headers=headers or None,
        )
    except ccr.errors.RequestsError as e:
        msg = str(e)
        if "timeout" in msg.lower() or "timed out" in msg.lower():
            raise FetchError(ErrorCode.TIMEOUT, msg) from e
        raise FetchError(ErrorCode.HTTP_ERROR, msg) from e

    raw = r.content or b""
    if len(raw) > MAX_BYTES:
        raise FetchError(
            ErrorCode.CONTENT_TOO_LARGE,
            f"response is {len(raw)} bytes; max is {MAX_BYTES}",
        )

    ctype = r.headers.get("content-type", "")
    elapsed = getattr(r, "elapsed", None)
    if isinstance(elapsed, timedelta):
        elapsed_ms = int(elapsed.total_seconds() * 1000)
    elif isinstance(elapsed, (int, float)):
        elapsed_ms = int(elapsed * 1000)
    else:
        elapsed_ms = 0

    return HttpResult(
        final_url=str(r.url),
        status_code=r.status_code,
        text=r.text,
        content_type=ctype,
        elapsed_ms=elapsed_ms,
    )
