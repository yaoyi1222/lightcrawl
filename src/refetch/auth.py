from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from .errors import ErrorCode, FetchError
from .paths import PROFILES, ensure_dirs
from .url_safety import etld1

LOGIN_URL_RE = re.compile(r"/(login|signin|sign-in|auth/?)(?:[/?]|$)", re.IGNORECASE)

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP_PORT = 9223


@dataclass
class ProfileMeta:
    name: str
    bound_domain: str
    created_at: str
    last_used_at: str | None = None
    last_validated_at: str | None = None
    status: str = "active"  # active | expired
    expired_reason: str | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _profile_state_path(name: str) -> Path:
    return PROFILES / f"{name}.json"


def _profile_meta_path(name: str) -> Path:
    return PROFILES / f"{name}.meta.json"


def _validate_profile_name(name: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", name):
        raise FetchError(
            ErrorCode.URL_NOT_ALLOWED,
            f"invalid profile name {name!r}: lowercase alnum, '-', '_', max 41 chars",
        )


def list_profiles() -> list[ProfileMeta]:
    ensure_dirs()
    out = []
    for meta_file in sorted(PROFILES.glob("*.meta.json")):
        try:
            data = json.loads(meta_file.read_text())
            out.append(ProfileMeta(**data))
        except Exception:
            continue
    return out


def get_profile(name: str) -> ProfileMeta:
    _validate_profile_name(name)
    p = _profile_meta_path(name)
    if not p.exists():
        raise FetchError(ErrorCode.PROFILE_NOT_FOUND, f"profile {name!r} does not exist")
    return ProfileMeta(**json.loads(p.read_text()))


def load_storage_state(name: str) -> dict:
    p = _profile_state_path(name)
    if not p.exists():
        raise FetchError(ErrorCode.PROFILE_NOT_FOUND, f"profile {name!r} state not found")
    return json.loads(p.read_text())


def save_profile(name: str, storage_state: dict, bound_domain: str, notes: str = "") -> ProfileMeta:
    _validate_profile_name(name)
    ensure_dirs()
    state_path = _profile_state_path(name)
    meta_path = _profile_meta_path(name)

    tmp_state = state_path.with_suffix(".json.tmp")
    tmp_state.write_text(json.dumps(storage_state))
    os.chmod(tmp_state, 0o600)
    tmp_state.replace(state_path)

    existing_created = None
    if meta_path.exists():
        try:
            existing_created = json.loads(meta_path.read_text()).get("created_at")
        except Exception:
            pass
    meta = ProfileMeta(
        name=name,
        bound_domain=bound_domain,
        created_at=existing_created or _now(),
        last_used_at=None,
        last_validated_at=_now(),
        status="active",
        notes=notes,
    )
    tmp_meta = meta_path.with_suffix(".json.tmp")
    tmp_meta.write_text(json.dumps(meta.to_dict(), indent=2))
    os.chmod(tmp_meta, 0o600)
    tmp_meta.replace(meta_path)
    return meta


def update_profile_status(name: str, *, status: str, expired_reason: str | None = None) -> None:
    p = _profile_meta_path(name)
    if not p.exists():
        return
    data = json.loads(p.read_text())
    data["status"] = status
    if expired_reason is not None:
        data["expired_reason"] = expired_reason
    if status == "active":
        data["last_validated_at"] = _now()
    data["last_used_at"] = _now()
    p.write_text(json.dumps(data, indent=2))
    os.chmod(p, 0o600)


def revoke_profile(name: str) -> bool:
    _validate_profile_name(name)
    state = _profile_state_path(name)
    meta = _profile_meta_path(name)
    found = False
    for f in (state, meta):
        if f.exists():
            f.unlink()
            found = True
    return found


def _check_cdp_pages(port: int) -> list[dict] | None:
    """Lightweight HTTP poll — no CDP session, no browser control."""
    try:
        r = subprocess.run(
            ["curl", "-s", f"http://127.0.0.1:{port}/json"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip().startswith("["):
            return json.loads(r.stdout)
    except Exception:
        pass
    return None


async def interactive_login(
    *,
    profile: str,
    url: str,
    success_selector: str | None = None,
    timeout_ms: int = 5 * 60 * 1000,
) -> ProfileMeta:
    """Open a HEADED browser, let the user log in, then save storage_state.

    Chrome is launched via subprocess with zero Playwright involvement during
    the login phase — Google OAuth sees a normal user-initiated browser.  Only
    AFTER login is detected do we briefly connect via CDP to harvest cookies.
    """
    _validate_profile_name(profile)
    bound = etld1(url)
    if not bound:
        raise FetchError(ErrorCode.URL_NOT_ALLOWED, f"cannot derive eTLD+1 from {url!r}")

    user_data_dir = str(PROFILES / f"chrome-data-{profile}")
    os.makedirs(user_data_dir, exist_ok=True)

    # 1 — Launch Chrome natively (no Playwright, no automation flags)
    chrome = subprocess.Popen(
        [
            CHROME_PATH,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + (timeout_ms / 1000.0)

    # 2 — Wait for CDP endpoint to be reachable
    for _ in range(60):
        if time.monotonic() > deadline:
            chrome.terminate()
            raise FetchError(ErrorCode.TIMEOUT, "Chrome did not start in time")
        pages = _check_cdp_pages(CDP_PORT)
        if pages is not None:
            break
        await asyncio.sleep(0.5)

    # 3 — Poll for login completion via lightweight HTTP (no CDP session)
    last_url = ""
    last_url_change = time.monotonic()

    while time.monotonic() < deadline:
        pages = _check_cdp_pages(CDP_PORT)
        if pages is None:
            # Browser might have been closed
            await asyncio.sleep(1)
            continue

        # Find the first page with a real URL
        cur = ""
        for p in pages:
            pu = p.get("url", "")
            if pu and not pu.startswith("about:") and pu != "chrome://newtab/":
                cur = pu
                break

        if not cur:
            await asyncio.sleep(1)
            continue

        if cur != last_url:
            last_url = cur
            last_url_change = time.monotonic()

        if not LOGIN_URL_RE.search(cur) and (time.monotonic() - last_url_change) >= 3.0:
            # Login detected — now briefly connect to harvest cookies
            break

        await asyncio.sleep(1)

    else:
        chrome.terminate()
        raise FetchError(
            ErrorCode.TIMEOUT,
            f"login not detected within {timeout_ms}ms",
        )

    # 4 — Brief CDP connect: grab state and disconnect immediately
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(
                f"http://127.0.0.1:{CDP_PORT}"
            )
            contexts = browser.contexts
            ctx = contexts[0] if contexts else await browser.new_context()
            if ctx.pages:
                # Navigate away from any Google OAuth page before grabbing state
                # to avoid the brief CDP connection being detected
                pass
            state = await ctx.storage_state()
            await browser.close()
    except Exception as e:
        chrome.terminate()
        raise FetchError(ErrorCode.UNKNOWN, f"failed to harvest cookies: {e}") from e

    chrome.terminate()
    return save_profile(profile, state, bound)
