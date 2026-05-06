from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import auth
from .errors import ErrorCode, FetchError
from .paths import ensure_dirs
from .router import FetchRequest, Router, WaitForArg
from .search.service import SearchAndReadRequest, SearchRequest, SearchService

server = Server("refetch")
_router: Router | None = None
_search: SearchService | None = None


def _get_router() -> Router:
    """Lazy Router singleton — fetch tools use this. No search dependency."""
    global _router
    if _router is None:
        _router = Router()
    return _router


def _get_search() -> SearchService:
    """Lazy SearchService singleton — search tools use this.

    Shares the same Router instance with fetch so BrowserPool is not duplicated.
    """
    global _search
    if _search is None:
        _search = SearchService(router=_get_router())
    return _search


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="fetch_url",
            description=(
                "Fetch a URL with anti-bot bypass and JS rendering. Auto-escalates "
                "from HTTP+ (curl_cffi with browser fingerprint) to a stealth Playwright "
                "browser when needed. Returns markdown by default. Pass `profile` to use "
                "a saved login session."
            ),
            inputSchema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "strategy": {
                        "type": "string",
                        "enum": ["auto", "http", "browser", "authed"],
                        "default": "auto",
                    },
                    "profile": {"type": "string"},
                    "output_format": {
                        "type": "string",
                        "enum": ["markdown", "html", "text"],
                        "default": "markdown",
                    },
                    "selector": {"type": "string"},
                    "wait_for": {
                        "type": "object",
                        "properties": {
                            "selector": {"type": "string"},
                            "network_idle": {"type": "boolean"},
                            "timeout_ms": {"type": "integer", "default": 10000},
                        },
                    },
                    "max_inline_tokens": {"type": "integer", "default": 8000},
                    "timeout_ms": {"type": "integer", "default": 30000},
                },
            },
        ),
        Tool(
            name="auth_login",
            description=(
                "Open a HEADED browser window for the user to log in to a site, then "
                "save the session as a named profile. Claude does NOT touch passwords; "
                "the user completes login (including 2FA/CAPTCHA) themselves. The profile "
                "is bound to the eTLD+1 of `url` and reusable via fetch_url(url, profile=<name>)."
            ),
            inputSchema={
                "type": "object",
                "required": ["profile", "url"],
                "properties": {
                    "profile": {"type": "string", "description": "short name, e.g. 'twitter'"},
                    "url": {"type": "string", "description": "login page URL"},
                    "success_selector": {
                        "type": "string",
                        "description": (
                            "optional CSS selector that appears only when logged in. "
                            "If omitted, success is detected by the URL no longer matching "
                            "/login|/signin|/auth and 3s of URL stability."
                        ),
                    },
                    "timeout_ms": {"type": "integer", "default": 300000},
                },
            },
        ),
        Tool(
            name="auth_status",
            description=(
                "List saved login profiles or get info on one. Returns metadata only "
                "(name, bound domain, timestamps, status); never returns cookie contents."
            ),
            inputSchema={
                "type": "object",
                "properties": {"profile": {"type": "string"}},
            },
        ),
        Tool(
            name="auth_revoke",
            description="Delete a saved login profile (storage state and metadata).",
            inputSchema={
                "type": "object",
                "required": ["profile"],
                "properties": {"profile": {"type": "string"}},
            },
        ),
        Tool(
            name="search",
            description=(
                "Web search with rich snippets and structured results. Returns "
                "title, URL, snippet (≥300 chars when possible), page age, and a "
                "fetch_hint per result. For most factual questions the snippet "
                "alone is enough — don't fetch unless you need full content. "
                "Use `depth=quick` for single-fact lookups, `normal` (default) "
                "for usual research, `deep` only when explicitly doing deep research."
            ),
            inputSchema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "depth": {
                        "type": "string",
                        "enum": ["quick", "normal", "deep"],
                        "default": "normal",
                    },
                    "backend": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "time_range": {
                        "type": "object",
                        "properties": {
                            "after": {"type": "string", "description": "ISO date"},
                            "before": {"type": "string", "description": "ISO date"},
                        },
                    },
                    "profile": {"type": "string"},
                    "timeout_ms": {"type": "integer", "default": 15000},
                },
            },
        ),
        Tool(
            name="search_and_read",
            description=(
                "One-shot: search + fetch the top N results in parallel. Returns "
                "the search results AND the fetched markdown for the top pages. "
                "Saves ~30%+ tokens vs separate search + N×fetch_url calls. Use "
                "this when the user wants a researched answer, not just links."
            ),
            inputSchema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "depth": {
                        "type": "string",
                        "enum": ["quick", "normal", "deep"],
                        "default": "normal",
                    },
                    "read_top_n": {"type": "integer", "default": 3},
                    "read_max_inline_tokens": {"type": "integer", "default": 4000},
                    "profile": {"type": "string"},
                    "timeout_ms": {"type": "integer", "default": 60000},
                },
            },
        ),
        Tool(
            name="list_backends",
            description=(
                "List available search backends and whether each is configured "
                "(API key present). No arguments."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
    arguments = arguments or {}
    try:
        if name == "fetch_url":
            result = await _do_fetch(arguments)
        elif name == "auth_login":
            result = await _do_auth_login(arguments)
        elif name == "auth_status":
            result = _do_auth_status(arguments)
        elif name == "auth_revoke":
            result = _do_auth_revoke(arguments)
        elif name == "search":
            result = await _do_search(arguments)
        elif name == "search_and_read":
            result = await _do_search_and_read(arguments)
        elif name == "list_backends":
            result = {"ok": True, "backends": _get_search().list_backends()}
        else:
            result = {"ok": False, "error_code": "UNKNOWN_TOOL", "error_detail": name}
    except FetchError as e:
        result = {"ok": False, "error_code": e.code.value, "error_detail": e.detail}
    except Exception as e:  # last-resort safety net
        result = {"ok": False, "error_code": ErrorCode.UNKNOWN.value, "error_detail": str(e)}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def _do_fetch(args: dict[str, Any]) -> dict:
    wait_for = None
    if isinstance(args.get("wait_for"), dict):
        wf = args["wait_for"]
        wait_for = WaitForArg(
            selector=wf.get("selector"),
            network_idle=bool(wf.get("network_idle", False)),
            timeout_ms=int(wf.get("timeout_ms", 10_000)),
        )
    req = FetchRequest(
        url=args["url"],
        strategy=args.get("strategy", "auto"),
        profile=args.get("profile"),
        output_format=args.get("output_format", "markdown"),
        selector=args.get("selector"),
        wait_for=wait_for,
        max_inline_tokens=int(args.get("max_inline_tokens", 8000)),
        timeout_ms=int(args.get("timeout_ms", 30_000)),
    )
    return await _get_router().fetch(req)


async def _do_auth_login(args: dict[str, Any]) -> dict:
    meta = await auth.interactive_login(
        profile=args["profile"],
        url=args["url"],
        success_selector=args.get("success_selector"),
        timeout_ms=int(args.get("timeout_ms", 5 * 60 * 1000)),
    )
    return {"ok": True, "profile": meta.name, "bound_domain": meta.bound_domain}


def _do_auth_status(args: dict[str, Any]) -> dict:
    name = args.get("profile")
    if name:
        meta = auth.get_profile(name)
        return {"ok": True, "profiles": [meta.to_dict()]}
    return {"ok": True, "profiles": [m.to_dict() for m in auth.list_profiles()]}


def _do_auth_revoke(args: dict[str, Any]) -> dict:
    name = args["profile"]
    found = auth.revoke_profile(name)
    return {"ok": True, "profile": name, "revoked": found}


async def _do_search(args: dict[str, Any]) -> dict:
    tr = args.get("time_range") or {}
    req = SearchRequest(
        query=args["query"],
        depth=args.get("depth", "normal"),
        backend=args.get("backend"),
        max_results=args.get("max_results"),
        time_range=(tr.get("after"), tr.get("before")),
        profile=args.get("profile"),
        timeout_ms=int(args.get("timeout_ms", 15_000)),
    )
    return await _get_search().search(req)


async def _do_search_and_read(args: dict[str, Any]) -> dict:
    req = SearchAndReadRequest(
        query=args["query"],
        depth=args.get("depth", "normal"),
        read_top_n=int(args.get("read_top_n", 3)),
        read_max_inline_tokens=int(args.get("read_max_inline_tokens", 4000)),
        profile=args.get("profile"),
        timeout_ms=int(args.get("timeout_ms", 60_000)),
    )
    return await _get_search().search_and_read(req)


async def _serve() -> None:
    ensure_dirs()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    run()
