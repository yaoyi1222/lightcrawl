from lxml import html as lxml_html

from lightcrawl.content import (
    Heading,
    _clean_dom,
    _dom_headings,
    _dom_to_plain_text,
    _extract_images,
    _extract_links,
    _locate_headings_in_markdown,
    _select_target,
    _suggested_selectors,
    detect_login_wall,
    detect_spa_shell,
    estimate_tokens,
    html_to_markdown,
    looks_like_nav_shell,
    maybe_dump,
    visible_text_ratio,
)


SIMPLE_HTML = """
<html><head><title>My Article</title></head>
<body>
  <nav>nav links</nav>
  <article>
    <h1>Hello World</h1>
    <p>This is the body of the article with enough text to make extraction meaningful.
       It needs more than a sentence so the test exercises real content.</p>
    <p>Second paragraph with more text so the article extraction works correctly
       and produces useful markdown output.</p>
  </article>
</body></html>
"""


def test_html_to_markdown_extracts_title_and_body():
    out = html_to_markdown(SIMPLE_HTML)
    assert out.title == "My Article"
    assert "Hello World" in out.markdown
    assert "article" in out.suggested_selectors


def test_html_to_markdown_with_selector():
    out = html_to_markdown(SIMPLE_HTML, selector="article")
    assert "Hello World" in out.markdown
    assert "nav links" not in out.markdown  # selector restricts to <article>


def test_detect_login_wall():
    assert detect_login_wall("Please log in to continue")
    assert detect_login_wall("<p>Sign in to continue</p>")
    assert not detect_login_wall("<p>Welcome home</p>")


def test_detect_spa_shell():
    assert detect_spa_shell('<html><body><div id="root"></div></body></html>')
    assert not detect_spa_shell(SIMPLE_HTML)


# ---------- looks_like_nav_shell (#39 — joincare.com pattern) ----------


def _nav_shell_html(num_links: int = 80, extra_body: str = "") -> str:
    """Synthesize a joincare-style nav-shell page: lots of menu links,
    no semantic content tags, no substantial paragraphs."""
    menu = "".join(
        f'<li><a href="/cat/{i}">分类 {i}</a></li>' for i in range(num_links)
    )
    return (
        "<html><head><title>新闻</title></head><body>"
        '<div class="header">'
        '<a href="/">首页</a><a href="/about">关于</a>'
        '<a href="/contact">联系我们</a><a href="/news">新闻</a>'
        "</div>"
        f"<ul class='nav-menu'>{menu}</ul>"
        '<div class="footer">'
        '<a href="/privacy">隐私</a><a href="/terms">条款</a>'
        "</div>"
        f"{extra_body}"
        "</body></html>"
    )


def test_looks_like_nav_shell_joincare_pattern():
    # Heavy nav, no <main>/<article>, no substantial paragraphs, link
    # text dominates. This is the joincare.com signature from #39.
    html = _nav_shell_html(num_links=80)
    assert len(html) > 2000
    assert looks_like_nav_shell(html)


def test_looks_like_nav_shell_picked_up_by_detect_spa_shell():
    # Wired through to detect_spa_shell so the existing escalation
    # path in router._should_escalate_to_browser fires automatically.
    html = _nav_shell_html(num_links=80)
    assert detect_spa_shell(html)


def test_looks_like_nav_shell_false_on_article_with_inline_links():
    # A real article that happens to contain inline links should NOT
    # be misclassified. Three paragraphs is enough to exit early.
    html = (
        "<html><body><article><h1>Title</h1>"
        + "".join(
            f"<p>This is paragraph {i} with substantial text including a "
            f'<a href="/ref{i}">reference link {i}</a> embedded inline. '
            "It must be more than thirty characters to count as substantial.</p>"
            for i in range(5)
        )
        + "</article></body></html>"
    )
    assert not looks_like_nav_shell(html)


def test_looks_like_nav_shell_false_when_main_element_present():
    # Pages with explicit semantic content containers are not nav-shells
    # even if they have heavy nav elsewhere — the <main> signal wins.
    html = (
        "<html><body>"
        + _nav_shell_html(num_links=80)[len("<html><body>") : -len("</body></html>")]
        + "<main><h1>Real article</h1><p>Body.</p></main>"
        "</body></html>"
    )
    assert not looks_like_nav_shell(html)


def test_looks_like_nav_shell_false_when_too_few_anchors():
    # A small page with only a handful of links isn't a nav-shell —
    # could just be a sparse landing page.
    html = (
        "<html><body>"
        + '<a href="/x">x</a>' * 5
        + "<div>" + "x" * 3000 + "</div>"
        + "</body></html>"
    )
    assert not looks_like_nav_shell(html)


def test_looks_like_nav_shell_false_when_link_text_minority():
    # 40 anchors but lots of non-link body text: the page legitimately
    # has content, so we don't escalate.
    html = (
        "<html><body>"
        + "".join(f'<a href="/n/{i}">n{i}</a>' for i in range(40))
        + "<div>" + ("This is some body text that is not inside a link. " * 100) + "</div>"
        + "</body></html>"
    )
    assert not looks_like_nav_shell(html)


def test_looks_like_nav_shell_false_on_short_pages():
    # Length gate: tiny pages take a different code path
    # (the existing < 200-byte escalation in the router).
    assert not looks_like_nav_shell("<html><body><a href=/>x</a></body></html>")


# -- PR #53 review regressions ----------------------------------------------


def test_looks_like_nav_shell_detects_p_wrapped_anchor_navs():
    # PR #53 review MEDIUM: nav menus rendered as
    # ``<p><a href=...>About Us — Learn more about our company history</a></p>``
    # used to clear the substantial-paragraph guard because the <a>'s
    # text was > 30 chars. The fixed check counts only non-anchor text
    # inside each <p>, so anchor-only paragraphs no longer let the
    # whole page slip past detection.
    menu_p = "".join(
        f'<p><a href="/about-{i}">About Us — Learn more about our company history {i}</a></p>'
        for i in range(40)
    )
    html = (
        "<html><body>"
        f"{menu_p}"
        '<div class="footer">'
        '<a href="/privacy">隐私</a><a href="/terms">条款</a>'
        "</div>"
        "</body></html>"
    )
    assert len(html) > 2000
    assert looks_like_nav_shell(html)


def test_looks_like_nav_shell_false_with_mostly_anchor_p_but_some_real_body():
    # Mixed: 2 anchor-only <p> (don't count) + 3 substantial body
    # paragraphs (do count). Substantial paragraphs ≥ 3 → not a nav-shell.
    html = (
        "<html><body>"
        + '<p><a href="/x">Anchor-only paragraph one</a></p>'
        + '<p><a href="/y">Anchor-only paragraph two</a></p>'
        + "".join(
            f"<p>Real body paragraph {i} with more than thirty characters "
            "outside any anchor.</p>"
            for i in range(3)
        )
        + "".join(f'<a href="/n/{i}">n{i}</a>' for i in range(30))
        + "</body></html>"
    )
    assert not looks_like_nav_shell(html)


def test_looks_like_nav_shell_ignores_head_metadata_for_density():
    # PR #53 review LOW 1: ``doc.text_content()`` previously included
    # <title>/<meta> text, inflating the denominator and dragging the
    # link/total ratio below the 60% threshold. Body-only scoping
    # restores correct detection.
    long_title = "T" * 5000  # would have dominated total_text under the old version
    menu = "".join(
        f'<li><a href="/cat/{i}">分类 {i}</a></li>' for i in range(80)
    )
    html = (
        f"<html><head><title>{long_title}</title></head><body>"
        f"<ul>{menu}</ul>"
        "</body></html>"
    )
    assert looks_like_nav_shell(html)


def test_looks_like_nav_shell_ignores_form_button_text_for_density():
    # PR #53 review LOW 2: a search form or signup widget with lots of
    # button/label text used to inflate total_text. We strip form/button/
    # select/textarea/input before measuring density.
    form_noise = (
        '<form action="/q">'
        '<label>Enter your full address including street, city, and ZIP code here</label>'
        '<input type="text" name="q">'
        '<button>Submit your search query and find results immediately</button>'
        '<select><option>Pick a category from the dropdown menu</option></select>'
        '<textarea>Additional comments and notes go in this very long textarea</textarea>'
        '</form>'
    )
    menu = "".join(
        f'<li><a href="/cat/{i}">分类 {i}</a></li>' for i in range(80)
    )
    html = (
        "<html><body>"
        f"{form_noise}"
        f"<ul>{menu}</ul>"
        "</body></html>"
    )
    assert looks_like_nav_shell(html)


def test_looks_like_nav_shell_accepts_preparsed_doc():
    # PR #53 review MEDIUM: the public API now accepts a pre-parsed doc.
    # html_to_markdown uses this to skip one lxml parse on the hot path;
    # external callers benefit similarly. Sanity-check the doc path
    # produces the same answer as the html-text path.
    html = _nav_shell_html(num_links=80)
    doc = lxml_html.fromstring(html)
    assert looks_like_nav_shell(html, doc=doc) is True
    assert looks_like_nav_shell(html, doc=doc) is looks_like_nav_shell(html)


def test_detect_spa_shell_does_not_mutate_caller_doc():
    # The nav-shell pass deepcopies the body before stripping noise tags
    # so the caller's parsed doc is untouched. Without that copy, the
    # downstream html_to_markdown pipeline would lose all the elements
    # in _NAV_SHELL_STRIP_TAGS (forms, buttons, imgs, etc.).
    html = _nav_shell_html(num_links=80, extra_body='<form><button>Click me</button></form>')
    doc = lxml_html.fromstring(html)
    before = lxml_html.tostring(doc, encoding="unicode")
    detect_spa_shell(html, doc=doc)
    after = lxml_html.tostring(doc, encoding="unicode")
    assert before == after


def test_maybe_dump_inline(tmp_path, monkeypatch):
    monkeypatch.setattr("lightcrawl.content.DUMPS", tmp_path)
    inline, truncated, dump_path = maybe_dump("https://x.test/", "small body", 100)
    assert inline == "small body"
    assert not truncated
    assert dump_path is None


def test_maybe_dump_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr("lightcrawl.content.DUMPS", tmp_path)
    big = "x" * (4 * 200)  # ~200 tokens at 4 chars/token
    inline, truncated, dump_path = maybe_dump("https://x.test/foo", big, max_inline_tokens=10)
    assert truncated
    assert dump_path is not None
    assert len(inline) < len(big)
    from pathlib import Path
    assert Path(dump_path).read_text() == big


def test_estimate_tokens():
    assert estimate_tokens("") == 1
    assert estimate_tokens("x" * 400) == 100


# ---------- _clean_dom ----------


def test_clean_dom_removes_script_style_iframe_svg():
    doc = lxml_html.fromstring("""
        <html><body>
          <script>var x = 1; // # not a heading</script>
          <style>.hidden { display: none; }</style>
          <iframe src="ad"></iframe>
          <svg><circle/></svg>
          <p>Real content</p>
        </body></html>
    """)
    _clean_dom(doc)
    serialized = lxml_html.tostring(doc, encoding="unicode")
    assert "var x = 1" not in serialized
    assert "<style" not in serialized
    assert "<iframe" not in serialized
    assert "<svg" not in serialized
    assert "Real content" in serialized


def test_clean_dom_keeps_header_and_aside():
    """Article H1 lives in <header>, sidebar facts in <aside> — must survive."""
    doc = lxml_html.fromstring("""
        <html><body>
          <article>
            <header><h1>Article Title</h1></header>
            <p>Body</p>
            <aside><h2>Related</h2></aside>
          </article>
        </body></html>
    """)
    _clean_dom(doc)
    out = lxml_html.tostring(doc, encoding="unicode")
    assert "Article Title" in out
    assert "Related" in out


def test_clean_dom_removes_aria_hidden_and_display_none():
    doc = lxml_html.fromstring("""
        <html><body>
          <div aria-hidden="true">Decorative</div>
          <div style="display:none">Hidden by inline style</div>
          <div style="display: none;">Also hidden</div>
          <p>Visible</p>
        </body></html>
    """)
    _clean_dom(doc)
    out = lxml_html.tostring(doc, encoding="unicode")
    assert "Decorative" not in out
    assert "Hidden by inline style" not in out
    assert "Also hidden" not in out
    assert "Visible" in out


def test_clean_dom_removes_html_comments():
    doc = lxml_html.fromstring(
        "<html><body><!-- secret comment --><p>visible</p></body></html>"
    )
    _clean_dom(doc)
    out = lxml_html.tostring(doc, encoding="unicode")
    assert "secret comment" not in out
    assert "visible" in out


def test_clean_dom_removes_processing_instructions():
    """Closes #9. `_dom_to_plain_text` defensively skips non-element nodes
    (`isinstance(el.tag, str)`), which silently drops processing-instruction
    content instead of cleaning it up. Strip PIs in `_clean_dom` so the
    upstream invariant (only element nodes remain) actually holds — keeping
    the downstream defensive check honest rather than load-bearing.

    Note: lxml's HTML parser coerces `<?php ...?>` literals into HTML
    comments, so we have to *construct* a real PI node via `etree`
    to exercise the new branch (XML-flavored HTML / XHTML / SVG inlined
    in HTML can all surface PIs at runtime)."""
    from lxml import etree
    doc = lxml_html.fromstring(
        "<html><body><p>visible</p></body></html>"
    )
    pi = etree.ProcessingInstruction("xml-stylesheet", 'href="leak.css"')
    doc.find("body").insert(0, pi)
    assert doc.xpath("//processing-instruction()")  # sanity: PI is in the tree
    _clean_dom(doc)
    assert not doc.xpath("//processing-instruction()")
    out = lxml_html.tostring(doc, encoding="unicode")
    assert "leak.css" not in out
    assert "visible" in out


# ---------- _dom_headings ----------


def test_dom_headings_document_order():
    doc = lxml_html.fromstring("""
        <html><body>
          <h1>One</h1>
          <section>
            <h2>Two</h2>
            <article><h3>Three</h3></article>
          </section>
          <h2>Four</h2>
        </body></html>
    """)
    assert _dom_headings(doc) == [
        (1, "One"), (2, "Two"), (3, "Three"), (2, "Four"),
    ]


def test_dom_headings_skips_empty():
    doc = lxml_html.fromstring("<html><body><h1></h1><h2>Real</h2></body></html>")
    assert _dom_headings(doc) == [(2, "Real")]


def test_dom_headings_handles_inline_children():
    doc = lxml_html.fromstring(
        "<html><body><h2>Section <em>with</em> <code>code</code></h2></body></html>"
    )
    assert _dom_headings(doc) == [(2, "Section with code")]


def test_dom_headings_inside_pre_code_are_not_markdown_headings():
    """A `# comment` line inside a <pre><code> block must not be promoted to
    a heading by either extraction path. With the DOM-based approach this is
    automatic: <pre><code> contains text, not <hN> elements."""
    html = """
        <html><body>
          <h1>Real Title</h1>
          <pre><code># this is a comment, not a heading
x = 1
# another comment
</code></pre>
          <h2>Real Section</h2>
        </body></html>
    """
    out = html_to_markdown(html)
    levels_texts = [(h.level, h.text) for h in out.headings]
    assert levels_texts == [(1, "Real Title"), (2, "Real Section")]


# ---------- _dom_to_plain_text ----------


def test_dom_to_plain_text_preserves_block_breaks():
    doc = lxml_html.fromstring("""
        <html><body>
          <h1>Title</h1>
          <p>First paragraph.</p>
          <p>Second paragraph.</p>
        </body></html>
    """)
    text = _dom_to_plain_text(doc)
    assert "Title" in text
    assert "First paragraph." in text
    assert "Second paragraph." in text
    # Each <p> on its own line.
    lines = text.split("\n")
    assert any(ln == "First paragraph." for ln in lines)
    assert any(ln == "Second paragraph." for ln in lines)


def test_dom_to_plain_text_inline_elements_stay_on_one_line():
    """<em>, <strong>, <a>, <code> are inline and must NOT split sentences."""
    doc = lxml_html.fromstring(
        "<p>Hello <em>world</em>, how <strong>are</strong> you?</p>"
    )
    text = _dom_to_plain_text(doc)
    assert text == "Hello world, how are you?"


def test_dom_to_plain_text_no_markdown_syntax():
    """plain_text must not contain markdown markers like #, **, [text](url)."""
    doc = lxml_html.fromstring(
        '<body><h1>Heading</h1><p>Text with <strong>bold</strong> and '
        '<a href="http://example.com">a link</a>.</p></body>'
    )
    text = _dom_to_plain_text(doc)
    assert "#" not in text
    assert "**" not in text
    assert "](http" not in text
    assert "Heading" in text
    assert "bold" in text
    assert "a link" in text


# ---------- _locate_headings_in_markdown ----------


def test_locate_headings_basic():
    md = "# Title\n\nbody\n\n## Section A\n\nmore\n\n### Sub\n\n## Section B\n"
    dom = [(1, "Title"), (2, "Section A"), (3, "Sub"), (2, "Section B")]
    assert _locate_headings_in_markdown(md, dom) == [
        Heading(level=1, text="Title", line=1),
        Heading(level=2, text="Section A", line=5),
        Heading(level=3, text="Sub", line=9),
        Heading(level=2, text="Section B", line=11),
    ]


def test_locate_headings_repeats_consume_lines_in_order():
    md = "## Foo\n\n## Foo\n"
    dom = [(2, "Foo"), (2, "Foo")]
    out = _locate_headings_in_markdown(md, dom)
    assert [h.line for h in out] == [1, 3]


def test_locate_headings_unmatched_returns_none():
    md = "# Located\n"
    dom = [(1, "Located"), (2, "Not in markdown")]
    out = _locate_headings_in_markdown(md, dom)
    assert out[0].line == 1
    assert out[1].line is None


def test_locate_headings_skips_fenced_code_blocks():
    """A '# foo' line inside a fenced block must not be treated as a heading."""
    md = "# Real\n\n```\n# fake heading inside code\n```\n\n## After\n"
    dom = [(1, "Real"), (2, "After")]
    out = _locate_headings_in_markdown(md, dom)
    assert out[0].line == 1
    assert out[1].line == 7


def test_locate_headings_handles_closing_hashes():
    md = "## Foo ##\n"
    dom = [(2, "Foo")]
    assert _locate_headings_in_markdown(md, dom)[0].line == 1


# ---------- _select_target ----------


def test_select_target_no_selector_returns_body_when_no_main_or_article():
    doc = lxml_html.fromstring("<html><body><p>x</p></body></html>")
    target = _select_target(doc, None)
    assert target.tag == "body"


def test_select_target_prefers_single_main():
    doc = lxml_html.fromstring(
        "<html><body><nav>nav</nav><main><h1>A</h1></main></body></html>"
    )
    target = _select_target(doc, None)
    assert target.tag == "main"


def test_select_target_prefers_single_article_when_no_main():
    doc = lxml_html.fromstring(
        "<html><body><nav>nav</nav><article><h1>A</h1></article></body></html>"
    )
    target = _select_target(doc, None)
    assert target.tag == "article"


def test_select_target_falls_back_to_body_when_multiple_main():
    doc = lxml_html.fromstring(
        "<html><body><main>A</main><main>B</main></body></html>"
    )
    target = _select_target(doc, None)
    assert target.tag == "body"


def test_select_target_single_match_returns_node():
    doc = lxml_html.fromstring(
        "<html><body><article><h1>A</h1></article></body></html>"
    )
    target = _select_target(doc, "article")
    assert target.tag == "article"


def test_select_target_multiple_matches_wraps_in_div():
    doc = lxml_html.fromstring(
        "<html><body><section><h1>A</h1></section>"
        "<section><h1>B</h1></section></body></html>"
    )
    target = _select_target(doc, "section")
    assert target.tag == "div"
    assert len(target.findall("section")) == 2


def test_select_target_no_match_falls_back_to_body():
    doc = lxml_html.fromstring("<html><body><p>x</p></body></html>")
    target = _select_target(doc, ".does-not-exist")
    assert target.tag == "body"


# ---------- html_to_markdown integration ----------


def test_html_to_markdown_includes_headings():
    out = html_to_markdown(SIMPLE_HTML)
    assert len(out.headings) >= 1
    assert out.headings[0].level == 1
    assert out.headings[0].text == "Hello World"
    assert out.headings[0].line is not None and out.headings[0].line >= 1


def test_html_to_markdown_strips_scripts_and_styles_from_output():
    html = """
        <html><head><title>T</title></head><body>
          <script>var secret = 'should not appear';</script>
          <style>.foo { color: red; }</style>
          <article><h1>Visible</h1><p>Body</p></article>
        </body></html>
    """
    out = html_to_markdown(html)
    assert "secret" not in out.markdown
    assert "color: red" not in out.markdown
    assert "Visible" in out.markdown


def test_html_to_markdown_title_falls_back_to_h1():
    html = "<html><body><h1>Implied Title</h1><p>body</p></body></html>"
    out = html_to_markdown(html)
    assert out.title == "Implied Title"


def test_html_to_markdown_empty_input():
    out = html_to_markdown("")
    assert out.title == ""
    assert out.markdown == ""
    assert out.plain_text == ""
    assert out.headings == []


def test_html_to_markdown_plain_text_no_markdown_residue():
    html = """
        <html><body><article>
          <h1>Title</h1>
          <p>Text with <strong>bold</strong> and <a href="http://e.com">link</a>.</p>
        </article></body></html>
    """
    out = html_to_markdown(html)
    assert "**" not in out.plain_text
    assert "](http" not in out.plain_text
    assert "Title" in out.plain_text
    assert "bold" in out.plain_text


# ---------- _suggested_selectors (domain table) ----------


def test_suggested_selectors_wikipedia_host_in_table():
    """wikipedia.org → #mw-content-text first, then generics."""
    doc = lxml_html.fromstring(
        '<html><body><main id="content"><div id="mw-content-text">'
        "<h1>A</h1></div></main></body></html>"
    )
    sel, hint = _suggested_selectors(doc, "https://en.wikipedia.org/wiki/Foo")
    assert sel[0] == "#mw-content-text"
    assert "main" in sel
    assert hint is None


def test_suggested_selectors_github_in_table():
    doc = lxml_html.fromstring(
        "<html><body><article class='markdown-body'>"
        "<h1>README</h1></article></body></html>"
    )
    sel, hint = _suggested_selectors(
        doc, "https://github.com/anthropics/anthropic-sdk-python"
    )
    assert sel[0] == "article.markdown-body, .repository-content"


def test_suggested_selectors_unknown_domain_falls_back_to_generics():
    doc = lxml_html.fromstring(
        "<html><body><article><h1>Plain article</h1></article></body></html>"
    )
    sel, hint = _suggested_selectors(doc, "https://some-random-site.example/path")
    assert sel[0] == "article"
    assert hint is None


def test_suggested_selectors_no_url_falls_back_to_generics():
    doc = lxml_html.fromstring(
        "<html><body><article><h1>A</h1></article></body></html>"
    )
    sel, hint = _suggested_selectors(doc, None)
    assert "article" in sel
    assert hint is None


def test_suggested_selectors_x_com_returns_hint():
    doc = lxml_html.fromstring(
        '<html><body><div id="react-root"><div>Loading</div></div></body></html>'
    )
    sel, hint = _suggested_selectors(doc, "https://x.com/AnthropicAI")
    assert "lightcrawl auth login" in (hint or "")
    assert sel == []  # x.com has None in DOMAIN_SELECTORS, no matching selector


def test_suggested_selectors_www_reddit_returns_hint():
    doc = lxml_html.fromstring("<html><body><main><div></div></main></body></html>")
    sel, hint = _suggested_selectors(doc, "https://www.reddit.com/r/MachineLearning/")
    assert "old.reddit.com" in (hint or "")


def test_suggested_selectors_domain_selector_not_present_skipped():
    """If '#mw-content-text' is NOT in this particular Wikipedia page
    (unlikely but possible if page structure changes), skip it and keep
    generics. The hint should still be None because it returns the hint
    for the host anyway."""
    doc = lxml_html.fromstring("<html><body><main>A</main></body></html>")
    sel, hint = _suggested_selectors(doc, "https://en.wikipedia.org/wiki/Foo")
    # Domain selector doesn't match, so we fall back to generics.
    assert sel == ["main"]
    assert hint is None


# ---------- visible_text_ratio ----------


def test_visible_text_ratio_wiki_like():
    """A typical article page: text ~5-15% of HTML."""
    html = (
        "<html><head><script>var x = 1; function foo() {}</script>"
        "<style>.a{color:red}</style></head>"
        "<body><article><h1>Title</h1><p>Paragraph one.</p>"
        "<p>Paragraph two with enough text to be meaningful.</p>"
        "</article></body></html>"
    )
    r = visible_text_ratio(html)
    assert 0.05 < r < 0.80  # script/style stripped; text dominates


def test_visible_text_ratio_spa_shell():
    """SPA shell with large inline script bundle, nearly zero visible text."""
    html = (
        "<html><body><div id='root'></div>"
        + "<script>" + "x" * 5000 + "</script>"
        + "</body></html>"
    )
    r = visible_text_ratio(html)
    assert r < 0.03


def test_visible_text_ratio_empty():
    assert visible_text_ratio("") == 0.0
    assert visible_text_ratio("<html></html>") == 0.0


# ---------- html_to_markdown integration with url parameter ----------


def test_html_to_markdown_with_url_emits_selector_hint_for_x_com():
    """When URL is an x.com page without auth, selector_hint should guide
    the agent to `lightcrawl auth login`."""
    html = (
        '<html><body><div id="react-root">'
        "<div>Please enable JavaScript</div></div></body></html>"
    )
    out = html_to_markdown(html, url="https://x.com/AnthropicAI")
    assert "lightcrawl auth login" in (out.selector_hint or "")


def test_html_to_markdown_with_url_wikipedia_selector_first():
    """Wikipedia URL should put #mw-content-text in suggested_selectors."""
    html = (
        '<html><head><title>T</title></head>'
        '<body><main id="content"><div id="mw-content-text">'
        "<h1>Article</h1><p>Text.</p></div></main></body></html>"
    )
    out = html_to_markdown(html, url="https://en.wikipedia.org/wiki/Test")
    assert out.suggested_selectors[0] == "#mw-content-text"


# ---------- Bug 4: SPA shell detection without blind spots ----------


def test_detect_spa_shell_medium_page_with_empty_next_div():
    """A ~2k HTML with <div id='__next'></div> but no <noscript>.
    Before Bug 4 fix, this was in the 1500-5000 blind spot."""
    html = (
        '<html><head><title>React App</title>'
        '<link href="styles.css" rel="stylesheet"></head>'
        '<body>' + 'x' * 1800 + '<div id="__next"></div>'
        '<script src="bundle.js"></script></body></html>'
    )
    assert len(html) > 1500
    assert detect_spa_shell(html) is True


def test_detect_spa_shell_large_empty_root_div():
    """A 5k+ HTML with an empty root div is still a shell."""
    html = (
        '<html><head><title>SPA</title></head><body>'
        + 'y' * 5000
        + '<div id="root"></div></body></html>'
    )
    assert len(html) > 5000
    assert detect_spa_shell(html) is True


def test_detect_spa_shell_normal_page_not_detected():
    """A real article with content inside <main> is not a shell."""
    html = (
        '<html><body><main><article>'
        '<h1>Title</h1><p>' + 'a' * 3000 + '</p>'
        '</article></main></body></html>'
    )
    assert detect_spa_shell(html) is False


# ---------- Bug 1+2: case-insensitive display:none and aria-hidden ----------


def test_clean_dom_handles_case_insensitive_display_none():
    """DISPLAY:NONE and Display: None should both be removed."""
    doc = lxml_html.fromstring(
        '<html><body><article><p>visible</p>'
        '<div style="DISPLAY:NONE">leak_upper</div>'
        '<div style="Display: None">leak_mixed</div>'
        '</article></body></html>'
    )
    _clean_dom(doc)
    out = lxml_html.tostring(doc, encoding="unicode")
    assert "leak_upper" not in out
    assert "leak_mixed" not in out
    assert "visible" in out


def test_clean_dom_handles_case_insensitive_aria_hidden():
    """aria-hidden=TRUE and aria-hidden=True should both be removed."""
    doc = lxml_html.fromstring(
        '<html><body><article><p>visible</p>'
        '<div aria-hidden="TRUE">leak_upper</div>'
        '<div aria-hidden="True">leak_mixed</div>'
        '</article></body></html>'
    )
    _clean_dom(doc)
    out = lxml_html.tostring(doc, encoding="unicode")
    assert "leak_upper" not in out
    assert "leak_mixed" not in out
    assert "visible" in out


# ---------- Bug 3: heading line numbers with inline formatting ----------


def test_html_to_markdown_headings_with_inline_code_have_line_numbers():
    """<h2>Using <code>fetch()</code> in Python</h2> should get a line number."""
    html = (
        '<html><body><article>'
        '<h1>Plain Title</h1>'
        '<p>Line 2</p>'
        '<h2>Using <code>fetch()</code> in Python</h2>'
        '<p>Line 4</p>'
        '<h3>Important: <strong>do not</strong> delete</h3>'
        '<p>Line 6</p>'
        '<h4>Some <em>emphasized</em> text</h4>'
        '</article></body></html>'
    )
    out = html_to_markdown(html)
    headings = {(h.level, h.text): h for h in out.headings}

    # Plain title always matches
    assert headings[(1, "Plain Title")].line is not None

    # These were failing before Bug 3 fix
    assert headings[(2, "Using fetch() in Python")].line is not None
    assert headings[(3, "Important: do not delete")].line is not None
    assert headings[(4, "Some emphasized text")].line is not None


# ---- PR 3: _extract_links -------------------------------------------------


def test_extract_links_basic():
    doc = lxml_html.fromstring("""
        <html><body>
          <a href="https://example.com/page1">Page 1</a>
          <a href="/page2">Page 2</a>
        </body></html>
    """)
    links = _extract_links(doc, "https://example.com/")
    assert len(links) == 2
    assert links[0]["url"] == "https://example.com/page1"
    assert links[0]["text"] == "Page 1"
    assert links[0]["rel"] == "internal"
    assert links[1]["url"] == "https://example.com/page2"
    assert links[1]["text"] == "Page 2"


def test_extract_links_skips_empty_href():
    doc = lxml_html.fromstring(
        '<html><body><a href="">empty</a><a>no href</a>'
        '<a href="https://example.com/">real</a></body></html>'
    )
    links = _extract_links(doc, "https://example.com/")
    assert len(links) == 1
    assert links[0]["url"] == "https://example.com/"


def test_extract_links_skips_special_schemes():
    doc = lxml_html.fromstring("""
        <html><body>
          <a href="mailto:alice@example.com">email</a>
          <a href="javascript:void(0)">js</a>
          <a href="tel:+15555551234">call</a>
          <a href="sms:+15555551234">text</a>
          <a href="data:text/plain,hello">data</a>
          <a href="https://example.com/">real</a>
        </body></html>
    """)
    links = _extract_links(doc, "https://example.com/")
    assert len(links) == 1
    assert links[0]["url"] == "https://example.com/"


def test_extract_links_skips_in_page_anchors():
    doc = lxml_html.fromstring("""
        <html><body>
          <a href="#section">jump</a>
          <a href="#top">top</a>
          <a href="https://example.com/about">about</a>
        </body></html>
    """)
    links = _extract_links(doc, "https://example.com/")
    assert len(links) == 1
    assert links[0]["url"] == "https://example.com/about"


def test_extract_links_resolves_relative_urls():
    doc = lxml_html.fromstring(
        '<html><body><a href="docs/api">API Docs</a></body></html>'
    )
    links = _extract_links(doc, "https://example.com/products/")
    assert links[0]["url"] == "https://example.com/products/docs/api"


def test_extract_links_internal_vs_external():
    doc = lxml_html.fromstring("""
        <html><body>
          <a href="/about">internal</a>
          <a href="https://other.com/page">external</a>
          <a href="https://example.com/blog">also internal</a>
        </body></html>
    """)
    links = _extract_links(doc, "https://example.com/")
    assert links[0]["rel"] == "internal"
    assert links[1]["rel"] == "external"
    assert links[2]["rel"] == "internal"


def test_extract_links_no_base_url_defaults_external():
    doc = lxml_html.fromstring(
        '<html><body><a href="https://example.com/">link</a></body></html>'
    )
    links = _extract_links(doc, None)
    assert len(links) == 1
    assert links[0]["rel"] == "external"
    assert links[0]["url"] == "https://example.com/"


def test_extract_links_collapses_whitespace_in_text():
    doc = lxml_html.fromstring(
        '<html><body><a href="/p">  multi   \n  line  </a></body></html>'
    )
    links = _extract_links(doc, "https://example.com/")
    assert links[0]["text"] == "multi line"


def test_extract_links_image_only_anchor_returns_empty_text():
    """<a> wrapping only an <img> has no readable text."""
    doc = lxml_html.fromstring(
        '<html><body><a href="/"><img src="logo.png" alt="Home"></a></body></html>'
    )
    links = _extract_links(doc, "https://example.com/")
    assert len(links) == 1
    assert links[0]["text"] == ""


# ---- PR 3: _extract_images ------------------------------------------------


def test_extract_images_basic():
    doc = lxml_html.fromstring("""
        <html><body>
          <img src="photo.jpg" alt="A photo">
          <img src="/images/icon.png">
        </body></html>
    """)
    images = _extract_images(doc, "https://example.com/")
    assert len(images) == 2
    assert images[0]["url"] == "https://example.com/photo.jpg"
    assert images[0]["alt"] == "A photo"
    assert images[1]["url"] == "https://example.com/images/icon.png"
    assert images[1]["alt"] == ""


def test_extract_images_skips_empty_src():
    doc = lxml_html.fromstring(
        '<html><body><img src=""><img alt="no src"><img src="real.jpg"></body></html>'
    )
    images = _extract_images(doc, "https://example.com/")
    assert len(images) == 1
    assert images[0]["url"] == "https://example.com/real.jpg"


def test_extract_images_skips_data_uris():
    doc = lxml_html.fromstring(
        '<html><body><img src="data:image/png;base64,AAAA">'
        '<img src="https://example.com/real.png"></body></html>'
    )
    images = _extract_images(doc, "https://example.com/")
    assert len(images) == 1
    assert images[0]["url"] == "https://example.com/real.png"


def test_extract_images_includes_width_height_as_ints():
    doc = lxml_html.fromstring(
        '<html><body><img src="a.jpg" width="800" height="600"></body></html>'
    )
    images = _extract_images(doc, "https://example.com/")
    assert images[0]["width"] == 800
    assert images[0]["height"] == 600


def test_extract_images_skips_non_integer_dimensions():
    """width='50%' or height='auto' should be dropped, not emitted."""
    doc = lxml_html.fromstring(
        '<html><body><img src="a.jpg" width="50%" height="auto"></body></html>'
    )
    images = _extract_images(doc, "https://example.com/")
    assert len(images) == 1
    assert "width" not in images[0]
    assert "height" not in images[0]


def test_extract_images_no_base_url_emits_raw_src():
    doc = lxml_html.fromstring(
        '<html><body><img src="/img/photo.jpg"></body></html>'
    )
    images = _extract_images(doc, None)
    assert images[0]["url"] == "/img/photo.jpg"


# ---- PR 3: html_to_markdown integration -----------------------------------


_LINKS_IMAGES_HTML = """
<html><head><title>Test Page</title></head>
<body>
  <article>
    <h1>Links & Images</h1>
    <p>Check out <a href="https://example.com/about">About</a> and
       <a href="https://other.com/">External</a>.</p>
    <img src="/hero.jpg" alt="Hero image" width="1200" height="630">
    <a href="mailto:a@b.com">email (skipped)</a>
  </article>
</body></html>
"""


def test_html_to_markdown_populates_links():
    out = html_to_markdown(_LINKS_IMAGES_HTML, url="https://example.com/")
    assert len(out.links) == 2
    urls = {link["url"] for link in out.links}
    assert "https://example.com/about" in urls
    assert "https://other.com/" in urls
    # mailto: is skipped
    assert not any("mailto" in link["url"] for link in out.links)


def test_html_to_markdown_populates_images():
    out = html_to_markdown(_LINKS_IMAGES_HTML, url="https://example.com/")
    assert len(out.images) == 1
    assert out.images[0]["url"] == "https://example.com/hero.jpg"
    assert out.images[0]["alt"] == "Hero image"
    assert out.images[0]["width"] == 1200
    assert out.images[0]["height"] == 630


def test_html_to_markdown_links_and_images_default_to_empty_lists():
    """Empty input should still produce empty lists, not crash."""
    out = html_to_markdown("")
    assert out.links == []
    assert out.images == []
