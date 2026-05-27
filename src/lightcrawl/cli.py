from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys

from . import auth, sitemap
from .errors import ErrorCode, FetchError
from .paths import ensure_dirs
from .router import FetchRequest, Router, WaitForArg
from .search.service import (
    SearchAndReadRequest,
    SearchRequest,
    SearchService,
)


# HTML5 element-name shape. Rejects malformed include_tag / exclude_tag inputs
# (empty string, CSS selectors, "nav, footer" comma typos) before they reach
# lxml's xpath builder — an invalid xpath there raises XPathEvalError, which
# would breach the "errors are values, not exceptions" boundary contract.
_TAG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9-]*$")


# v0.3 PR 2.4 — duration parser for cache flags (see docs/v0.3/design.md §3).
# Accepts 300ms / 5s / 10m / 2h / 7d shape. Bare integers are rejected because
# the unit determines orders of magnitude (60 → seconds? minutes?), so requiring
# a unit prevents silent off-by-1000x bugs.
_DUR_RE = re.compile(r"^\s*(\d+)\s*(ms|s|m|h|d)\s*$")
_DUR_UNITS_MS = {
    "ms": 1, "s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000,
}


def _parse_duration_ms(value: str) -> int:
    """Parse ``300ms`` / ``5s`` / ``10m`` / ``2h`` / ``7d`` → milliseconds.

    Used as an argparse ``type=`` so invalid input becomes a clean
    ``argparse`` error rather than crashing inside the subcommand. The
    regex is anchored on both ends — partial matches like ``"5sblahblah"``
    are rejected.
    """
    if not isinstance(value, str):
        raise argparse.ArgumentTypeError(
            f"duration must be a string like '5s' or '2h', got {type(value).__name__}",
        )
    m = _DUR_RE.match(value)
    if m is None:
        raise argparse.ArgumentTypeError(
            f"invalid duration {value!r}; expected forms like "
            f"'500ms', '5s', '10m', '2h', '7d'",
        )
    n = int(m.group(1))
    if n <= 0:
        raise argparse.ArgumentTypeError(
            f"duration must be positive, got {value!r}",
        )
    return n * _DUR_UNITS_MS[m.group(2)]


def _add_cache_flags(p: argparse.ArgumentParser) -> None:
    """Attach the four cache control flags from design §3 to a parser.

    Shared across ``fetch`` / ``search-and-read`` (and future ``crawl`` /
    ``batch-fetch``) so every subcommand that supports cache speaks the
    same dialect. argparse mutex enforcement happens later in
    ``_validate_cache_flags`` — argparse's own ``mutually_exclusive_group``
    can't express "A may combine with B and C but not D"."""
    p.add_argument(
        "--max-age",
        dest="max_age_ms",
        type=_parse_duration_ms,
        default=None,
        metavar="DUR",
        help=(
            "Max acceptable cache age (e.g. '500ms', '5s', '10m', '2h', '7d'). "
            "Cache hit within this window skips the network. "
            "For ``fetch``, also enables cache write unless --no-store."
        ),
    )
    p.add_argument(
        "--cache-only",
        dest="cache_only",
        action="store_true",
        help=(
            "Read-only cache mode. Cache miss returns CACHE_MISS without "
            "touching the network. Use for offline replay."
        ),
    )
    p.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        help=(
            "Bypass cache entirely (no read, no write). Mutually exclusive "
            "with --max-age, --cache-only, and --no-store; combining them "
            "returns CACHE_FLAG_CONFLICT."
        ),
    )
    p.add_argument(
        "--no-store",
        dest="no_store",
        action="store_true",
        help=(
            "Read cache (respecting --max-age) but don't write back. Useful "
            "for one-shot fetches that shouldn't pollute the cache."
        ),
    )


def _validate_cache_flags(args: argparse.Namespace) -> dict | None:
    """Return a CACHE_FLAG_CONFLICT envelope if ``--no-cache`` is combined
    with any of ``--max-age``/``--cache-only``/``--no-store``; else None.

    Why a return-value instead of ``parser.error()``: argparse's
    ``error()`` prints to stderr and exits non-zero, which would breach
    the "single JSON object on stdout" contract that skills rely on."""
    if not getattr(args, "no_cache", False):
        return None
    conflicts: list[str] = []
    if getattr(args, "max_age_ms", None) is not None:
        conflicts.append("--max-age")
    if getattr(args, "cache_only", False):
        conflicts.append("--cache-only")
    if getattr(args, "no_store", False):
        conflicts.append("--no-store")
    if not conflicts:
        return None
    return {
        "ok": False,
        "error_code": ErrorCode.CACHE_FLAG_CONFLICT.value,
        "error_detail": (
            "--no-cache cannot be combined with "
            + ", ".join(conflicts)
            + " (see design §3 truth table)."
        ),
    }


def _resolve_cache_kwargs(
    args: argparse.Namespace, *, default_store_in_cache: bool = False,
) -> dict:
    """Map CLI flags to FetchRequest cache fields per the design §3 truth
    table. Validation (mutex) must run first.

    ``default_store_in_cache`` is the subcommand's default for write
    behaviour when neither ``--max-age`` nor ``--no-store`` are set. For
    ``fetch``/``search-and-read`` this is False (v0.2-compatible);
    ``crawl``/``batch-fetch`` will flip it to True in a later PR.
    """
    if getattr(args, "no_cache", False):
        return dict(
            max_age_ms=None, cache_only=False,
            store_in_cache=False, no_cache=True,
        )
    cache_only = bool(getattr(args, "cache_only", False))
    max_age_ms = getattr(args, "max_age_ms", None)
    no_store = bool(getattr(args, "no_store", False))
    if cache_only:
        # cache-only mode never writes (the design table makes this
        # explicit: the entire point is "look at the cache, don't go to
        # the net"; if we wrote on cache miss we'd... still be doing
        # nothing, because cache-only short-circuits before network).
        store_in_cache = False
    elif max_age_ms is not None:
        # --max-age implies write (the recommended `fetch --max-age 1h`
        # combo), overridable by --no-store.
        store_in_cache = not no_store
    else:
        # No cache-related flag specified — honour the subcommand default.
        # --no-store alone is a no-op for fetch (which defaults to False)
        # but matters for crawl/batch-fetch's default-True.
        store_in_cache = default_store_in_cache and not no_store
    return dict(
        max_age_ms=max_age_ms,
        cache_only=cache_only,
        store_in_cache=store_in_cache,
        no_cache=False,
    )


def _clean_tags(raw) -> list[str]:
    # Reject anything that isn't a list — a bare string would otherwise
    # iterate character-by-character, which is never the caller's intent.
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for t in raw:
        if not isinstance(t, str):
            continue
        s = t.strip().lower()
        if _TAG_RE.match(s):
            out.append(s)
    return out


def _parse_headers(raw: list[str] | None) -> dict[str, str]:
    """Parse `--header KEY=VAL` (or `KEY: VAL`) flags into a dict. Malformed
    entries (no separator) are silently dropped — argparse already accepted
    them as strings, but garbage stays out of the request."""
    if not raw:
        return {}
    out: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, str):
            continue
        if "=" in item:
            k, v = item.split("=", 1)
        elif ":" in item:
            k, v = item.split(":", 1)
        else:
            continue
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


def _parse_actions(raw: str | None) -> list:
    """Parse `--actions` value: JSON string or `@filepath` to a JSON file."""
    import json as _json
    from .actions import parse_actions as _parse

    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("@"):
        path = raw[1:]
        try:
            with open(path, "r") as f:
                raw = f.read()
        except OSError as e:
            raise ValueError(f"cannot read actions file {path!r}: {e}") from e
    try:
        items = _json.loads(raw)
    except _json.JSONDecodeError as e:
        raise ValueError(f"--actions JSON is invalid: {e}") from e
    return _parse(items)


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _exit_code(result: dict) -> int:
    """Exit 0 on `ok: true`, 1 otherwise. Skills can branch on either the
    exit code or the JSON `error_code` field — both paths agree."""
    return 0 if result.get("ok") else 1


def _safe_run(coro) -> int:
    """Run an async subcommand, converting any uncaught exception into the
    same `{"ok": false, "error_code": "UNKNOWN", ...}` envelope the inner
    handlers produce. Without this, an unexpected exception (third-party
    bug, OOM, etc.) would print a Python traceback to stdout and break
    the JSON-per-line contract that skills rely on."""
    try:
        return asyncio.run(coro)
    except FetchError as e:
        _print({"ok": False, "error_code": e.code.value, "error_detail": e.detail})
        return 1
    except Exception as e:  # last-resort safety net
        _print({
            "ok": False,
            "error_code": ErrorCode.UNKNOWN.value,
            "error_detail": f"{type(e).__name__}: {e}",
        })
        return 1


# -- auth subcommands --------------------------------------------------------


def _cmd_auth_list(_: argparse.Namespace) -> int:
    _print({"ok": True, "profiles": [m.to_dict() for m in auth.list_profiles()]})
    return 0


def _cmd_auth_show(args: argparse.Namespace) -> int:
    try:
        meta = auth.get_profile(args.profile)
    except FetchError as e:
        _print({"ok": False, "error_code": e.code.value, "error_detail": e.detail})
        return 1
    # Same shape as `auth list`: always `{ok, profiles: [...]}`, even for
    # a single profile lookup. Skills can branch on `result.ok` uniformly.
    _print({"ok": True, "profiles": [meta.to_dict()]})
    return 0


def _cmd_auth_revoke(args: argparse.Namespace) -> int:
    found = auth.revoke_profile(args.profile)
    _print({"ok": True, "profile": args.profile, "revoked": found})
    return 0


def _cmd_auth_login(args: argparse.Namespace) -> int:
    return _safe_run(_run_auth_login(args))


async def _run_auth_login(args: argparse.Namespace) -> int:
    meta = await auth.interactive_login(
        profile=args.profile,
        url=args.url,
        success_selector=args.success_selector,
        timeout_ms=args.timeout_ms,
    )
    _print({"ok": True, "profile": meta.name, "bound_domain": meta.bound_domain})
    return 0


# -- fetch / search subcommands ---------------------------------------------


def _cmd_fetch(args: argparse.Namespace) -> int:
    err = _validate_cache_flags(args)
    if err is not None:
        _print(err)
        return 1
    return _safe_run(_run_fetch(args))


async def _run_fetch(args: argparse.Namespace) -> int:
    wait_for = None
    if args.wait_for_selector or args.wait_for_network_idle:
        wait_for = WaitForArg(
            selector=args.wait_for_selector,
            network_idle=args.wait_for_network_idle,
            timeout_ms=args.wait_for_timeout_ms,
        )
    # PR 5: parse declarative actions from JSON or @file
    raw_actions = getattr(args, "actions", None)
    parsed_actions: list = []
    if raw_actions:
        parsed_actions = _parse_actions(raw_actions)

    # remove_base64_images uses BooleanOptionalAction (default=None) so an
    # absent flag yields None and falls through to FetchRequest's dataclass
    # default. Passing False here would override the v0.3 default of True.
    fetch_kwargs = dict(
        url=args.url,
        strategy=args.strategy,
        profile=args.profile,
        output_format=args.output_format,
        selector=args.selector,
        wait_for=wait_for,
        max_inline_tokens=args.max_inline_tokens,
        timeout_ms=args.timeout_ms,
        headers=_parse_headers(getattr(args, "headers", None)),
        include_tags=_clean_tags(getattr(args, "include_tags", None)),
        exclude_tags=_clean_tags(getattr(args, "exclude_tags", None)),
        mobile=bool(getattr(args, "mobile", False)),
        actions=parsed_actions,
        # v0.3 PR 2.4 — cache controls (design §3). ``fetch`` defaults to
        # store_in_cache=False so v0.2 callers stay byte-identical.
        **_resolve_cache_kwargs(args, default_store_in_cache=False),
    )
    rbi = getattr(args, "remove_base64_images", None)
    if rbi is not None:
        fetch_kwargs["remove_base64_images"] = bool(rbi)
    req = FetchRequest(**fetch_kwargs)
    router = Router()
    try:
        result = await router.fetch(req)
    finally:
        await router.close()
    _print(result)
    return _exit_code(result)


def _cmd_search(args: argparse.Namespace) -> int:
    return _safe_run(_run_search(args))


async def _run_search(args: argparse.Namespace) -> int:
    req = SearchRequest(
        query=args.query,
        depth=args.depth,
        backend=args.backend,
        max_results=args.max_results,
        time_range=(args.time_range_after, args.time_range_before),
        profile=args.profile,
        timeout_ms=args.timeout_ms,
    )
    svc = SearchService()
    try:
        result = await svc.search(req)
    finally:
        await svc.close()
    _print(result)
    return _exit_code(result)


def _cmd_search_and_read(args: argparse.Namespace) -> int:
    err = _validate_cache_flags(args)
    if err is not None:
        _print(err)
        return 1
    return _safe_run(_run_search_and_read(args))


async def _run_search_and_read(args: argparse.Namespace) -> int:
    req = SearchAndReadRequest(
        query=args.query,
        depth=args.depth,
        read_top_n=args.read_top_n,
        read_max_inline_tokens=args.read_max_inline_tokens,
        profile=args.profile,
        timeout_ms=args.timeout_ms,
        # v0.3 PR 2.4 — cache controls propagate to every per-result
        # fetch the service fans out. Default store_in_cache=False
        # preserves v0.2 behaviour.
        **_resolve_cache_kwargs(args, default_store_in_cache=False),
    )
    svc = SearchService()
    try:
        result = await svc.search_and_read(req)
    finally:
        await svc.close()
    _print(result)
    return _exit_code(result)


# -- map --------------------------------------------------------------------


def _cmd_map(args: argparse.Namespace) -> int:
    return _safe_run(_run_map(args))


async def _run_map(args: argparse.Namespace) -> int:
    router = Router()
    try:
        result = await sitemap.run_map(
            args.url,
            search_filter=args.search,
            limit=args.limit,
            router=router,
        )
    finally:
        await router.close()
    payload = result.to_dict()
    _print(payload)
    return _exit_code(payload)


def _cmd_list_backends(_: argparse.Namespace) -> int:
    return _safe_run(_run_list_backends())


async def _run_list_backends() -> int:
    # SearchService.list_backends() is sync today and the BrowserPool is
    # lazy, so close() is a no-op — but routing through the same async
    # try/finally as the other subcommands keeps the cleanup contract
    # uniform. If anyone later adds resource allocation to
    # SearchService.__init__ or list_backends(), this won't silently leak.
    svc = SearchService()
    try:
        _print({"ok": True, "backends": svc.list_backends()})
    finally:
        await svc.close()
    return 0


# -- argparse wiring --------------------------------------------------------


def _add_fetch_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "fetch",
        help="Fetch a URL with auto strategy escalation (L1 HTTP → L2 browser → L3 authed)",
    )
    p.add_argument("url")
    p.add_argument(
        "--strategy",
        choices=["auto", "http", "browser", "authed"],
        default="auto",
        help="Force a fetch strategy (default: auto-escalate)",
    )
    p.add_argument("--profile", help="Use a saved login profile (forces L3)")
    p.add_argument(
        "--output-format",
        dest="output_format",
        choices=["markdown", "html", "text", "screenshot", "markdown+screenshot", "links", "images"],
        default="markdown",
        help=(
            "Body format. `screenshot` returns an empty text body and a PNG "
            "path under `screenshots[]`; `markdown+screenshot` returns both. "
            "Screenshot formats force L2 (Playwright) — L1 can't render. "
            "`links` returns a JSON array of extracted links; "
            "`images` returns a JSON array of extracted images. "
            "links and images are always present under `metadata` regardless of format."
        ),
    )
    p.add_argument("--selector", help="CSS selector to scope content extraction")
    p.add_argument(
        "--wait-for-selector",
        dest="wait_for_selector",
        help="CSS selector to wait for before reading the page (SPAs)",
    )
    p.add_argument(
        "--wait-for-network-idle",
        dest="wait_for_network_idle",
        action="store_true",
        help="Wait for network idle before reading the page",
    )
    p.add_argument(
        "--wait-for-timeout-ms",
        dest="wait_for_timeout_ms",
        type=int,
        default=10_000,
    )
    p.add_argument(
        "--max-inline-tokens",
        dest="max_inline_tokens",
        type=int,
        default=8000,
        help="Token budget for inline content; overflow goes to a dump file",
    )
    p.add_argument(
        "--timeout-ms", dest="timeout_ms", type=int, default=30_000,
    )
    p.add_argument(
        "--header",
        dest="headers",
        action="append",
        default=[],
        metavar="KEY=VAL",
        help=(
            "Extra HTTP request header, repeatable. Merged after the impersonate "
            "profile (caller wins on collision). Avoid overriding User-Agent on "
            "L1 — that desyncs UA from the TLS fingerprint."
        ),
    )
    p.add_argument(
        "--include-tag",
        dest="include_tags",
        action="append",
        default=[],
        metavar="TAG",
        help=(
            "Tag-level allowlist, repeatable. When non-empty, automatic "
            "<main>/<article> scoping is skipped and the result is every match "
            "in document order. No-match falls back to whole <body>. Must match "
            "HTML5 element-name shape."
        ),
    )
    p.add_argument(
        "--exclude-tag",
        dest="exclude_tags",
        action="append",
        default=[],
        metavar="TAG",
        help=(
            "Tag-level denylist, repeatable. Applied on top of the built-in "
            "script/style/iframe strip. Must match HTML5 element-name shape."
        ),
    )
    p.add_argument(
        "--mobile",
        action="store_true",
        help=(
            "Emulate a mobile client on both layers. L1 switches curl_cffi to "
            "the iOS Safari impersonate profile (UA + TLS fingerprint together); "
            "L2 uses Playwright's 'iPhone 13' device descriptor."
        ),
    )
    p.add_argument(
        "--remove-base64-images",
        dest="remove_base64_images",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Drop <img> elements whose src is a data: URI before extraction. "
            "Default in v0.3 is ON: data: URIs are dropped while external "
            "<img> tags survive into markdown. Use --no-remove-base64-images "
            "to restore the v0.2 behavior of stripping every <img>."
        ),
    )
    p.add_argument(
        "--actions",
        dest="actions",
        metavar="JSON_OR_@FILE",
        help=(
            "Declarative browser actions as a JSON array, or @path to a JSON "
            "file. Actions run after page load and before content extraction. "
            "Supported types: click, write, press, wait, scroll, screenshot. "
            'Example: \'[{"type":"click","selector":"#btn"},{"type":"screenshot"'
            ',"label":"post-click"}]\'. Non-empty actions force L2 (browser).'
        ),
    )
    _add_cache_flags(p)
    p.set_defaults(func=_cmd_fetch)


def _add_search_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("search", help="Web search via Brave/Serper/Tavily with failover")
    p.add_argument("query")
    p.add_argument(
        "--depth",
        choices=["quick", "normal", "deep"],
        default="normal",
    )
    p.add_argument("--backend", help="Force a specific backend (skips failover)")
    p.add_argument("--max-results", dest="max_results", type=int)
    p.add_argument(
        "--time-range-after", dest="time_range_after", help="ISO date lower bound"
    )
    p.add_argument(
        "--time-range-before", dest="time_range_before", help="ISO date upper bound"
    )
    p.add_argument(
        "--profile",
        help="Scope needs_login annotation to this profile only",
    )
    p.add_argument("--timeout-ms", dest="timeout_ms", type=int, default=15_000)
    p.set_defaults(func=_cmd_search)


def _add_search_and_read_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "search-and-read",
        help="Search + parallel-fetch top N results in one call",
    )
    p.add_argument("query")
    p.add_argument("--depth", choices=["quick", "normal", "deep"], default="normal")
    p.add_argument(
        "--read-top-n", "--max-results",
        dest="read_top_n", type=int, default=3,
        help=(
            "Number of search results to fetch in parallel (default: 3). "
            "`--max-results` is accepted as an alias."
        ),
    )
    p.add_argument(
        "--read-max-inline-tokens",
        dest="read_max_inline_tokens",
        type=int,
        default=4000,
    )
    p.add_argument("--profile", help="Use saved login profile for the fetch phase")
    p.add_argument("--timeout-ms", dest="timeout_ms", type=int, default=60_000)
    _add_cache_flags(p)
    p.set_defaults(func=_cmd_search_and_read)


def _add_map_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "map",
        help="List reachable in-domain URLs (sitemap-first, homepage fallback)",
    )
    p.add_argument("url", help="seed URL; its scheme+host define the domain")
    p.add_argument(
        "--search", default=None,
        help="case-insensitive substring filter on discovered URLs",
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="cap the number of URLs returned (default: all, up to 50k)",
    )
    p.set_defaults(func=_cmd_map)


def _add_list_backends_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "list-backends",
        help="Show which search backends have API keys configured",
    )
    p.set_defaults(func=_cmd_list_backends)


def _add_auth_parser(sub: argparse._SubParsersAction) -> None:
    auth_p = sub.add_parser("auth", help="manage login profiles")
    auth_sub = auth_p.add_subparsers(dest="subcmd", required=True)

    p = auth_sub.add_parser("list")
    p.set_defaults(func=_cmd_auth_list)

    p = auth_sub.add_parser("show")
    p.add_argument("profile")
    p.set_defaults(func=_cmd_auth_show)

    p = auth_sub.add_parser("revoke")
    p.add_argument("profile")
    p.set_defaults(func=_cmd_auth_revoke)

    p = auth_sub.add_parser("login")
    p.add_argument("profile")
    p.add_argument("url")
    p.add_argument("--success-selector", dest="success_selector")
    p.add_argument("--timeout-ms", dest="timeout_ms", type=int, default=5 * 60 * 1000)
    p.set_defaults(func=_cmd_auth_login)


def main(argv: list[str] | None = None) -> int:
    ensure_dirs()
    parser = argparse.ArgumentParser(
        prog="lightcrawl",
        description=(
            "lightcrawl CLI — fetch URLs, search the web, and manage login "
            "profiles. Every command prints a JSON object on stdout; exit "
            "code 0 means ok=true, 1 means ok=false."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    _add_fetch_parser(sub)
    _add_search_parser(sub)
    _add_search_and_read_parser(sub)
    _add_map_parser(sub)
    _add_list_backends_parser(sub)
    _add_auth_parser(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
