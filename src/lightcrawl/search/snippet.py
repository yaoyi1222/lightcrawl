"""Snippet sanitation for search backends.

Several backends (Tavily in particular) return the page's first non-empty
content block as the snippet. For sites whose first block is the navigation
bar — sina.com.cn is the canonical offender (#37) — that content is markdown
image/link markup that carries no useful signal:

    [![新浪网](http://.../nav.gif)](http://www.sina.com.cn/)

Stripping that markup is preferable to surfacing it: an empty snippet is
honest about "no excerpt available", whereas raw nav markup actively misleads
agents into thinking the page is content-shaped.
"""

from __future__ import annotations

import re

# Markdown image: ![alt](url "title"?). We drop the whole thing — the alt text
# of a logo/icon is rarely informative, and inline images make snippets harder
# to scan.
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

# Markdown link: [text](url). Keep the visible text, drop the URL. This is
# nested-link safe because we first remove images (whose alt text was the
# inner [] payload), so [![...](...)](...) → [](...) → "".
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")

# HTML tags. Brave already strips <strong>, but other backends may surface
# raw <a>, <em>, <img>, etc. We strip the tag, keep the text content.
_HTML_TAG = re.compile(r"<[^>]+>")

# Whitespace collapse: any run of ASCII whitespace (including newlines) →
# single space. Run last.
_WHITESPACE = re.compile(r"\s+")


def sanitize_snippet(text: str) -> str:
    """Strip HTML and markdown image/link markup from a search snippet.

    Order matters: images first (they live inside link [] payloads), then
    links, then HTML tags, then whitespace collapse.
    """
    if not text:
        return text
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _HTML_TAG.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text
