from __future__ import annotations

import io
import re
from dataclasses import dataclass

from curl_cffi import requests as ccr

from .errors import ErrorCode, FetchError

DEFAULT_TIMEOUT = 10.0  # PDFs can be large
MAX_BYTES = 50 * 1024 * 1024  # 50MB limit for PDFs
DEFAULT_IMPERSONATE = "chrome120"  # reuse fetch_http's profile

# Page-number noise lines: "1", "1 / 239", "Page 12", "- 5 -". The fallback
# title extractor walks past these to find the real cover-page heading.
_PAGE_NUMBER_LINE = re.compile(
    r"^\s*(page\s+)?[-—\s]*\d+(\s*[/-]\s*\d+)?[-—\s]*$",
    re.IGNORECASE,
)


def _extract_title(reader) -> str:
    """Best-effort title for a PDF, in order:
      1. `reader.metadata.title` if non-blank.
      2. First non-page-number, non-trivially-short line of page 1.
      3. Empty string — never fabricate one.

    pypdf accessor errors (encrypted metadata, malformed XMP, missing
    pages) are swallowed: a missing title is a UX downgrade, not fatal.
    """
    try:
        meta = getattr(reader, "metadata", None)
        if meta is not None:
            t = getattr(meta, "title", None)
            if isinstance(t, str) and t.strip():
                return t.strip()
    except Exception:
        pass

    try:
        pages = getattr(reader, "pages", []) or []
        if not pages:
            return ""
        first = (pages[0].extract_text() or "").strip()
    except Exception:
        return ""

    for line in first.splitlines():
        s = line.strip()
        if not s:
            continue
        if _PAGE_NUMBER_LINE.match(s):
            continue
        # Length 4 picks up real titles ("Doc1") while still rejecting
        # short labels. Counted by chars — CJK titles (2+ chars) clear it.
        if len(s) < 4:
            continue
        return s
    return ""


@dataclass
class PdfResult:
    markdown: str
    num_pages: int
    content_length: int
    final_url: str
    elapsed_ms: int
    title: str = ""


def fetch_pdf(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    impersonate: str = DEFAULT_IMPERSONATE,
) -> PdfResult:
    """Download a PDF and extract text from every page via pypdf.

    L1-only (curl_cffi download + pypdf extraction). No L2/Playwright fallback
    — Playwright PDF download requires totally different event wiring (see #20).
    """
    import time as _time
    started = _time.monotonic()

    try:
        r = ccr.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers=headers or None,
            impersonate=impersonate,
        )
    except ccr.errors.RequestsError as e:
        msg = str(e)
        if "timeout" in msg.lower() or "timed out" in msg.lower():
            raise FetchError(ErrorCode.TIMEOUT, msg) from e
        raise FetchError(ErrorCode.PDF_FETCH_BLOCKED, msg) from e

    raw = r.content or b""
    if len(raw) > MAX_BYTES:
        raise FetchError(
            ErrorCode.CONTENT_TOO_LARGE,
            f"PDF is {len(raw)} bytes; max is {MAX_BYTES}",
        )

    ctype = (r.headers.get("content-type", "") or "").lower()
    is_pdf = ctype.startswith("application/pdf") or raw[:4] == b"%PDF"

    if not is_pdf:
        raise FetchError(
            ErrorCode.UNSUPPORTED_CONTENT_TYPE,
            f"expected application/pdf or %PDF magic bytes; got content-type={ctype!r}",
        )

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception as e:
        raise FetchError(
            ErrorCode.UNSUPPORTED_CONTENT_TYPE,
            f"pypdf could not open the document: {e}",
        ) from e

    parts: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(text)

    if not parts:
        raise FetchError(
            ErrorCode.PDF_NO_TEXT_LAYER,
            f"PDF has {len(reader.pages)} page(s) but none contain extractable text "
            "(scanned PDF or image-only); OCR is not supported in v0.2",
        )

    md = "\n\n---\n\n".join(parts)
    elapsed_ms = int((_time.monotonic() - started) * 1000)

    return PdfResult(
        markdown=md,
        num_pages=len(reader.pages),
        content_length=len(raw),
        final_url=str(r.url),
        elapsed_ms=elapsed_ms,
        title=_extract_title(reader),
    )
