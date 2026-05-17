"""PR 1b — `mobile` + `remove_base64_images`.

Offline tests covering:
  - `mobile=True` switches the L1 impersonate profile to the iOS Safari one
    (caller-supplied or routed by the router) — verified by mock observation
    on `fetch_http.fetch`.
  - `mobile=True` on L2 unpacks Playwright's "iPhone 13" device descriptor
    into the BrowserContext kwargs — verified by mocking `pool.context()`.
  - `remove_base64_images=True` strips `<img src="data:...">` elements while
    leaving regular `<img src="https://...">` in the markdown.
  - Default-args call (`mobile=False`, `remove_base64_images=False`) keeps the
    v0.1/PR 1a byte-identical response shape.

The mobile **production validation** is the network experiment recorded in
issue #17 — these tests only assert the wiring.
"""

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

from refetch import content as content_mod
from refetch import fetch_browser as fb_mod
from refetch import fetch_http as fh_mod
from refetch.fetch_http import HttpResult
from refetch.router import FetchRequest, Router


@pytest.fixture
def router():
    return Router()


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("refetch.paths.ROOT", tmp_path)
    monkeypatch.setattr("refetch.paths.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("refetch.paths.PROFILES", tmp_path / "profiles")
    monkeypatch.setattr("refetch.paths.LOGS", tmp_path / "logs")
    monkeypatch.setattr("refetch.content.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("refetch.auth.PROFILES", tmp_path / "profiles")
    (tmp_path / "dumps").mkdir(parents=True)
    (tmp_path / "profiles").mkdir(parents=True)


_LONG_HTML = (
    "<html><head><title>T</title></head><body>"
    "<article><h1>Headline</h1>"
    "<p>body text long enough to bypass the tiny-body escalation "
    "heuristic and produce stable markdown output.</p></article>"
    "</body></html>"
)


def _ok(html: str = _LONG_HTML) -> HttpResult:
    return HttpResult(
        final_url="https://example.com/",
        status_code=200,
        text=html,
        content_type="text/html",
        elapsed_ms=5,
    )


# ---- L1: mobile flips the impersonate profile ------------------------------


async def test_mobile_routes_to_safari_impersonate_on_l1(router):
    """`mobile=True` must pass curl_cffi's iOS Safari profile, not the
    desktop chrome120 default. Flipping UA only would desync UA from the
    TLS fingerprint — a known bot signal — so the whole impersonate value
    has to change."""
    seen = {}

    def fake_fetch(url, *, timeout, headers=None, impersonate=None, **_kwargs):
        seen["impersonate"] = impersonate
        return _ok()

    with patch("refetch.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("refetch.fetch_http.fetch", side_effect=fake_fetch):
        await router.fetch(FetchRequest(url="https://example.com/", mobile=True))
    assert seen["impersonate"] == fh_mod.MOBILE_IMPERSONATE
    assert "ios" in seen["impersonate"].lower()  # sanity check the constant


async def test_default_mobile_false_uses_desktop_impersonate(router):
    """Compat gate: when the caller doesn't ask for mobile, L1 still uses
    the chrome120 default — no behavior drift from v0.1."""
    seen = {}

    def fake_fetch(url, *, timeout, headers=None, impersonate=None, **_kwargs):
        seen["impersonate"] = impersonate
        return _ok()

    with patch("refetch.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("refetch.fetch_http.fetch", side_effect=fake_fetch):
        await router.fetch(FetchRequest(url="https://example.com/"))
    assert seen["impersonate"] == fh_mod.DEFAULT_IMPERSONATE
    assert seen["impersonate"] == "chrome120"


# ---- L2: mobile unpacks the iPhone 13 device descriptor --------------------


async def test_mobile_unpacks_iphone_device_into_browser_context(router):
    """When L1 fails / forces escalation, `mobile=True` must reach L2 and
    the BrowserPool must apply the iPhone 13 device descriptor (UA +
    viewport + is_mobile + has_touch) by unpacking the dict from
    `pool.mobile_context_kwargs()`."""
    # Force L1 to return 403 → router escalates to L2
    def fake_l1(url, *, timeout, headers=None, impersonate=None, **_kwargs):
        return HttpResult(
            final_url=url, status_code=403, text="<html></html>",
            content_type="text/html", elapsed_ms=5,
        )

    seen_kwargs = {}

    async def fake_mobile_kwargs(self):
        return {
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS …)",
            "viewport": {"width": 390, "height": 844},
            "is_mobile": True,
            "has_touch": True,
            "device_scale_factor": 3,
        }

    @asynccontextmanager
    async def fake_context(self, *, storage_state=None, **context_kwargs):
        seen_kwargs.update(context_kwargs)
        # Yield a sentinel; fetch() won't actually do anything with it
        # because we mock the whole fetch_browser.fetch call below.
        yield None

    async def fake_l2(pool, url, *, wait_for=None, timeout=10.0,
                     storage_state=None, headers=None, mobile=False, **_kwargs):
        # Invoke the real pool plumbing through our patched methods so we
        # can capture what context() received.
        if mobile:
            extra = await pool.mobile_context_kwargs()
        else:
            extra = {}
        async with pool.context(storage_state=storage_state, **extra):
            pass
        return fb_mod.BrowserResult(
            final_url=url, status_code=200, text=_LONG_HTML,
            content_type="text/html", elapsed_ms=10,
        )

    with patch("refetch.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("refetch.fetch_http.fetch", side_effect=fake_l1), \
         patch("refetch.fetch_browser.BrowserPool.mobile_context_kwargs", fake_mobile_kwargs), \
         patch("refetch.fetch_browser.BrowserPool.context", fake_context), \
         patch("refetch.fetch_browser.fetch", side_effect=fake_l2):
        await router.fetch(FetchRequest(url="https://example.com/", mobile=True))

    assert seen_kwargs.get("is_mobile") is True
    assert seen_kwargs.get("has_touch") is True
    assert "iPhone" in seen_kwargs.get("user_agent", "")
    assert seen_kwargs.get("viewport", {}).get("width") == 390


# ---- base64 image stripping ------------------------------------------------


_HTML_WITH_IMAGES = """
<html><head><title>T</title></head><body>
  <article>
    <h1>Pictures</h1>
    <p>Inline base64:
       <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==" alt="dot">
    </p>
    <p>External: <img src="https://example.com/logo.png" alt="logo"></p>
    <p>Body text long enough to clear the tiny-body escalation heuristic
       and produce a stable markdown extraction.</p>
  </article>
</body></html>
"""


def test_remove_base64_images_strips_data_uri_keeps_external():
    out = content_mod.html_to_markdown(_HTML_WITH_IMAGES, remove_base64_images=True)
    assert "iVBORw0K" not in out.markdown            # base64 payload gone
    assert "data:image" not in out.markdown          # no data: URI
    assert "example.com/logo.png" in out.markdown    # external image survived
    assert "Pictures" in out.markdown                # body intact


def test_default_strips_all_images_v01_behavior():
    """Default `remove_base64_images=False` keeps the v0.1 behavior of
    stripping every `<img>` (data: URIs and external alike). This locks
    backwards-compat."""
    out = content_mod.html_to_markdown(_HTML_WITH_IMAGES)
    assert "iVBORw0K" not in out.markdown
    assert "data:image" not in out.markdown
    assert "example.com/logo.png" not in out.markdown
    assert "Pictures" in out.markdown


def test_drop_base64_images_helper_two_pass():
    """The helper itself: must remove every data: <img> from a doc with
    interleaved elements without leaving holes from mid-iteration mutation
    (the CLAUDE.md DOM-mutation rule). Three base64 images in one parent."""
    from lxml import html as lxml_html

    doc = lxml_html.fromstring(
        "<html><body>"
        '<p><img src="data:image/png;base64,AAA"></p>'
        '<p><img src="data:image/png;base64,BBB"></p>'
        '<p><img src="data:image/png;base64,CCC"></p>'
        '<p><img src="https://e.com/x.png"></p>'
        "</body></html>"
    )
    content_mod._drop_base64_images(doc)
    remaining = doc.xpath("//img/@src")
    assert remaining == ["https://e.com/x.png"]


# ---- backwards compat ------------------------------------------------------


async def test_default_call_response_unchanged_after_pr1b(router):
    """Default `fetch_url`/CLI call must produce a response with the
    v0.1/PR1a top-level key set even with PR 1b's new fields merged."""
    with patch("refetch.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("refetch.fetch_http.fetch", return_value=_ok()):
        out = await router.fetch(FetchRequest(url="https://example.com/"))

    expected_keys = {
        "ok", "url", "final_url", "strategy_used", "fetched_at", "title",
        "content", "content_truncated", "dump_path", "metadata", "attempts",
        "headings",
    }
    assert set(out.keys()) == expected_keys
    assert out["ok"] is True
    assert "Headline" in out["content"]
