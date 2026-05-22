from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass

from .. import auth as auth_mod
from ..errors import ErrorCode, FetchError
from ..paths import DUMPS
from ..router import FetchRequest, Router
from ..url_safety import etld1
from .backends.base import Backend, BackendError
from .backends.brave import BraveBackend
from .backends.serper import SerperBackend
from .backends.tavily import TavilyBackend
from .types import (
    DEPTH_DEFAULTS,
    AnnotatedResult,
    Depth,
    FetchHint,
    SearchResult,
)

SNIPPET_TARGET = 200       # below this we try to enrich
SNIPPET_GOAL = 300         # target length to make most fetches unnecessary

# Minimum per-fetch budget inside search_and_read. L2 browser fetches need
# ~10-15s for launch + load + JS; 5s reliably times them out. Setting the
# floor at 15s matches `Router._fetch_browser_only`'s own L2 cap.
MIN_FETCH_TIMEOUT_MS = 15_000

# Codes that are worth retrying on a different backend. PROVIDER_ERROR is
# included because Brave/Serper sometimes surface 5xx with that code.
_RETRYABLE_BACKEND_CODES = frozenset({
    "RATE_LIMITED", "TIMEOUT", "HTTP_ERROR", "PROVIDER_ERROR",
})


@dataclass
class SearchRequest:
    query: str
    depth: Depth = "normal"
    backend: str | None = None
    max_results: int | None = None
    time_range: tuple[str | None, str | None] = (None, None)
    profile: str | None = None
    timeout_ms: int = 15_000


@dataclass
class SearchAndReadRequest:
    query: str
    depth: Depth = "normal"
    read_top_n: int = 3
    read_max_inline_tokens: int = 4000
    profile: str | None = None
    timeout_ms: int = 60_000


class SearchService:
    """Holds backends + a router (shared with fetch). One per process."""

    def __init__(self, *, router: Router | None = None, backends: list[Backend] | None = None):
        self._router = router or Router()
        self._owns_router = router is None
        if backends is None:
            backends = [BraveBackend(), SerperBackend(), TavilyBackend()]
        self._backends: dict[str, Backend] = {b.name: b for b in backends}

    @property
    def router(self) -> Router:
        return self._router

    async def close(self) -> None:
        if self._owns_router:
            await self._router.close()

    def list_backends(self) -> list[dict]:
        out = []
        for b in self._backends.values():
            configured = getattr(b, "configured", lambda: True)()
            entry: dict = {
                "name": b.name,
                "configured": configured,
                "cost_per_call_usd": b.cost_per_call_usd,
            }
            # Surface the config_guide unconditionally so a user with one
            # backend already configured still sees how to enable the
            # others (e.g. for failover). The fields mirror exactly what
            # `resolve_api_key` looks at — env var, config-file path, and
            # the signup URL — so the answer here matches reality. (#36)
            env_var = getattr(b, "env_var", None)
            signup_url = getattr(b, "signup_url", None)
            if env_var and signup_url:
                entry["config_guide"] = {
                    "env_var": env_var,
                    "signup_url": signup_url,
                    "config_file": "~/.lightcrawl/config.json",
                }
            out.append(entry)
        return out

    def _pick_backend(self, name: str | None) -> tuple[str, Backend]:
        if name:
            if name not in self._backends:
                raise BackendError(
                    "NO_BACKEND_CONFIGURED",
                    f"backend {name!r} not registered; available: "
                    f"{sorted(self._backends.keys())}",
                )
            return name, self._backends[name]
        # Pick the first configured backend.
        for n, b in self._backends.items():
            if getattr(b, "configured", lambda: True)():
                return n, b
        raise BackendError("NO_BACKEND_CONFIGURED", "no search backend has credentials configured")

    def _ordered_backends(self, primary: str) -> list[tuple[str, Backend]]:
        """Return [(name, backend), ...] in failover order: primary first,
        then any other configured backends in registration order. Unconfigured
        backends are skipped so we never spend a TIMEOUT failing against one."""
        out: list[tuple[str, Backend]] = []
        primary_backend = self._backends.get(primary)
        if primary_backend is not None:
            out.append((primary, primary_backend))
        for n, b in self._backends.items():
            if n == primary:
                continue
            if getattr(b, "configured", lambda: True)():
                out.append((n, b))
        return out

    def _annotate(
        self, results: list[SearchResult], profile: str | None = None
    ) -> list[AnnotatedResult]:
        # Cheap hints only. When the caller specified a profile, only annotate
        # results that match THAT profile's bound domain — otherwise an agent
        # passing profile="twitter" would see needs_login=true on linkedin.com
        # results too. With no profile, fall back to all active profiles.
        if profile:
            try:
                meta = auth_mod.get_profile(profile)
                active_domains = (
                    {meta.bound_domain} if meta.status == "active" else set()
                )
            except FetchError:
                active_domains = set()
        else:
            active_domains = {
                p.bound_domain for p in auth_mod.list_profiles() if p.status == "active"
            }
        annotated = []
        for r in results:
            target_etld1 = etld1(r.url)
            cache_status = "warm" if _has_dump(r.url) else "cold"
            needs_login = target_etld1 in active_domains  # we have a profile = likely needs login
            annotated.append(
                AnnotatedResult(
                    rank=r.rank,
                    title=r.title,
                    url=r.url,
                    snippet=r.snippet,
                    page_age_days=r.page_age_days,
                    fetch_hint=FetchHint(
                        needs_login=needs_login,
                        cache_status=cache_status,
                    ),
                )
            )
        return annotated

    def _enhance_snippets(self, results: list[AnnotatedResult]) -> None:
        """If a snippet is short and the URL is in the dump cache, extend it
        from the cached content. Pure local; never fetches."""
        for r in results:
            if len(r.snippet) >= SNIPPET_TARGET:
                continue
            cached = _read_dump(r.url)
            if not cached:
                continue
            head = cached.strip().split("\n\n", 1)[0]
            if len(head) > SNIPPET_GOAL:
                head = head[:SNIPPET_GOAL].rsplit(" ", 1)[0] + "…"
            if len(head) > len(r.snippet):
                r.snippet = head

    async def search(self, req: SearchRequest) -> dict:
        max_results = req.max_results or DEPTH_DEFAULTS[req.depth]
        timeout_s = req.timeout_ms / 1000.0
        attempts: list[dict] = []

        try:
            primary_name, _ = self._pick_backend(req.backend)
        except BackendError as e:
            return _failure(req.query, e.code, e.detail, attempts, [])

        # If the caller pinned a backend explicitly, honor it without failover
        # (their choice was deliberate). Otherwise iterate through configured
        # backends in registration order so a rate-limited Brave doesn't kill
        # the search when Tavily is also configured — the README and SKILL
        # advertise this as "automatic failover".
        if req.backend:
            ordered = [(primary_name, self._backends[primary_name])]
        else:
            ordered = self._ordered_backends(primary_name)

        started = time.monotonic()
        last_failure: tuple[str, str, str] | None = None  # (name, code, detail)
        raw = None
        used_name: str | None = None
        used_backend: Backend | None = None
        for name, backend in ordered:
            try:
                raw = await asyncio.wait_for(
                    backend.search(
                        req.query,
                        max_results=max_results,
                        time_range=req.time_range,
                        timeout=min(timeout_s, 10.0),
                    ),
                    timeout=timeout_s,
                )
                attempts.append({"backend": name, "result": f"{len(raw)} results"})
                used_name, used_backend = name, backend
                break
            except asyncio.TimeoutError:
                attempts.append({"backend": name, "result": "timeout"})
                last_failure = (name, "TIMEOUT", f"backend {name} timed out")
                continue
            except BackendError as e:
                attempts.append({"backend": name, "result": e.code.lower()})
                last_failure = (name, e.code, e.detail)
                if e.code not in _RETRYABLE_BACKEND_CODES:
                    # Non-retryable (auth, config, etc.) — stop trying others.
                    break
                continue

        if raw is None or used_backend is None or used_name is None:
            # All backends failed. Surface the last failure's code/detail.
            if last_failure is None:
                return _failure(req.query, "NO_BACKEND_CONFIGURED", "no backends attempted", attempts, [])
            _, code, detail = last_failure
            return _failure(
                req.query, code, detail, attempts,
                _suggest_on_failure(code, list(self._backends.keys())),
            )

        if not raw:
            return _failure(
                req.query, "EMPTY_RESULTS", f"backend {used_name} returned no results",
                attempts,
                ["rewrite the query", "try a broader phrasing", "try a different backend"],
            )

        annotated = self._annotate(raw, profile=req.profile)
        self._enhance_snippets(annotated)

        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": True,
            "query": req.query,
            "backend_used": used_name,
            "depth_used": req.depth,
            "results": [r.to_dict() for r in annotated],
            "metadata": {
                "elapsed_ms": elapsed_ms,
                "estimated_cost_usd": round(used_backend.cost_per_call_usd, 4),
                "result_count": len(annotated),
            },
        }

    async def search_and_read(self, req: SearchAndReadRequest) -> dict:
        # Step 1: search.
        s_req = SearchRequest(query=req.query, depth=req.depth, profile=req.profile,
                              timeout_ms=min(15_000, req.timeout_ms))
        search_started = time.monotonic()
        s_resp = await self.search(s_req)
        search_elapsed = int((time.monotonic() - search_started) * 1000)
        if not s_resp.get("ok"):
            return s_resp

        results = s_resp["results"]
        top = results[: req.read_top_n]
        allowed_urls = {r["url"] for r in top}

        # Step 2: fan out fetches in parallel, sharing the same BrowserPool.
        fetch_started = time.monotonic()
        remaining_ms = max(MIN_FETCH_TIMEOUT_MS, req.timeout_ms - search_elapsed)

        async def fetch_one(url: str) -> tuple[str, dict]:
            try:
                fr = FetchRequest(
                    url=url,
                    profile=req.profile,
                    max_inline_tokens=req.read_max_inline_tokens,
                    timeout_ms=remaining_ms,
                )
                return url, await self._router.fetch(fr)
            except Exception as e:
                return url, {
                    "ok": False,
                    "error_code": "INTERNAL_ERROR",
                    "error_detail": f"{type(e).__name__}: {e}",
                }

        outs = await asyncio.gather(
            *(fetch_one(r["url"]) for r in top), return_exceptions=True
        )
        fetch_elapsed = int((time.monotonic() - fetch_started) * 1000)

        fetched: list[dict] = []
        failures: list[dict] = []
        for url, fout in outs:
            if url not in allowed_urls:
                continue  # defense-in-depth (shouldn't happen)
            if fout.get("ok"):
                fetched.append({
                    "url": fout["url"],
                    "final_url": fout.get("final_url"),
                    "title": fout.get("title", ""),
                    "content_markdown": fout.get("content", ""),
                    "content_truncated": bool(fout.get("content_truncated")),
                    "dump_path": fout.get("dump_path"),
                    "fetch_strategy_used": fout.get("strategy_used"),
                    "tokens_returned": _approx_tokens(fout.get("content", "")),
                    "headings": fout.get("headings", []),
                })
            else:
                failures.append({
                    "url": url,
                    "error_code": fout.get("error_code"),
                    "error_detail": fout.get("error_detail"),
                })

        resp: dict = {
            "ok": True,
            "query": req.query,
            "search_results": results,
            "fetched_pages": fetched,
            "fetch_failures": failures,
            "metadata": {
                "search_elapsed_ms": search_elapsed,
                "fetch_elapsed_ms": fetch_elapsed,
                "total_tokens_returned": sum(p["tokens_returned"] for p in fetched),
            },
        }
        # Surface truncation at the top level so an agent consuming several
        # pages at once doesn't have to scan every fetched_pages[*] entry
        # for content_truncated=True. Per-page dump_path stays the source
        # of truth — the warning just points the agent at it. (#43)
        truncated_count = sum(1 for p in fetched if p["content_truncated"])
        if truncated_count:
            resp["truncation_warning"] = (
                f"{truncated_count} of {len(fetched)} fetched pages exceeded "
                f"the token budget. Full content saved to dump files — see "
                f"the dump_path field on each truncated page."
            )
        return resp

    def fetch_url_within_search(
        self, *, url: str, allowed_urls: set[str]
    ) -> str | None:
        """Hook used by the server to enforce URL provenance for any
        search-derived fetch. Returns an error string if forbidden, else None."""
        if url not in allowed_urls:
            return ErrorCode.URL_NOT_ALLOWED.value  # using the existing enum
        return None


# -- helpers --


def _has_dump(url: str) -> bool:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return (DUMPS / f"{digest}.md").exists()


def _read_dump(url: str) -> str | None:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    p = DUMPS / f"{digest}.md"
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _approx_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _suggest_on_failure(code: str, all_backends: list[str]) -> list[str]:
    if code == "RATE_LIMITED":
        others = [b for b in all_backends if b]
        return [
            "wait ~60s and retry",
            f"try a different backend: {others}" if others else "no alternative backends configured",
        ]
    if code == "NO_BACKEND_CONFIGURED":
        return [
            "set one of: BRAVE_SEARCH_API_KEY (free 2k/mo), "
            "SERPER_API_KEY (free 2.5k once), TAVILY_API_KEY (free 1k/mo)",
            "or store a key in ~/.lightcrawl/config.json "
            '({"backends": {"<name>": {"api_key": "..."}}}); '
            "for tavily, `tvly login` writes ~/.tavily/config.json automatically",
        ]
    if code == "TIMEOUT":
        return ["increase timeout_ms", "check network"]
    return ["rephrase the query", "try a smaller depth"]


def _failure(
    query: str, code: str, detail: str, attempts: list[dict], suggestions: list[str]
) -> dict:
    return {
        "ok": False,
        "query": query,
        "error_code": code,
        "error_detail": detail,
        "attempts": attempts,
        "suggestions": suggestions,
    }
