from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..config import resolve_api_key
from ..types import SearchResult
from .base import BackendError

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def _parse_age_days(age_str: str | None, page_age_iso: str | None) -> int | None:
    """Brave returns either an `age` like "2 days ago" or `page_age` ISO string."""
    if page_age_iso:
        try:
            then = datetime.fromisoformat(page_age_iso.replace("Z", "+00:00"))
            return max(0, (datetime.now(timezone.utc) - then).days)
        except Exception:
            pass
    if age_str:
        s = age_str.lower().strip()
        try:
            n = int(s.split()[0])
        except (ValueError, IndexError):
            return None
        if "minute" in s or "hour" in s:
            return 0
        if "day" in s:
            return n
        if "week" in s:
            return n * 7
        if "month" in s:
            return n * 30
        if "year" in s:
            return n * 365
    return None


def _strip_tags(text: str | None) -> str:
    if not text:
        return ""
    # Brave wraps query terms in <strong>; we don't need that markup.
    return text.replace("<strong>", "").replace("</strong>", "")


class BraveBackend:
    name = "brave"
    cost_per_call_usd = 0.005  # rough per-query estimate at the paid tier

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = resolve_api_key("BRAVE_SEARCH_API_KEY", "brave", explicit=api_key)

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
            raise BackendError("NO_BACKEND_CONFIGURED", "BRAVE_SEARCH_API_KEY is not set")

        params: dict[str, str] = {
            "q": query,
            "count": str(min(max_results, 20)),
            "result_filter": "web",
        }
        after, before = time_range
        if after or before:
            # Brave supports `freshness=pd|pw|pm|py` or `freshness=<after>to<before>`.
            if after and before:
                params["freshness"] = f"{after}to{before}"
            elif after:
                params["freshness"] = f"{after}to{datetime.now(timezone.utc).date().isoformat()}"

        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(BRAVE_ENDPOINT, params=params, headers=headers)
        except httpx.TimeoutException as e:
            raise BackendError("TIMEOUT", str(e)) from e
        except httpx.HTTPError as e:
            raise BackendError("HTTP_ERROR", f"{type(e).__name__}: {e}") from e

        if r.status_code == 429:
            raise BackendError("RATE_LIMITED", "brave: 429")
        if r.status_code == 401 or r.status_code == 403:
            raise BackendError("NO_BACKEND_CONFIGURED", f"brave auth failed: {r.status_code}")
        if r.status_code >= 400:
            raise BackendError("HTTP_ERROR", f"brave: {r.status_code} {r.text[:200]}")

        try:
            data = r.json()
        except Exception as e:
            raise BackendError("HTTP_ERROR", f"non-JSON response: {e}") from e

        web_items = (data.get("web") or {}).get("results") or []
        out: list[SearchResult] = []
        for i, item in enumerate(web_items[:max_results], start=1):
            url = item.get("url") or ""
            if not url:
                continue
            out.append(
                SearchResult(
                    rank=i,
                    title=_strip_tags(item.get("title")),
                    url=url,
                    snippet=_strip_tags(item.get("description")),
                    page_age_days=_parse_age_days(item.get("age"), item.get("page_age")),
                )
            )
        return out
