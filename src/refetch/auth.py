from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

from .errors import ErrorCode, FetchError
from .paths import PROFILES, ensure_dirs
from .url_safety import etld1

LOGIN_URL_RE = re.compile(r"/(login|signin|sign-in|auth/?)(?:[/?]|$)", re.IGNORECASE)

CDP_PORT_DEFAULT = 9223


def _find_chrome() -> str:
    """Locate a Chrome/Chromium binary across platforms. Falls back to
    Playwright's bundled Chromium if no system Chrome is found."""
    if sys.platform == "darwin":
        mac_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(mac_path):
            return mac_path
    elif sys.platform == "win32":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c
    # Linux + fallback for unusual macOS/Windows installs
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    raise FetchError(
        ErrorCode.UNKNOWN,
        "Chrome/Chromium not found on PATH; install Google Chrome or set up "
        "Playwright's bundled chromium with `playwright install chromium`",
    )


def _find_free_port(start: int = CDP_PORT_DEFAULT, span: int = 50) -> int:
    """Bind-test a free localhost port in [start, start+span).

    The port can race — another process may grab it between this check and
    the Chrome launch. The caller's wait-for-CDP loop will surface that as a
    startup timeout, which is the same recovery path as a slow Chrome start.
    """
    for port in range(start, start + span):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise FetchError(
        ErrorCode.UNKNOWN, f"no free CDP port found in [{start}, {start + span})"
    )


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
        r = httpx.get(f"http://127.0.0.1:{port}/json", timeout=3.0)
        if r.status_code == 200 and r.text.strip().startswith("["):
            return r.json()
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

    chrome_path = _find_chrome()
    cdp_port = _find_free_port(CDP_PORT_DEFAULT)

    # 1 — Launch Chrome natively (no Playwright, no automation flags).
    # The whole flow is wrapped in try/finally so the subprocess is always
    # reaped — including on CancelledError / KeyboardInterrupt mid-poll.
    chrome = subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        deadline = time.monotonic() + (timeout_ms / 1000.0)

        # 2 — Wait for CDP endpoint to be reachable
        for _ in range(60):
            if time.monotonic() > deadline:
                raise FetchError(ErrorCode.TIMEOUT, "Chrome did not start in time")
            pages = _check_cdp_pages(cdp_port)
            if pages is not None:
                break
            await asyncio.sleep(0.5)

        # 3 — Poll for login completion via lightweight HTTP (no CDP session)
        last_url = ""
        last_url_change = time.monotonic()
        login_detected = False

        while time.monotonic() < deadline:
            pages = _check_cdp_pages(cdp_port)
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
                login_detected = True
                break

            await asyncio.sleep(1)

        if not login_detected:
            raise FetchError(
                ErrorCode.TIMEOUT,
                f"login not detected within {timeout_ms}ms",
            )

        # 4 — Brief CDP connect: grab state and disconnect immediately
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{cdp_port}"
                )
                contexts = browser.contexts
                ctx = contexts[0] if contexts else await browser.new_context()
                state = await ctx.storage_state()
                await browser.close()
        except Exception as e:
            raise FetchError(ErrorCode.UNKNOWN, f"failed to harvest cookies: {e}") from e

        return save_profile(profile, state, bound)
    finally:
        try:
            chrome.terminate()
            chrome.wait(timeout=5)
        except Exception:
            try:
                chrome.kill()
            except Exception:
                pass
