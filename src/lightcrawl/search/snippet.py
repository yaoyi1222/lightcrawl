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

# URL inside markdown (...). Allows one level of balanced parens to handle
# real-world URLs like Wikipedia's ``Python_(programming_language)`` —
# ``[^)]*`` alone stops at the first ``)`` and produces ``Python)`` cruft.
_PARENS_URL = r"\((?:[^()]*(?:\([^()]*\))*[^()]*)\)"

# Markdown image: ![alt](url "title"?). We drop the whole thing — the alt text
# of a logo/icon is rarely informative, and inline images make snippets harder
# to scan.
_MD_IMAGE = re.compile(r"!\[[^\]]*\]" + _PARENS_URL)

# Markdown link: [text](url). Keep the visible text, drop the URL. This is
# nested-link safe because we first remove images (whose alt text was the
# inner [] payload), so [![...](...)](...) → [](...) → "".
_MD_LINK = re.compile(r"\[([^\]]*)\]" + _PARENS_URL)

# HTML comments. The original ``<[^>]+>`` regex stripped these for free;
# the tightened ``_HTML_TAG`` (next) no longer does because comments don't
# start with a letter. Cover them explicitly so backends that leak the
# raw page's comment blocks don't surface them in snippets. Non-greedy so
# adjacent comments stay distinct. (#51 follow-up)
_HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")

# Markdown autolink: ``<https://example.com>`` renders as just the URL.
# Run before ``_HTML_TAG`` so the lookahead-tightened tag regex doesn't
# need to know about autolinks at all — they're already gone by the time
# it runs. mailto: covered for completeness. (#51 follow-up)
_MD_AUTOLINK = re.compile(r"<((?:https?|mailto):[^<>\s]+)>")

# HTML tags. Brave already strips <strong>, but other backends may surface
# raw <a>, <em>, <img>, etc. We strip the tag, keep the text content.
# The lookahead ``(?=[\s/>])`` after the tag name keeps markdown autolinks
# like ``<https://example.com>`` intact — those would otherwise be eaten
# as if they were HTML tags. (#51 review)
_HTML_TAG = re.compile(r"<\/?[a-zA-Z][a-zA-Z0-9-]*(?=[\s/>])[^<>]*>")

# Whitespace collapse: any run of whitespace (incl. newlines and Unicode
# spaces like NBSP or U+3000) → single space. Run last.
_WHITESPACE = re.compile(r"\s+")


def sanitize_snippet(text: str) -> str:
    """Strip HTML and markdown image/link markup from a search snippet.

    Order matters: comments first (so an autolink-looking URL inside a
    comment stays inside the comment match and gets dropped wholesale),
    then markdown autolinks (unwrap before _HTML_TAG can see them), then
    images (their alt text lives inside link [] payloads, so they have
    to die before _MD_LINK runs), then links, then HTML tags, then
    whitespace collapse.
    """
    if not text:
        return text
    text = _HTML_COMMENT.sub("", text)
    text = _MD_AUTOLINK.sub(r"\1", text)
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _HTML_TAG.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text
