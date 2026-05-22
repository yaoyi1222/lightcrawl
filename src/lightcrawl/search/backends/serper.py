from __future__ import annotations

from datetime import date, datetime, timezone

import httpx

from ..config import resolve_api_key
from ..types import SearchResult
from .base import BackendError

SERPER_ENDPOINT = "https://google.serper.dev/search"


def _parse_after(after_iso: str | None) -> date | None:
    if not after_iso:
        return None
    try:
        return datetime.fromisoformat(after_iso.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _tbs_for_range(
    after_iso: str | None, before_iso: str | None
) -> str | None:
    """Map (after, before) ISO dates to Google's `tbs` parameter.

    - both bounds → `cdr:1,cd_min:MM/DD/YYYY,cd_max:MM/DD/YYYY`
    - after only → nearest qdr:d|w|m|y bucket (no `before` means "ongoing")
    - before only → unsupported, ignored (matches Brave behaviour)
    """
    after = _parse_after(after_iso)
    before = _parse_after(before_iso)
    if after and before:
        return f"cdr:1,cd_min:{after.strftime('%m/%d/%Y')},cd_max:{before.strftime('%m/%d/%Y')}"
    if after:
        days = (datetime.now(timezone.utc).date() - after).days
        if days <= 1:
            return "qdr:d"
        if days <= 7:
            return "qdr:w"
        if days <= 31:
            return "qdr:m"
        if days <= 365:
            return "qdr:y"
        return None
    return None


def _parse_age_days(date_str: str | None) -> int | None:
    """Serper's `date` field is either "X days ago" / "X hours ago" or an
    English-formatted date like "Mar 5, 2025"."""
    if not date_str:
        return None
    s = date_str.lower().strip()
    parts = s.split()
    if len(parts) >= 2 and parts[0].isdigit():
        n = int(parts[0])
        unit = parts[1]
        if "minute" in unit or "hour" in unit:
            return 0
        if "day" in unit:
            return n
        if "week" in unit:
            return n * 7
        if "month" in unit:
            return n * 30
        if "year" in unit:
            return n * 365
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            then = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
            return max(0, (datetime.now(timezone.utc) - then).days)
        except ValueError:
            continue
    return None


class SerperBackend:
    name = "serper"
    cost_per_call_usd = 0.001  # ~$50 for 50k queries on the standard tier

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = resolve_api_key("SERPER_API_KEY", "serper", explicit=api_key)
        self._transport = transport

    def configured(self) -> bool:
        return bool(self.api_key)

    async def search(
        self,
        query: str,
        *,
        max_results: int,
        time_range: tuple[str | None, str | None] = (None, None),
        timeout: float = 10.0,
    ) -> list[SearchResult]:
        if not self.api_key:
            raise BackendError("NO_BACKEND_CONFIGURED", "SERPER_API_KEY is not set")

        body: dict[str, object] = {
            "q": query,
            "num": min(max_results, 20),
            "gl": "us",
            "hl": "en",
        }
        tbs = _tbs_for_range(*time_range)
        if tbs:
            body["tbs"] = tbs

        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        client_kwargs: dict[str, object] = {"timeout": timeout}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                r = await client.post(SERPER_ENDPOINT, json=body, headers=headers)
        except httpx.TimeoutException as e:
            raise BackendError("TIMEOUT", str(e)) from e
        except httpx.HTTPError as e:
            raise BackendError("HTTP_ERROR", f"{type(e).__name__}: {e}") from e

        if r.status_code == 429:
            raise BackendError("RATE_LIMITED", "serper: 429")
        if r.status_code in (401, 403):
            raise BackendError("NO_BACKEND_CONFIGURED", f"serper auth failed: {r.status_code}")
        if r.status_code >= 400:
            raise BackendError("HTTP_ERROR", f"serper: {r.status_code} {r.text[:200]}")

        try:
            data = r.json()
        except Exception as e:
            raise BackendError("HTTP_ERROR", f"non-JSON response: {e}") from e

        organic = data.get("organic") or []
        out: list[SearchResult] = []
        for i, item in enumerate(organic[:max_results], start=1):
            url = item.get("link") or ""
            if not url:
                continue
            out.append(
                SearchResult(
                    rank=i,
                    title=item.get("title") or "",
                    url=url,
                    snippet=item.get("snippet") or "",
                    page_age_days=_parse_age_days(item.get("date")),
                )
            )
        return out
