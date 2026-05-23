from unittest.mock import patch

import pytest

from lightcrawl import auth as auth_mod
from lightcrawl.content import visible_text_ratio
from lightcrawl.errors import ErrorCode, FetchError
from lightcrawl.fetch_http import HttpResult
from lightcrawl.router import (
    FetchRequest,
    Router,
    _looks_like_binary_url,
    _looks_like_challenge,
    _should_escalate_to_browser,
)


@pytest.fixture
def router():
    r = Router()
    yield r


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("lightcrawl.paths.ROOT", tmp_path)
    monkeypatch.setattr("lightcrawl.paths.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("lightcrawl.paths.PROFILES", tmp_path / "profiles")
    monkeypatch.setattr("lightcrawl.paths.LOGS", tmp_path / "logs")
    monkeypatch.setattr("lightcrawl.content.DUMPS", tmp_path / "dumps")
    monkeypatch.setattr("lightcrawl.auth.PROFILES", tmp_path / "profiles")
    (tmp_path / "dumps").mkdir(parents=True)
    (tmp_path / "profiles").mkdir(parents=True)


async def test_blocks_private_url(router):
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="127.0.0.1"):
        out = await router.fetch(FetchRequest(url="http://localhost/admin"))
    assert out["ok"] is False
    assert out["error_code"] == ErrorCode.URL_NOT_ALLOWED.value


async def test_login_required_when_wall_detected(router):
    html = "<html><body>Sign in to continue</body></html>"
    fake = HttpResult(
        final_url="https://example.com/x",
        status_code=200,
        text=html,
        content_type="text/html",
        elapsed_ms=10,
    )
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake):
        out = await router.fetch(FetchRequest(url="https://example.com/x"))
    assert out["ok"] is False
    assert out["error_code"] == ErrorCode.LOGIN_REQUIRED.value


async def test_profile_domain_mismatch(router, tmp_path):
    auth_mod.save_profile("twitter", {"cookies": [], "origins": []}, "x.com")
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"):
        out = await router.fetch(
            FetchRequest(url="https://other.example.com/", profile="twitter")
        )
    assert out["ok"] is False
    assert out["error_code"] == ErrorCode.PROFILE_DOMAIN_MISMATCH.value


async def test_profile_not_found(router):
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"):
        out = await router.fetch(
            FetchRequest(url="https://x.com/foo", profile="nonexistent")
        )
    assert out["ok"] is False
    assert out["error_code"] == ErrorCode.PROFILE_NOT_FOUND.value


async def test_success_returns_markdown(router):
    html = """
    <html><head><title>T</title></head><body>
      <article><h1>Hi</h1><p>body text long enough to extract properly with
      readability and then markdownify it nicely.</p></article>
    </body></html>
    """
    fake = HttpResult(
        final_url="https://example.com/",
        status_code=200,
        text=html,
        content_type="text/html",
        elapsed_ms=10,
    )
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake):
        out = await router.fetch(FetchRequest(url="https://example.com/"))
    assert out["ok"] is True
    assert out["strategy_used"] == "http"
    assert "Hi" in out["content"]
    assert out["attempts"][0]["strategy"] == "http"


# -- PR-4: CF challenge detection ---------------------------------------------


def test_looks_like_challenge_cdn_cgi_path():
    """`/cdn-cgi/challenge-platform/` is CF's own private path — assert hit."""
    html = '<html><body><script src="/cdn-cgi/challenge-platform/scripts/test.js">'
    assert _looks_like_challenge(html) is True


def test_looks_like_challenge_cf_chl_bypass():
    """cf-chl-bypass / cf_chl_opt are internal CF vars — assert hit."""
    assert _looks_like_challenge(
        '<html><body>cf-chl-bypass</body></html>'
    ) is True


def test_looks_like_challenge_so_challenge_page():
    """Stack Overflow's CF challenge page — title + 2 weak keywords."""
    html = '<html><head><title>Just a moment...</title></head><body>'
    html += 'Performing security verification. This website uses a security service.'
    html += '</body></html>'
    assert _looks_like_challenge(html) is True


def test_looks_like_challenge_single_weak_is_false_positive():
    """`<p>Some articles discuss checking your browser's User-Agent header</p>`
    must NOT fire. One weak keyword alone is not enough."""
    html = '<html><body><p>Always try checking your browser devtools.</p></body></html>'
    assert _looks_like_challenge(html) is False


def test_looks_like_challenge_empty():
    assert _looks_like_challenge("") is True
    assert _looks_like_challenge("<html></html>") is False


# -- PR-3: escalation threshold -----------------------------------------------


_SPA_SHELL_LARGE = (
    '<html><body><div id="root"></div>'
    + '<script>' + 'A' * 5000 + '</script>'
    + '</body></html>'
)


def test_should_escalate_spa_shell():
    assert _should_escalate_to_browser(200, _SPA_SHELL_LARGE) is True


def test_should_escalate_low_visible_text_ratio():
    """HTML > 2000 bytes, nearly zero visible text → escalate."""
    html = '<html><body>' + '<script>' + 'x' * 4000 + '</script>' + '</body></html>'
    assert len(html) > 2000
    assert visible_text_ratio(html) < 0.01
    assert _should_escalate_to_browser(200, html) is True


def test_should_escalate_normal_page_does_not_escalate():
    """A real article — text ratio ~10-15%, must NOT escalate."""
    html = (
        '<html><body><article><h1>Title</h1>'
        + '<p>A' + 'b' * 3000 + '</p>'
        + '</article></body></html>'
    )
    assert len(html) > 2000
    assert visible_text_ratio(html) > 0.04
    assert _should_escalate_to_browser(200, html) is False


def test_should_escalate_http_403():
    assert _should_escalate_to_browser(403, "<html></html>") is True


def test_should_escalate_nav_shell():
    """Nav-shell pages (joincare.com #39): heavy static nav, no
    semantic content tags, almost no <p> blocks. They route through
    detect_spa_shell → _should_escalate_to_browser, so the router
    flips to L2 automatically."""
    menu = "".join(
        f'<li><a href="/cat/{i}">分类 {i}</a></li>' for i in range(80)
    )
    html = (
        "<html><body>"
        f"<ul class='nav-menu'>{menu}</ul>"
        '<div class="footer">'
        '<a href="/privacy">隐私</a><a href="/terms">条款</a>'
        "</div>"
        "</body></html>"
    )
    assert len(html) > 2000
    assert _should_escalate_to_browser(200, html) is True


def test_should_escalate_http_429():
    assert _should_escalate_to_browser(429, "<html></html>") is True


def test_should_escalate_http_503():
    assert _should_escalate_to_browser(503, "<html></html>") is True


# -- v0.3 PR 2.1: FetchRequest cache fields ---------------------------------


def test_fetchrequest_cache_field_defaults_match_v02():
    """New cache fields must default to "do nothing" so v0.2 callers keep
    working byte-identically. See docs/v0.3/design.md §6."""
    req = FetchRequest(url="https://example.com/")
    assert req.max_age_ms is None
    assert req.cache_only is False
    assert req.store_in_cache is False
    assert req.no_cache is False


def test_fetchrequest_cache_fields_accept_overrides():
    req = FetchRequest(
        url="https://example.com/",
        max_age_ms=3_600_000,
        cache_only=True,
        store_in_cache=True,
        no_cache=False,
    )
    assert req.max_age_ms == 3_600_000
    assert req.cache_only is True
    assert req.store_in_cache is True


def test_errorcode_includes_new_cache_codes():
    """Locked in here so callers can stably import them before the cache
    module lands. See docs/v0.3/design.md §7."""
    assert ErrorCode.CACHE_MISS.value == "CACHE_MISS"
    assert ErrorCode.CACHE_CORRUPT.value == "CACHE_CORRUPT"
    assert ErrorCode.CACHE_FLAG_CONFLICT.value == "CACHE_FLAG_CONFLICT"


# -- Bug 5: IPv6 literal addresses ------------------------------------------


async def test_ipv6_literal_returns_url_not_allowed(router):
    """IPv6 loopback [::1] should get URL_NOT_ALLOWED, not DNS_FAILED."""
    out = await router.fetch(FetchRequest(url="http://[::1]:8080/admin"))
    assert out["ok"] is False
    assert out["error_code"] == ErrorCode.URL_NOT_ALLOWED.value


async def test_ipv6_link_local_returns_url_not_allowed(router):
    """IPv6 link-local [fe80::1] should also be blocked."""
    out = await router.fetch(FetchRequest(url="http://[fe80::1]/admin"))
    assert out["ok"] is False
    assert out["error_code"] == ErrorCode.URL_NOT_ALLOWED.value


# -- Bug 7: gather exception isolation --------------------------------------


async def test_gather_with_exception_isolation():
    """If one coroutine raises, return_exceptions=True + fetch_one try/except
    keeps other results alive instead of discarding everything."""
    import asyncio

    async def ok_one():
        return "https://a.test/", {"ok": True, "content": "data"}

    async def crash_one():
        raise RuntimeError("unexpected crash")

    # Simulates the fetch_one wrapper pattern added in Bug 7 fix.
    async def safe_one(url, coro):
        try:
            return await coro
        except Exception as e:
            return url, {"ok": False, "error_code": "INTERNAL_ERROR",
                         "error_detail": f"{type(e).__name__}: {e}"}

    tasks = [
        safe_one("https://a.test/", ok_one()),
        safe_one("https://b.test/", crash_one()),
        safe_one("https://c.test/", ok_one()),
    ]
    outs = await asyncio.gather(*tasks, return_exceptions=True)

    successes = sum(1 for _, fout in outs if fout.get("ok"))
    failures = sum(1 for _, fout in outs if not fout.get("ok"))
    assert successes == 2
    assert failures == 1


# -- Bug 9: PDF / binary URL early rejection --------------------------------


def test_looks_like_binary_url_pdf():
    """PR 4: .pdf is no longer in _BINARY_EXTS — PDFs are handled by fetch_pdf.
    The lookup helper must not reject them."""
    assert _looks_like_binary_url("https://arxiv.org/pdf/2301.07041.pdf") is False


def test_looks_like_binary_url_archive_and_image():
    assert _looks_like_binary_url("https://example.com/foo.zip") is True
    assert _looks_like_binary_url("https://example.com/logo.png") is True


def test_looks_like_binary_url_html_pages_pass():
    assert _looks_like_binary_url("https://example.com/article") is False
    assert _looks_like_binary_url("https://example.com/foo.html") is False


def test_looks_like_binary_url_pdf_with_signed_query_still_detected_as_pdf():
    """PR 4: .pdf with signed query is no longer rejected as binary. It is
    detected as a PDF and dispatched to fetch_pdf."""
    assert _looks_like_binary_url(
        "https://example.com/doc.pdf?Signature=abc&Expires=99"
    ) is False


def test_looks_like_binary_url_query_with_pdf_token_not_rejected():
    """Per the docstring's intent: an HTML page that mentions `.pdf` in the
    query string (path=/search) must not be misclassified as binary."""
    assert _looks_like_binary_url("https://example.com/search?q=foo.pdf") is False


# -- fetch_browser UA helper ------------------------------------------------


def test_default_user_agent_matches_host_os(monkeypatch):
    """The UA's platform token must agree with the host OS — a Linux UA on a
    macOS host (or vice versa) is itself a bot-detection signal."""
    from lightcrawl import fetch_browser

    monkeypatch.setattr(fetch_browser.platform, "system", lambda: "Linux")
    ua = fetch_browser._default_user_agent()
    assert "X11; Linux x86_64" in ua
    assert "Chrome/" in ua

    monkeypatch.setattr(fetch_browser.platform, "system", lambda: "Windows")
    ua = fetch_browser._default_user_agent()
    assert "Windows NT 10.0; Win64; x64" in ua

    monkeypatch.setattr(fetch_browser.platform, "system", lambda: "Darwin")
    ua = fetch_browser._default_user_agent()
    assert "Mac OS X" in ua


async def test_pdf_url_is_dispatched_to_fetch_pdf(router):
    """PR 4: .pdf URLs are no longer rejected — they route to fetch_pdf.
    Non-.pdf binaries (e.g. .zip) are still rejected."""
    from lightcrawl.fetch_pdf import PdfResult

    def fake_fetch_pdf(url, *, timeout, headers=None):
        return PdfResult(
            markdown="PDF content",
            num_pages=3,
            content_length=12345,
            final_url=url,
            elapsed_ms=100,
        )

    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_pdf.fetch_pdf", side_effect=fake_fetch_pdf):
        out = await router.fetch(FetchRequest(url="https://arxiv.org/pdf/2301.07041.pdf"))

    assert out["ok"] is True
    assert out["strategy_used"] == "pdf"
    assert out["content"] == "PDF content"
    assert out["metadata"]["num_pages"] == 3
    assert out["metadata"]["content_length"] == 12345
    assert out["metadata"]["content_type"] == "application/pdf"


# -- Bug 10: failure response schema parity ---------------------------------


_SUCCESS_KEYS = {
    "ok", "url", "final_url", "strategy_used", "fetched_at", "title",
    "content", "content_truncated", "dump_path", "metadata",
    "attempts", "headings",
}


async def test_failure_response_has_all_success_keys(router):
    """Every failure path must emit the same top-level keys as success paths,
    so CLI callers can do `out["metadata"]["status_code"]` unconditionally."""
    # PDF early-reject failure
    pdf = await router.fetch(FetchRequest(url="https://example.com/x.pdf"))
    # SSRF block failure
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="127.0.0.1"):
        ssrf = await router.fetch(FetchRequest(url="http://localhost/admin"))
    # Profile-not-found failure
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"):
        prof = await router.fetch(
            FetchRequest(url="https://x.com/foo", profile="nonexistent")
        )

    for out in (pdf, ssrf, prof):
        missing = _SUCCESS_KEYS - set(out.keys())
        assert not missing, f"failure response missing keys: {missing}"
        assert "status_code" in out["metadata"]
        assert "error_code" in out
        assert "error_detail" in out
        assert "suggestions" in out


# -- Bug 11: L1 retry-once on transient TimeoutError ------------------------


def _ok_html_result() -> HttpResult:
    return HttpResult(
        final_url="https://example.com/",
        status_code=200,
        text="<html><head><title>T</title></head><body><article><h1>Hi</h1>"
             "<p>body text long enough to extract properly with readability and "
             "then markdownify it nicely. Additional content here to push past "
             "the 200-byte tiny-body threshold so _should_escalate_to_browser "
             "does not fire on our test payload.</p></article></body></html>",
        content_type="text/html",
        elapsed_ms=10,
    )


async def test_l1_retries_once_on_timeout_and_succeeds(router):
    """First L1 attempt times out, second succeeds → no L2 escalation, no
    `timeout` in attempts (retry was transparent at the strategy level)."""
    call_count = {"n": 0}

    def fake_fetch(url: str, *, timeout: float, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise TimeoutError("simulated transient L1 timeout")
        return _ok_html_result()

    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", side_effect=fake_fetch):
        out = await router.fetch(FetchRequest(url="https://example.com/"))

    assert out["ok"] is True
    assert out["strategy_used"] == "http"
    assert call_count["n"] == 2  # original + 1 retry
    assert all(a["strategy"] == "http" for a in out["attempts"])


async def test_l1_retry_failure_falls_back_to_l2(router):
    """If both L1 attempts time out, escalate to browser as before."""
    call_count = {"n": 0, "browser": 0}

    def always_timeout(url: str, *, timeout: float, **_kwargs):
        call_count["n"] += 1
        raise TimeoutError("L1 always slow")

    async def fake_browser(*args, **kwargs):
        call_count["browser"] += 1
        # Force browser failure too so we don't depend on Playwright wiring
        raise FetchError(ErrorCode.TIMEOUT, "L2 also down")

    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", side_effect=always_timeout), \
         patch("lightcrawl.fetch_browser.fetch", side_effect=fake_browser):
        out = await router.fetch(FetchRequest(url="https://example.com/", timeout_ms=15000))

    assert call_count["n"] == 2  # both L1 attempts ran
    assert call_count["browser"] == 1  # then escalated
    assert out["ok"] is False
    # attempts should record both http timeout and browser
    strategies = [a["strategy"] for a in out["attempts"]]
    assert "http" in strategies and "browser" in strategies


# -- Bug 8: SPA navigation loop surfaces SPA_NAVIGATION_LOOP -----------------


async def test_spa_navigation_loop_propagates_error_code(router):
    """When fetch_browser raises SPA_NAVIGATION_LOOP, the router surfaces
    that exact code (not a generic HTTP_ERROR) plus a domain hint when one
    matches DOMAIN_HINTS (e.g. www.reddit.com → use old.reddit.com)."""

    async def fake_browser_spa_loop(*args, **kwargs):
        raise FetchError(
            ErrorCode.SPA_NAVIGATION_LOOP,
            "the page kept navigating; the SPA never settled",
        )

    # First force L1 to fail/escalate so we end up in L2
    def fake_l1(url, *, timeout, **_kwargs):
        raise TimeoutError("force escalate")

    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", side_effect=fake_l1), \
         patch("lightcrawl.fetch_browser.fetch", side_effect=fake_browser_spa_loop):
        out = await router.fetch(
            FetchRequest(url="https://www.reddit.com/r/Python/", timeout_ms=15000)
        )

    assert out["ok"] is False
    assert out["error_code"] == ErrorCode.SPA_NAVIGATION_LOOP.value
    # Reddit hint must come through suggestions
    assert any("old.reddit.com" in s for s in out["suggestions"])


async def test_spa_navigation_loop_no_hint_for_unknown_domain(router):
    """For sites without a DOMAIN_HINTS entry, the failure path still works
    but suggestions list is empty (no false hints)."""

    async def fake_browser_spa_loop(*args, **kwargs):
        raise FetchError(ErrorCode.SPA_NAVIGATION_LOOP, "spa loop")

    def fake_l1(url, *, timeout, **_kwargs):
        raise TimeoutError("force escalate")

    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", side_effect=fake_l1), \
         patch("lightcrawl.fetch_browser.fetch", side_effect=fake_browser_spa_loop):
        out = await router.fetch(
            FetchRequest(url="https://random-spa.example/", timeout_ms=15000)
        )

    assert out["ok"] is False
    assert out["error_code"] == ErrorCode.SPA_NAVIGATION_LOOP.value
    assert out["suggestions"] == []


# ---- PR 3: links/images in metadata + output formats ----------------------


_HTML_WITH_LINKS_IMAGES = (
    "<html><head><title>PR 3 Test</title></head>"
    "<body><article>"
    "<h1>Links &amp; Images</h1>"
    "<p>Text long enough to bypass the tiny-body escalation heuristic and "
    "produce stable output in tests.</p>"
    "<a href='https://example.com/about'>About</a> "
    "<a href='https://other.com/ext'>External</a>"
    "<img src='/hero.jpg' alt='Hero' width='800' height='600'>"
    "</article></body></html>"
)


async def test_metadata_includes_links_and_images(router):
    """After PR 3, metadata MUST always contain 'links' and 'images' lists.
    Even a page with no links/images gets empty lists."""
    fake = HttpResult(
        final_url="https://example.com/",
        status_code=200,
        text=_HTML_WITH_LINKS_IMAGES,
        content_type="text/html",
        elapsed_ms=5,
    )
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake):
        out = await router.fetch(FetchRequest(url="https://example.com/"))

    assert out["ok"] is True
    metadata = out["metadata"]
    assert "links" in metadata
    assert "images" in metadata
    assert isinstance(metadata["links"], list)
    assert isinstance(metadata["images"], list)
    # Verify content
    assert len(metadata["links"]) == 2
    assert metadata["links"][0]["url"] == "https://example.com/about"
    assert len(metadata["images"]) == 1
    assert metadata["images"][0]["url"] == "https://example.com/hero.jpg"


async def test_output_format_links_returns_json_array(router):
    """output_format='links' body must be a JSON array of link objects."""
    fake = HttpResult(
        final_url="https://example.com/",
        status_code=200,
        text=_HTML_WITH_LINKS_IMAGES,
        content_type="text/html",
        elapsed_ms=5,
    )
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake):
        out = await router.fetch(
            FetchRequest(url="https://example.com/", output_format="links")
        )

    assert out["ok"] is True
    import json
    links = json.loads(out["content"])
    assert isinstance(links, list)
    assert len(links) == 2
    assert links[0]["url"] == "https://example.com/about"
    assert links[0]["rel"] == "internal"


async def test_output_format_images_returns_json_array(router):
    """output_format='images' body must be a JSON array of image objects."""
    fake = HttpResult(
        final_url="https://example.com/",
        status_code=200,
        text=_HTML_WITH_LINKS_IMAGES,
        content_type="text/html",
        elapsed_ms=5,
    )
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake):
        out = await router.fetch(
            FetchRequest(url="https://example.com/", output_format="images")
        )

    assert out["ok"] is True
    import json
    images = json.loads(out["content"])
    assert isinstance(images, list)
    assert len(images) == 1
    assert images[0]["url"] == "https://example.com/hero.jpg"
    assert images[0]["alt"] == "Hero"
    assert images[0]["width"] == 800


async def test_metadata_links_images_present_on_default_format(router):
    """Default output_format='markdown' must still carry links+images in
    metadata — PR 3 adds always-on extraction, not conditional on format."""
    fake = HttpResult(
        final_url="https://example.com/",
        status_code=200,
        text=_HTML_WITH_LINKS_IMAGES,
        content_type="text/html",
        elapsed_ms=5,
    )
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="93.184.216.34"), \
         patch("lightcrawl.fetch_http.fetch", return_value=fake):
        out = await router.fetch(FetchRequest(url="https://example.com/"))

    assert out["ok"] is True
    assert len(out["metadata"]["links"]) == 2
    assert len(out["metadata"]["images"]) == 1
    # The content is markdown, not JSON
    assert "About" in out["content"]
    assert "External" in out["content"]


async def test_failure_response_has_links_images_in_metadata(router):
    """Review fix: failure path metadata MUST include empty links/images
    lists so callers get a consistent schema across ok/error paths."""
    with patch("lightcrawl.url_safety.socket.gethostbyname", return_value="127.0.0.1"):
        out = await router.fetch(FetchRequest(url="http://localhost/admin"))

    assert out["ok"] is False
    assert out["metadata"]["links"] == []
    assert out["metadata"]["images"] == []

