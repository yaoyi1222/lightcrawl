"""Diagnostic: compare four extraction pipelines on the bench URL set.

Pipelines:
  P0   raw HTML (baseline)
  P1   readability + markdownify    (status quo)
  P2   cleaned DOM (safe), return HTML
  P2b  cleaned DOM (plan.md aggressive: nav/header/footer/aside + strip class/id), HTML
  P3   cleaned DOM (safe), markdownify(body)        — main candidate
  P3b  cleaned DOM (aggressive), markdownify(body)
  P4   trafilatura

For each pipeline we record:
  - tokens (cl100k_base)
  - markdown-side heading count (regex, fence-aware)
  - script/style residue heuristic
  - sample head

DOM-side heading counts (h1..h6) are recorded once per URL for ground truth.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lightcrawl import fetch_browser, fetch_http  # noqa: E402

import tiktoken  # noqa: E402
import trafilatura  # noqa: E402
from lxml import html as lxml_html  # noqa: E402
from markdownify import markdownify  # noqa: E402
from readability import Document  # noqa: E402

ENC = tiktoken.get_encoding("cl100k_base")


def tok(s: str) -> int:
    if not s:
        return 0
    return len(ENC.encode(s, disallowed_special=()))


_REMOVE_TAGS_SAFE = {
    "script", "style", "noscript", "iframe", "svg",
    "form", "button", "input", "select", "textarea",
    "object", "embed", "canvas", "video", "audio",
    "img", "picture", "source",
}
_REMOVE_TAGS_AGGRESSIVE = _REMOVE_TAGS_SAFE | {"nav", "header", "footer", "aside"}


def _clean_dom(doc, *, aggressive: bool = False, strip_attrs: bool = False) -> None:
    tags = _REMOVE_TAGS_AGGRESSIVE if aggressive else _REMOVE_TAGS_SAFE
    xpath_expr = " | ".join(f"//{t}" for t in tags)
    for el in doc.xpath(xpath_expr):
        p = el.getparent()
        if p is not None:
            p.remove(el)
    for node in doc.xpath("//comment()"):
        p = node.getparent()
        if p is not None:
            p.remove(node)
    for el in doc.xpath('//*[@aria-hidden="true"]'):
        p = el.getparent()
        if p is not None:
            p.remove(el)
    for el in doc.xpath(
        '//*[contains(@style,"display:none") or contains(@style,"display: none")]'
    ):
        p = el.getparent()
        if p is not None:
            p.remove(el)
    if strip_attrs:
        for el in doc.iter():
            for a in ("class", "id", "style"):
                if a in el.attrib:
                    del el.attrib[a]


def _dom_headings(doc) -> dict:
    counts = {}
    for lv in range(1, 7):
        counts[f"h{lv}"] = len(doc.xpath(f"//h{lv}"))
    counts["total"] = sum(counts.values())
    return counts


def _md_headings(md: str) -> dict:
    counts = {f"h{lv}": 0 for lv in range(1, 7)}
    in_fence = False
    for line in md.split("\n"):
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            counts[f"h{len(m.group(1))}"] += 1
    counts["total"] = sum(counts.values())
    return counts


def has_script_residue(text: str) -> bool:
    return bool(
        re.search(r"\bvar\s+\w+\s*=", text)
        or re.search(r"window\.\w+\s*=", text)
        or re.search(r"\bfunction\s*\(", text)
        or re.search(r"@media[^{]*\{", text)
        or re.search(r"\.\w+\s*\{[^}]{0,200}\}", text)
    )


# ---- pipelines ----

def pipeline_raw(html: str) -> dict:
    return {"text": html, "name": "P0_raw"}


def pipeline_current(html: str) -> dict:
    try:
        readable = Document(html)
        summary = readable.summary(html_partial=True)
        md = markdownify(summary, heading_style="ATX")
    except Exception as e:
        md = f"<error: {e}>"
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return {"text": md, "name": "P1_readability_md"}


def pipeline_clean_html_safe(html: str) -> dict:
    doc = lxml_html.fromstring(html)
    _clean_dom(doc, aggressive=False)
    body = doc.find(".//body")
    if body is None:
        body = doc
    out = lxml_html.tostring(body, encoding="unicode")
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return {"text": out, "name": "P2_clean_html_safe"}


def pipeline_clean_html_aggressive(html: str) -> dict:
    doc = lxml_html.fromstring(html)
    _clean_dom(doc, aggressive=True, strip_attrs=True)
    body = doc.find(".//body")
    if body is None:
        body = doc
    out = lxml_html.tostring(body, encoding="unicode")
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return {"text": out, "name": "P2b_clean_html_aggressive"}


def pipeline_clean_md(html: str) -> dict:
    doc = lxml_html.fromstring(html)
    _clean_dom(doc, aggressive=False)
    body = doc.find(".//body")
    if body is None:
        body = doc
    body_html = lxml_html.tostring(body, encoding="unicode")
    md = markdownify(body_html, heading_style="ATX")
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return {"text": md, "name": "P3_clean_md"}


def pipeline_clean_md_aggressive(html: str) -> dict:
    doc = lxml_html.fromstring(html)
    _clean_dom(doc, aggressive=True, strip_attrs=True)
    body = doc.find(".//body")
    if body is None:
        body = doc
    body_html = lxml_html.tostring(body, encoding="unicode")
    md = markdownify(body_html, heading_style="ATX")
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return {"text": md, "name": "P3b_clean_md_aggressive"}


def pipeline_trafilatura(html: str) -> dict:
    try:
        out = trafilatura.extract(
            html,
            output_format="markdown",
            include_tables=True,
            include_links=True,
            include_formatting=True,
            favor_recall=True,
        ) or ""
    except Exception as e:
        out = f"<error: {e}>"
    return {"text": out, "name": "P4_trafilatura"}


PIPELINES = [
    pipeline_raw,
    pipeline_current,
    pipeline_clean_html_safe,
    pipeline_clean_html_aggressive,
    pipeline_clean_md,
    pipeline_clean_md_aggressive,
    pipeline_trafilatura,
]


@dataclass
class PipelineRow:
    name: str
    tokens: int
    chars: int
    headings_md_total: int
    headings_md_levels: dict
    has_script_residue: bool
    sample_head: str
    error: str | None = None


@dataclass
class UrlReport:
    url: str
    category: str
    fetch_ok: bool
    fetch_status: int | None
    raw_html_chars: int
    raw_html_tokens: int
    dom_headings: dict
    rows: list[PipelineRow] = field(default_factory=list)
    error: str | None = None
    fetch_strategy: str | None = None


def _looks_unrendered(html: str) -> bool:
    """Detect SPA shell / blocked / login wall / tiny body — anything that
    suggests we should escalate to a real browser."""
    if not html or len(html) < 500:
        return True
    lo = html.lower()
    if 'id="root"></div>' in lo or 'id="app"></div>' in lo or 'id="__next"></div>' in lo:
        return True
    if "checking your browser" in lo or "cf-mitigated" in lo:
        return True
    if "enable javascript" in lo and len(html) < 8000:
        return True
    return False


def _fetch_http_with_retry(url: str, attempts: int = 2, timeout: float = 20.0):
    last = None
    for i in range(attempts):
        try:
            return fetch_http.fetch(url, timeout=timeout)
        except Exception as e:
            last = e
            time.sleep(0.6 * (i + 1))
    import httpx
    from lightcrawl.fetch_http import HttpResult
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                                                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                 "Chrome/120.0 Safari/537.36"}) as c:
            r = c.get(url)
        return HttpResult(
            final_url=str(r.url),
            status_code=r.status_code,
            text=r.text,
            content_type=r.headers.get("content-type", ""),
            elapsed_ms=0,
        )
    except Exception:
        raise last


async def _fetch_with_browser_fallback(
    pool: fetch_browser.BrowserPool, url: str
) -> tuple[str, str, int | None]:
    """Returns (html, strategy, status). Falls back to Playwright if HTTP
    looks unrendered or blocked."""
    try:
        r = await asyncio.to_thread(_fetch_http_with_retry, url)
        if not _looks_unrendered(r.text) and r.status_code < 400:
            return r.text, "http", r.status_code
        http_html, http_status = r.text, r.status_code
    except Exception:
        http_html, http_status = "", None

    try:
        wf = fetch_browser.WaitFor(network_idle=True, timeout_ms=12_000)
        br = await asyncio.wait_for(
            fetch_browser.fetch(pool, url, wait_for=wf, timeout=30.0),
            timeout=45.0,
        )
        return br.text, "browser", br.status_code
    except Exception:
        if http_html:
            return http_html, "http_fallback", http_status
        raise


async def run_one_async(
    pool: fetch_browser.BrowserPool, url: str, category: str
) -> UrlReport:
    rep = UrlReport(
        url=url, category=category,
        fetch_ok=False, fetch_status=None,
        raw_html_chars=0, raw_html_tokens=0, dom_headings={},
    )
    try:
        html, strategy, status = await _fetch_with_browser_fallback(pool, url)
    except Exception as e:
        rep.error = f"fetch: {type(e).__name__}: {e}"
        return rep
    rep.fetch_ok = True
    rep.fetch_status = status
    rep.fetch_strategy = strategy
    rep.raw_html_chars = len(html)
    rep.raw_html_tokens = tok(html)

    try:
        doc = lxml_html.fromstring(html)
        rep.dom_headings = _dom_headings(doc)
    except Exception as e:
        rep.dom_headings = {"error": str(e)}

    for fn in PIPELINES:
        try:
            out = fn(html)
            text = out["text"]
            mdc = _md_headings(text)
            row = PipelineRow(
                name=out["name"],
                tokens=tok(text),
                chars=len(text),
                headings_md_total=mdc["total"],
                headings_md_levels=mdc,
                has_script_residue=has_script_residue(text),
                sample_head=(text[:160].replace("\n", " ") if text else ""),
            )
        except Exception as e:
            row = PipelineRow(
                name=fn.__name__, tokens=0, chars=0,
                headings_md_total=0, headings_md_levels={},
                has_script_residue=False, sample_head="",
                error=f"{type(e).__name__}: {e}",
            )
        rep.rows.append(row)
    return rep


async def _run_all(items, concurrency: int = 3) -> list[UrlReport]:
    pool = fetch_browser.BrowserPool(max_concurrent_contexts=concurrency)
    sem = asyncio.Semaphore(concurrency)
    reports: list[UrlReport] = [None] * len(items)  # type: ignore

    async def one(idx: int, it: dict):
        async with sem:
            url = it["url"]
            category = it.get("category", "?")
            print(f"[{category}] {url}", flush=True)
            t0 = time.monotonic()
            rep = await run_one_async(pool, url, category)
            dt = time.monotonic() - t0
            if rep.error:
                print(f"  ERROR [{category}] {url}: {rep.error}", flush=True)
            else:
                print(
                    f"  done [{category}] strat={rep.fetch_strategy} "
                    f"raw={rep.raw_html_tokens} tok, "
                    f"dom_h={rep.dom_headings.get('total')}, "
                    f"{dt:.1f}s",
                    flush=True,
                )
            reports[idx] = rep

    try:
        await asyncio.gather(*(one(i, it) for i, it in enumerate(items)))
    finally:
        await pool.close()
    return reports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", default="urls.toml",
                        help="TOML file with [[urls]] entries (relative to bench/)")
    parser.add_argument("--out", default="diagnostic",
                        help="Output basename (writes <out>.json/.md to bench/results/)")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()

    here = Path(__file__).parent
    urls_path = (here / args.urls) if not Path(args.urls).is_absolute() else Path(args.urls)
    cfg = tomllib.loads(urls_path.read_text())
    items = cfg["urls"]
    out_json = here / "results" / f"{args.out}.json"
    out_md = here / "results" / f"{args.out}.md"

    reports = asyncio.run(_run_all(items, concurrency=args.concurrency))

    out_json.write_text(
        json.dumps([asdict(r) for r in reports], indent=2, ensure_ascii=False)
    )

    md: list[str] = []
    md.append("# Diagnostic report")
    md.append("")
    md.append("Pipelines:")
    md.append("- P0: raw HTML (baseline)")
    md.append("- P1: readability + markdownify (current)")
    md.append("- P2: deep-clean HTML (safe tag set), return HTML")
    md.append("- P2b: deep-clean HTML aggressive (plan.md tag set + strip class/id), HTML")
    md.append("- P3: deep-clean DOM (safe), markdownify body")
    md.append("- P3b: deep-clean DOM (aggressive), markdownify body")
    md.append("- P4: trafilatura")
    md.append("")
    md.append("## Per-URL results")
    md.append("")
    md.append("| URL (cat) | strat | DOM h_total | Pipeline | Tokens | MD headings | Residue |")
    md.append("|---|---|---:|---|---:|---:|:--:|")
    for rep in reports:
        if not rep.fetch_ok:
            err = (rep.error or "")[:80].replace("|", "/")
            md.append(
                f"| {rep.url} ({rep.category}) | — | — | FETCH FAILED ({err}) | — | — | — |"
            )
            continue
        first = True
        for row in rep.rows:
            url_cell = f"{rep.url} ({rep.category})" if first else ""
            strat_cell = (rep.fetch_strategy or "?") if first else ""
            dom_cell = str(rep.dom_headings.get("total", "")) if first else ""
            first = False
            residue = "yes" if row.has_script_residue else ""
            md.append(
                f"| {url_cell} | {strat_cell} | {dom_cell} | {row.name} | "
                f"{row.tokens} | {row.headings_md_total} | {residue} |"
            )

    md.append("")
    md.append("## Aggregate (sum across successful URLs)")
    md.append("")
    md.append("| Pipeline | Σ tokens | Σ MD headings | URLs w/ residue |")
    md.append("|---|---:|---:|---:|")
    successful = [r for r in reports if r.fetch_ok]
    if successful:
        names = [row.name for row in successful[0].rows]
        for name in names:
            tot_tok, tot_h, n_res = 0, 0, 0
            for rep in successful:
                for row in rep.rows:
                    if row.name == name:
                        tot_tok += row.tokens
                        tot_h += row.headings_md_total
                        if row.has_script_residue:
                            n_res += 1
            md.append(f"| {name} | {tot_tok} | {tot_h} | {n_res} |")

    md.append("")
    md.append("## DOM heading distribution (ground truth)")
    md.append("")
    md.append("| URL | h1 | h2 | h3 | h4 | h5 | h6 | total |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for rep in reports:
        if not rep.fetch_ok or "error" in rep.dom_headings:
            continue
        d = rep.dom_headings
        md.append(
            f"| {rep.url} | {d.get('h1',0)} | {d.get('h2',0)} | "
            f"{d.get('h3',0)} | {d.get('h4',0)} | {d.get('h5',0)} | "
            f"{d.get('h6',0)} | {d.get('total',0)} |"
        )

    md.append("")
    md.append("## Sample heads (first ~160 chars)")
    md.append("")
    for rep in reports:
        if not rep.fetch_ok:
            continue
        md.append(f"### {rep.url}")
        md.append("")
        for row in rep.rows:
            md.append(f"- **{row.name}** — `{row.sample_head}`")
        md.append("")

    out_md.write_text("\n".join(md) + "\n")
    print(f"\nWrote {out_json}")
    print(f"Wrote {out_md}")


if __name__ == "__main__":
    main()
