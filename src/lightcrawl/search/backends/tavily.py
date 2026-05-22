from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..config import resolve_api_key
from ..types import SearchResult
from .base import BackendError

TAVILY_ENDPOINT = "https://api.tavily.com/search"


def _days_for_range(after_iso: str | None) -> int | None:
    """Tavily only supports a `days: int` window (last N days). If only an
    `after` date is given, compute days = (today - after); ignore `before`.
    """
    if not after_iso:
        return None
    try:
        then = datetime.fromisoformat(after_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    days = (datetime.now(timezone.utc) - then).days
    if days < 1:
        return 1
    if days > 365:
        return 365
    return days


def _parse_published_age_days(published_iso: str | None) -> int | None:
    if not published_iso:
        return None
    try:
        then = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - then).days)


class TavilyBackend:
    name = "tavily"
    cost_per_call_usd = 0.008  # basic depth, paid tier reference
    env_var = "TAVILY_API_KEY"
    signup_url = "https://app.tavily.com/home"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = resolve_api_key(self.env_var, "tavily", explicit=api_key)
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
            raise BackendError("NO_BACKEND_CONFIGURED", "TAVILY_API_KEY is not set")

        # Snippet-only path: do NOT fetch raw_content or synthesise an answer
        # — those bypass this project's Router/profile/Playwright layer.
        body: dict[str, object] = {
            "query": query,
            "search_depth": "basic",
            "max_results": min(max_results, 20),
            "include_raw_content": False,
            "include_answer": False,
        }
        days = _days_for_range(time_range[0])
        if days is not None:
            body["days"] = days

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        client_kwargs: dict[str, object] = {"timeout": timeout}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                r = await client.post(TAVILY_ENDPOINT, json=body, headers=headers)
        except httpx.TimeoutException as e:
            raise BackendError("TIMEOUT", str(e)) from e
        except httpx.HTTPError as e:
            raise BackendError("HTTP_ERROR", f"{type(e).__name__}: {e}") from e

        if r.status_code == 429:
            raise BackendError("RATE_LIMITED", "tavily: 429")
        if r.status_code in (401, 403):
            raise BackendError("NO_BACKEND_CONFIGURED", f"tavily auth failed: {r.status_code}")
        if r.status_code >= 400:
            raise BackendError("HTTP_ERROR", f"tavily: {r.status_code} {r.text[:200]}")

        try:
            data = r.json()
        except Exception as e:
            raise BackendError("HTTP_ERROR", f"non-JSON response: {e}") from e

        items = data.get("results") or []
        out: list[SearchResult] = []
        for i, item in enumerate(items[:max_results], start=1):
            url = item.get("url") or ""
            if not url:
                continue
            out.append(
                SearchResult(
                    rank=i,
                    title=item.get("title") or "",
                    url=url,
                    snippet=item.get("content") or "",
                    page_age_days=_parse_published_age_days(item.get("published_date")),
                )
            )
        return out
