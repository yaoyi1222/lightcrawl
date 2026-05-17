from __future__ import annotations

import asyncio
import platform
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

from playwright.async_api import (
    Browser,
    BrowserContext,
    TimeoutError as PWTimeout,
    async_playwright,
)
from playwright_stealth import Stealth

_STEALTH = Stealth()

from .errors import ErrorCode, FetchError

DEFAULT_TIMEOUT = 15.0


def _default_user_agent() -> str:
    """Build a Chrome 120 UA whose platform token matches the host OS, so the
    UA doesn't contradict the JS-visible navigator.platform that stealth
    exposes — UA/platform mismatch is itself a bot-detection signal."""
    sysname = platform.system()
    if sysname == "Linux":
        os_token = "X11; Linux x86_64"
    elif sysname == "Windows":
        os_token = "Windows NT 10.0; Win64; x64"
    else:
        # Darwin + unknown -> macOS UA (the project's prior default)
        os_token = "Macintosh; Intel Mac OS X 10_15_7"
    return (
        f"Mozilla/5.0 ({os_token}) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )


_DEFAULT_UA = _default_user_agent()


@dataclass
class WaitFor:
    selector: str | None = None
    network_idle: bool = False
    timeout_ms: int = 10_000


@dataclass
class BrowserResult:
    final_url: str
    status_code: int
    text: str
    content_type: str
    elapsed_ms: int


class BrowserPool:
    """Single Chromium process, multiple short-lived contexts.

    Browser launch is ~1-2s, so we keep one browser alive and create a new
    context per fetch. Contexts are cheap and isolate cookies/state.
    """

    def __init__(self, max_concurrent_contexts: int = 4) -> None:
        self._pw = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(max_concurrent_contexts)

    async def _ensure(self) -> Browser:
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(headless=True)
            return self._browser

    @asynccontextmanager
    async def context(self, *, storage_state: str | dict | None = None):
        browser = await self._ensure()
        async with self._sem:
            ctx = await browser.new_context(
                storage_state=storage_state,
                user_agent=_DEFAULT_UA,
                viewport={"width": 1280, "height": 800},
            )
            try:
                yield ctx
            finally:
                await ctx.close()

    async def close(self) -> None:
        async with self._lock:
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None


async def fetch(
    pool: BrowserPool,
    url: str,
    *,
    wait_for: WaitFor | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    storage_state: str | dict | None = None,
    headers: dict[str, str] | None = None,
) -> BrowserResult:
    """L2 fetch via Playwright with stealth always enabled."""
    wait_for = wait_for or WaitFor()
    started = time.monotonic()

    async with pool.context(storage_state=storage_state) as ctx:
        await _STEALTH.apply_stealth_async(ctx)
        if headers:
            await ctx.set_extra_http_headers(headers)
        page = await ctx.new_page()
        try:
            response = await page.goto(
                url,
                timeout=int(timeout * 1000),
                wait_until="domcontentloaded",
            )
            if wait_for.selector:
                try:
                    await page.wait_for_selector(
                        wait_for.selector, timeout=wait_for.timeout_ms
                    )
                except PWTimeout as e:
                    raise FetchError(
                        ErrorCode.JS_TIMEOUT,
                        f"selector {wait_for.selector!r} not found within {wait_for.timeout_ms}ms",
                    ) from e
            elif wait_for.network_idle:
                try:
                    await page.wait_for_load_state(
                        "networkidle", timeout=wait_for.timeout_ms
                    )
                except PWTimeout:
                    pass  # best-effort; SPAs often never go idle

            # Bug 8: page.content() raises if the SPA is mid-navigation.
            # One short re-settle attempt rescues most cases; if it still
            # fails the outer except maps it to SPA_NAVIGATION_LOOP.
            try:
                html = await page.content()
            except Exception as inner:
                msg = str(inner).lower()
                if "navigating" in msg and "changing the content" in msg:
                    try:
                        await page.wait_for_load_state(
                            "domcontentloaded", timeout=3000
                        )
                    except PWTimeout:
                        pass
                    html = await page.content()
                else:
                    raise
            final_url = page.url
            status = response.status if response is not None else 0
            ctype = ""
            if response is not None:
                try:
                    ctype = response.headers.get("content-type", "")
                except Exception:
                    ctype = ""
        except PWTimeout as e:
            raise FetchError(ErrorCode.TIMEOUT, str(e)) from e
        except Exception as e:
            if isinstance(e, FetchError):
                raise
            msg = str(e)
            low = msg.lower()
            # Bug 9: Playwright surfaces "Download is starting" when a URL
            # responds with Content-Disposition attachment. Map to a clear
            # error code instead of the generic HTTP_ERROR bucket.
            if "download is starting" in low:
                raise FetchError(
                    ErrorCode.UNSUPPORTED_CONTENT_TYPE,
                    "the URL triggered a file download; not an HTML page",
                ) from e
            # Bug 8: SPA mid-navigation — page.content() raises before the
            # DOM settles. The retry inside this function above usually
            # recovers; if it doesn't, surface a specific code.
            if "navigating" in low and "changing the content" in low:
                raise FetchError(
                    ErrorCode.SPA_NAVIGATION_LOOP,
                    "the page kept navigating; the SPA never settled",
                ) from e
            raise FetchError(ErrorCode.HTTP_ERROR, msg) from e
        finally:
            await page.close()

    return BrowserResult(
        final_url=final_url,
        status_code=status,
        text=html,
        content_type=ctype,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
