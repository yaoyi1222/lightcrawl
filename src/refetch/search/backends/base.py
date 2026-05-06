from __future__ import annotations

from typing import Protocol

from ..types import SearchResult


class BackendError(Exception):
    """Raised by a Backend when the search fails. The caller maps this to
    the structured `error_code` in the MCP response."""

    def __init__(self, code: str, detail: str):
        self.code = code  # e.g. RATE_LIMITED, EMPTY_RESULTS, HTTP_ERROR, TIMEOUT
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class Backend(Protocol):
    name: str
    cost_per_call_usd: float

    async def search(
        self,
        query: str,
        *,
        max_results: int,
        time_range: tuple[str | None, str | None] = (None, None),
        timeout: float = 10.0,
    ) -> list[SearchResult]:
        ...
