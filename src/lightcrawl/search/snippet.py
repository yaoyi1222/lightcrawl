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

# Mojibake recovery (#38): a GBK page served without a charset declaration
# (or with a wrong one) can be decoded as UTF-8 by upstream search
# backends, yielding snippets like ``˾ƸĻʦڣ``. The mapping is reversible:
# the original GBK bytes survive as UTF-8 code points (anywhere in
# U+0080–U+07FF depending on the GBK lead byte — ``ڣ`` in the example
# sits at U+06A3, beyond our *detection* window but still recovered),
# and re-encoding as UTF-8 then decoding as GBK recovers the Chinese
# (``˾ƸĻʦڣ`` → ``司聘幕师冢``). Four guards keep this from corrupting
# legitimate non-CJK text:
#   1. text has no valid CJK code points yet (else we'd corrupt good UTF-8)
#   2. ≥ 3 chars sit in U+0080–U+02FF — a narrow *detection* window over
#      the densest sub-range of typical GBK mojibake. We deliberately do
#      NOT widen this to the full U+0080–U+07FF mojibake landing zone:
#      that would pull in Cyrillic (U+0400–U+04FF), Greek (U+0370–U+03FF)
#      and Arabic, and the encode-utf8/decode-gbk round-trip on those
#      scripts produces garbage CJK.
#   3. encode-utf8 / decode-gbk succeeds at all
#   4. the recovered text is ≥ 75% CJK by non-whitespace char density.
#      Latin scripts with heavy diacritics — Vietnamese (62%), Polish
#      (60%), Czech (50%), Spanish — round-trip to a middling CJK
#      density because consonants stay ASCII while accented vowels
#      become CJK. Real GBK mojibake recoveries cluster at 80–100%
#      because most byte pairs map to CJK (GBK is Chinese-dense). 0.75
#      sits in the gap between the two clusters with ~7 pp of margin
#      against Vietnamese on the false-positive side and ~7 pp against
#      the noisier sina sample on the true-positive side. (PR #52 review)
_CJK_LO, _CJK_HI = 0x4E00, 0x9FFF
_SUSPECT_LO, _SUSPECT_HI = 0x0080, 0x02FF
_MOJIBAKE_MIN_SUSPECT_CHARS = 3
_RECOVERY_MIN_CJK_RATIO = 0.75


def _count_in_range(text: str, lo: int, hi: int) -> int:
    return sum(1 for c in text if lo <= ord(c) <= hi)


def recover_gbk_mojibake(text: str) -> str:
    """Best-effort recovery of GBK pages mis-decoded as UTF-8 upstream.

    Returns the original text unchanged unless all four guards trigger;
    a no-op on ASCII, valid UTF-8 Chinese, French, Spanish, Cyrillic,
    Greek, Vietnamese, Czech, Polish, etc.
    """
    if not text:
        return text
    if _count_in_range(text, _CJK_LO, _CJK_HI) > 0:
        return text
    if _count_in_range(text, _SUSPECT_LO, _SUSPECT_HI) < _MOJIBAKE_MIN_SUSPECT_CHARS:
        return text
    try:
        candidate = text.encode("utf-8").decode("gbk")
    except UnicodeDecodeError:
        return text
    cjk_count = _count_in_range(candidate, _CJK_LO, _CJK_HI)
    if cjk_count == 0:
        return text
    # Density is over the *non-whitespace* part so ASCII separators
    # (``|``, spaces) between mojibake'd runs don't pull the ratio down
    # below threshold on legitimately-recoverable snippets.
    non_ws = sum(1 for c in candidate if not c.isspace())
    if non_ws == 0 or cjk_count / non_ws < _RECOVERY_MIN_CJK_RATIO:
        return text
    return candidate


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
