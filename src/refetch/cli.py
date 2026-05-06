from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import auth
from .errors import FetchError
from .paths import ensure_dirs


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _cmd_auth_list(_: argparse.Namespace) -> int:
    _print({"profiles": [m.to_dict() for m in auth.list_profiles()]})
    return 0


def _cmd_auth_show(args: argparse.Namespace) -> int:
    try:
        meta = auth.get_profile(args.profile)
    except FetchError as e:
        _print({"ok": False, "error_code": e.code.value, "error_detail": e.detail})
        return 1
    _print(meta.to_dict())
    return 0


def _cmd_auth_revoke(args: argparse.Namespace) -> int:
    found = auth.revoke_profile(args.profile)
    _print({"ok": True, "profile": args.profile, "revoked": found})
    return 0


def _cmd_auth_login(args: argparse.Namespace) -> int:
    try:
        meta = asyncio.run(
            auth.interactive_login(
                profile=args.profile,
                url=args.url,
                success_selector=args.success_selector,
                timeout_ms=args.timeout_ms,
            )
        )
    except FetchError as e:
        _print({"ok": False, "error_code": e.code.value, "error_detail": e.detail})
        return 1
    _print({"ok": True, "profile": meta.name, "bound_domain": meta.bound_domain})
    return 0


def main(argv: list[str] | None = None) -> int:
    ensure_dirs()
    parser = argparse.ArgumentParser(prog="refetch")
    sub = parser.add_subparsers(dest="cmd", required=True)

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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
