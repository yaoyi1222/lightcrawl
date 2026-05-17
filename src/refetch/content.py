from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from lxml import html as lxml_html
from markdownify import markdownify

from .paths import DUMPS
from .url_safety import etld1

_LOGIN_WALL_PATTERNS = re.compile(
    r"(sign\s*in\s+to\s+continue|please\s+log\s*in|login\s+required|"
    r"you\s+must\s+be\s+logged\s+in|create\s+an\s+account\s+to\s+continue)",
    re.IGNORECASE,
)

_SPA_SHELL_PATTERNS = re.compile(
    r'<div\s+id\s*=\s*"(root|app|__next|__nuxt)"\s*></div>',
    re.IGNORECASE,
)

CHARS_PER_TOKEN = 4  # rough estimate; good enough for budgeting

# Tags that hold no useful content for an LLM reader. Removed before any
# extraction. We deliberately keep <nav>/<header>/<footer>/<aside>: many
# sites put real headings (article H1, sidebar facts) inside them, and
# stripping them costs more in lost structure than it saves in tokens.
_REMOVE_TAGS = (
    "script", "style", "noscript", "iframe", "svg",
    "form", "button", "input", "select", "textarea",
    "object", "embed", "canvas", "video", "audio",
    "img", "picture", "source",
)
_REMOVE_XPATH = " | ".join(f"//{t}" for t in _REMOVE_TAGS)

# Block-level tags whose boundaries become line breaks in plain-text output.
_BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
    "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
    "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr",
    "ul",
})

_HEADING_LINE_RE = re.compile(r"^(#{1,6})\s+(.+?)(?:\s+#+\s*)?$")


# ---- domain-specific selector hints ----
#
# Generic candidates ("article", "main", ...) work for many pages but miss
# site-specific best selectors. This table maps known high-traffic hosts to
# the CSS selector that yields the cleanest article body. Looked up by exact
# host first, then by eTLD+1.
#
# A `None` value marks hosts where no selector helps (e.g. login walls): the
# matching `DOMAIN_HINTS` entry tells the agent what to do instead (auth or
# refetch via a different URL).
DOMAIN_SELECTORS: dict[str, str | None] = {
    # Wikipedia: skip the language list, left nav, footer.
    "wikipedia.org":             "#mw-content-text",
    # GitHub: README body in repo and blob views.
    "github.com":                "article.markdown-body, .repository-content",
    "raw.githubusercontent.com": None,                  # plain text, no DOM
    # Python / Anthropic / similar Sphinx-Mintlify-style docs.
    "docs.python.org":           "div.body",
    "docs.anthropic.com":        "main article, main",
    "anthropic.com":             "main",
    # Forums / Q&A.
    "old.reddit.com":            "#siteTable",
    "stackoverflow.com":         "#question, #answers",
    "news.ycombinator.com":      "#hnmain",
    # Blogs.
    "huggingface.co":            "article",
    "medium.com":                "article",
    "react.dev":                 "article",
    # SPA / news.
    "lite.cnn.com":              "main",
    # Hosts where any selector is futile — see DOMAIN_HINTS.
    "x.com":                     None,
    "twitter.com":               None,
    "www.reddit.com":            None,
}

DOMAIN_HINTS: dict[str, str] = {
    "x.com":          "x.com requires authentication; run `refetch auth login twitter https://x.com/login` then retry with `--profile twitter`",
    "twitter.com":    "twitter.com requires authentication; run `refetch auth login twitter https://x.com/login` then retry with `--profile twitter`",
    "www.reddit.com": "www.reddit.com is an SPA shell over HTTP; refetch via https://old.reddit.com/<same path> for server-rendered content",
}


_MISSING = object()


def _domain_lookup(host: str, table: dict):
    """Look up `host` in `table` by exact match, then by eTLD+1.
    Returns _MISSING when no entry exists (use `is _MISSING` to distinguish
    from a real `None` value, e.g. DOMAIN_SELECTORS['x.com'] == None)."""
    if not host:
        return _MISSING
    if host in table:
        return table[host]
    e1 = etld1(host)
    if e1 and e1 in table:
        return table[e1]
    return _MISSING


@dataclass
class Heading:
    level: int
    text: str
    line: int | None  # 1-based line in `markdown`; None if not located


@dataclass
class ExtractedContent:
    title: str
    markdown: str
    plain_text: str
    suggested_selectors: list[str] = field(default_factory=list)
    needs_js_hint: bool = False
    looks_like_login_wall: bool = False
    headings: list[Heading] = field(default_factory=list)
    selector_hint: str | None = None


def visible_text_ratio(html_text: str) -> float:
    """Ratio of visible text to total HTML length. SPA shells, login walls,
    and pure-JS bootstrap pages (x.com, www.reddit) have ratios < 0.01;
    normal article pages are 0.04–0.20."""
    if not html_text or len(html_text) < 100:
        return 0.0
    try:
        doc = lxml_html.fromstring(html_text)
    except Exception:
        return 1.0
    for el in doc.xpath("//script | //style | //noscript"):
        p = el.getparent()
        if p is not None:
            p.remove(el)
    txt = (doc.text_content() or "").strip()
    return len(txt) / max(1, len(html_text))


def detect_login_wall(html_text: str) -> bool:
    return bool(_LOGIN_WALL_PATTERNS.search(html_text))


def detect_spa_shell(html_text: str) -> bool:
    # Empty root/app/__next/__nuxt div → SPA mount point with no SSR
    # content. No length gate: a shell can be large due to inline JS
    # bundles, preload hints, etc. The regex only matches truly empty
    # divs (`></div>`), so SSR pages with rendered content won't match.
    if _SPA_SHELL_PATTERNS.search(html_text):
        return True
    if "<noscript>" in html_text.lower() and "javascript" in html_text.lower():
        return len(html_text) < 5000
    return False


def _drop_base64_images(doc: lxml_html.HtmlElement) -> None:
    """Remove `<img>` elements whose `src` is a `data:` URI.

    Used by `html_to_markdown(remove_base64_images=True)` so non-base64
    images survive into markdown while data-URI payloads (often hundreds
    of KB each) are dropped. Two-pass collect-then-remove because
    mutating during `doc.iter()` invalidates the iterator (see CLAUDE.md).
    """
    to_remove: list[lxml_html.HtmlElement] = []
    for el in doc.iter("img"):
        src = (el.get("src") or "").strip().lower()
        if src.startswith("data:"):
            to_remove.append(el)
    for el in to_remove:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)


def _clean_dom(
    doc: lxml_html.HtmlElement,
    *,
    extra_strip: tuple[str, ...] | list[str] = (),
    keep_images: bool = False,
) -> None:
    """Remove non-content elements from the DOM in place.

    `extra_strip` is a list of additional tag names to strip on top of the
    built-in `_REMOVE_TAGS` (script/style/iframe/...). Used by Firecrawl-style
    `exclude_tags` to let callers blacklist e.g. `<nav>`/`<aside>`/`<footer>`
    that we deliberately keep by default (see comment on `_REMOVE_TAGS`).

    `keep_images=True` skips the built-in `<img>` strip so the caller can
    selectively drop only base64-inlined ones via `_drop_base64_images()`.
    `<picture>` and `<source>` stay stripped either way — neither carries
    useful text and both clutter markdown.
    """
    base_remove = tuple(t for t in _REMOVE_TAGS if not (keep_images and t == "img"))
    remove_tags = base_remove + tuple(t.lower() for t in extra_strip)
    remove_xpath = " | ".join(f"//{t}" for t in remove_tags)
    for el in doc.xpath(remove_xpath):
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    for node in doc.xpath("//comment()"):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)

    # aria-hidden + display:none: collect then remove (modifying the tree
    # while iterating breaks the iterator). Use Python-side .lower() to
    # handle CSS value case-insensitivity — XPath contains() is case-
    # sensitive, so `DISPLAY:NONE` / `Display: None` would leak otherwise.
    to_remove: list[lxml_html.HtmlElement] = []
    for el in doc.iter():
        aria = el.get("aria-hidden")
        if aria is not None and aria.lower() == "true":
            to_remove.append(el)
            continue
        style = (el.get("style") or "").replace(" ", "").lower()
        if "display:none" in style:
            to_remove.append(el)
    for el in to_remove:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)


def _suggested_selectors(
    doc: lxml_html.HtmlElement, url: str | None = None
) -> tuple[list[str], str | None]:
    """Return (selectors, hint).

    `selectors` is an ordered list of CSS selectors that match elements in
    `doc`. A domain-specific selector from DOMAIN_SELECTORS comes first when
    the URL's host (or eTLD+1) is in the table and that selector matches at
    least one node. Generic candidates (`article`, `main`, ...) follow.

    `hint` is a free-form action string from DOMAIN_HINTS for hosts where no
    selector helps (login walls, redirect-to-old.reddit). None otherwise.
    """
    out: list[str] = []
    hint: str | None = None
    host = (urlparse(url).hostname or "") if url else ""

    domain_sel = _domain_lookup(host, DOMAIN_SELECTORS)
    if domain_sel is not _MISSING:
        if domain_sel:
            try:
                if doc.cssselect(domain_sel):
                    out.append(domain_sel)
            except Exception:
                pass
        # Even if the selector didn't match (page changed shape), surface the
        # hint so the agent isn't left wondering.
        h = _domain_lookup(host, DOMAIN_HINTS)
        if h is not _MISSING:
            hint = h  # type: ignore[assignment]

    for css in ["article", "main", "#content", "#main", ".article", ".post", ".content"]:
        if css in out:
            continue
        try:
            if doc.cssselect(css):
                out.append(css)
        except Exception:
            continue
    return out, hint


def _dom_headings(root: lxml_html.HtmlElement) -> list[tuple[int, str]]:
    """(level, text) pairs in document order, scoped to `root` and its descendants."""
    out: list[tuple[int, str]] = []
    for el in root.xpath(".//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6"):
        text = re.sub(r"\s+", " ", (el.text_content() or "").strip())
        if not text:
            continue
        out.append((int(el.tag[1]), text))
    return out


def _dom_to_plain_text(root: lxml_html.HtmlElement) -> str:
    """Extract readable plain text. Block elements introduce line breaks;
    inline elements (em/strong/a/code/span) join into the same line."""
    parts: list[str] = []

    def emit_break() -> None:
        if parts and not parts[-1].endswith("\n"):
            parts.append("\n")

    def walk(el) -> None:
        # Skip non-element nodes (comments etc. — already removed but defensive).
        if not isinstance(el.tag, str):
            return
        is_block = el.tag in _BLOCK_TAGS
        if is_block:
            emit_break()
        if el.text:
            parts.append(el.text)
        for child in el:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if is_block:
            emit_break()

    walk(root)
    text = "".join(parts)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _strip_md_formatting(text: str) -> str:
    """Remove inline markdown syntax so DOM text can match ATX heading lines.
    Emulates what `text_content()` returns — no backticks, no bold/italic
    markers, no link URLs."""
    # backtick code spans: `fetch()` → fetch()
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # bold: **do not** → do not
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    # italic: *emphasized* → emphasized
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    # links: [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _locate_headings_in_markdown(
    md: str, dom_headings: list[tuple[int, str]]
) -> list[Heading]:
    """For each (level, text) from the DOM, find the line number of the
    corresponding ATX heading in `md`. Same-text repeats consume line numbers
    in document order. line=None when the heading didn't survive markdown
    conversion (e.g. heading wrapped only an <a> with no text)."""
    if not dom_headings:
        return []
    if not md:
        return [Heading(level=lv, text=tx, line=None) for lv, tx in dom_headings]

    md_index: dict[tuple[int, str], list[int]] = {}
    in_fence = False
    for i, line in enumerate(md.split("\n"), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_LINE_RE.match(line)
        if m:
            lv = len(m.group(1))
            tx = _strip_md_formatting(m.group(2))
            if tx:
                md_index.setdefault((lv, tx), []).append(i)

    out: list[Heading] = []
    for lv, tx in dom_headings:
        key = (lv, tx)
        lines = md_index.get(key)
        line_no = lines.pop(0) if lines else None
        out.append(Heading(level=lv, text=tx, line=line_no))
    return out


def _select_target(
    doc: lxml_html.HtmlElement,
    selector: str | None,
    *,
    include_tags: tuple[str, ...] | list[str] = (),
) -> lxml_html.HtmlElement:
    """Return the subtree to convert. Selector may match 0, 1, or many nodes.
    Without a selector, prefer a single <main> or <article> over <body> —
    HTML5 marks these as dominant content, so this avoids returning page
    chrome (nav menus, language lists) that would otherwise eat the
    max_inline_tokens budget.

    `include_tags` is a Firecrawl-style positive tag allowlist (e.g.
    ['article', 'aside']). When non-empty, the auto main/article scoping is
    deliberately skipped — otherwise an `include_tags=['aside']` request would
    return nothing on pages that have a single <main> not containing the
    aside. The result is a synthetic wrapper containing every match in
    document order."""
    if selector:
        try:
            nodes = doc.cssselect(selector)
        except Exception:
            nodes = []
        if len(nodes) == 1:
            return nodes[0]
        if len(nodes) > 1:
            wrapper = lxml_html.Element("div")
            for n in nodes:
                wrapper.append(n)  # moves n; we won't reuse doc afterwards
            return wrapper

    if include_tags:
        body = doc.find(".//body")
        scope = body if body is not None else doc
        xpath = " | ".join(f".//{t.lower()}" for t in include_tags)
        try:
            nodes = scope.xpath(xpath)
        except Exception:
            nodes = []
        if nodes:
            # XPath union returns document order. lxml's Element.append()
            # *reparents* — appending a descendant after its ancestor would
            # detach the descendant from the (already moved) ancestor's
            # subtree, producing both duplicated and reordered output. So
            # when both ancestor and descendant match, keep only the
            # ancestor. Walking in document order means ancestors are seen
            # before their descendants.
            selected: list[lxml_html.HtmlElement] = []
            seen_ids: set[int] = set()
            for n in nodes:
                if any(id(a) in seen_ids for a in n.iterancestors()):
                    continue
                seen_ids.add(id(n))
                selected.append(n)
            wrapper = lxml_html.Element("div")
            for n in selected:
                wrapper.append(n)
            return wrapper
        return scope  # no matches: fall back to whole body, not auto-scope

    mains = doc.xpath("//main")
    if len(mains) == 1:
        return mains[0]
    arts = doc.xpath("//article")
    if len(arts) == 1:
        return arts[0]
    body = doc.find(".//body")
    return body if body is not None else doc


def html_to_markdown(
    html_text: str,
    *,
    selector: str | None = None,
    url: str | None = None,
    include_tags: tuple[str, ...] | list[str] = (),
    exclude_tags: tuple[str, ...] | list[str] = (),
    remove_base64_images: bool = False,
) -> ExtractedContent:
    """Extract title + main content. If selector given, restrict to that subtree.
    If url given, look up domain-specific hints (selector + actionable
    `selector_hint` for sites that need auth or a different host).

    Pipeline: parse → deep-clean DOM → markdownify subtree → derive plain_text
    and headings from the same cleaned DOM. No content extractor (readability,
    trafilatura) is used — the diagnostic in bench/results/diagnostic_extended.md
    showed they discard structure aggressively (29% heading retention vs 92%
    for this pipeline)."""
    looks_login = detect_login_wall(html_text)
    needs_js = detect_spa_shell(html_text)

    if not html_text.strip():
        return ExtractedContent(
            title="", markdown="", plain_text="",
            looks_like_login_wall=looks_login, needs_js_hint=needs_js,
        )

    try:
        doc = lxml_html.fromstring(html_text)
    except Exception:
        return ExtractedContent(
            title="", markdown=html_text, plain_text=html_text,
            looks_like_login_wall=looks_login, needs_js_hint=needs_js,
        )

    suggestions, hint = _suggested_selectors(doc, url)
    title = (doc.findtext(".//title") or "").strip()

    # When opting in to base64 stripping, drop the data-URI images first,
    # THEN clean the DOM with images preserved — net effect: non-base64
    # images survive into markdown, base64 payloads are gone.
    if remove_base64_images:
        _drop_base64_images(doc)
    _clean_dom(doc, extra_strip=exclude_tags, keep_images=remove_base64_images)

    if not title:
        h1s = doc.xpath("//h1")
        if h1s:
            title = re.sub(r"\s+", " ", (h1s[0].text_content() or "").strip())

    target = _select_target(doc, selector, include_tags=include_tags)
    target_html = lxml_html.tostring(target, encoding="unicode")
    md = markdownify(target_html, heading_style="ATX")
    md = re.sub(r"\n{3,}", "\n\n", md).strip()

    plain = _dom_to_plain_text(target)
    headings = _locate_headings_in_markdown(md, _dom_headings(target))

    return ExtractedContent(
        title=title,
        markdown=md,
        plain_text=plain,
        suggested_selectors=suggestions,
        needs_js_hint=needs_js,
        looks_like_login_wall=looks_login,
        headings=headings,
        selector_hint=hint,
    )


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def maybe_dump(url: str, content: str, max_inline_tokens: int) -> tuple[str, bool, str | None]:
    """Return (inline_content, truncated, dump_path).

    If content fits within budget, returns it unchanged. Otherwise writes the
    full content to dumps/ and returns a truncated head + the dump path.
    """
    if estimate_tokens(content) <= max_inline_tokens:
        return content, False, None

    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    dump_path = DUMPS / f"{digest}.md"
    dump_path.write_text(content, encoding="utf-8")
    head = content[: max_inline_tokens * CHARS_PER_TOKEN]
    return head, True, str(dump_path)
