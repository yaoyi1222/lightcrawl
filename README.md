<div align="center">

# Refetch

**Refetch is a drop-in upgrade for WebFetch and WebSearch in any agent (Claude Code, Codex, Gemini CLI, Copilot CLI, etc.). It adds anti-bot bypass, JS rendering, saved login sessions, and multi-backend search — plus a content pipeline that cuts 30–90% of wasted tokens — all in a single local server.**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-115%20passing-brightgreen.svg)](tests/)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](CONTRIBUTING.md)

[English](README.md) · [中文](README_zh.md) · [CONTRIBUTING](CONTRIBUTING.md)

</div>

---

## Refetch

Refetch is a local MCP server that upgrades your agent's ability to fetch and search the web. It supports:

- ✅ Anti-bot bypass — survives Cloudflare, TLS fingerprinting, and browser challenges
- ✅ JavaScript rendering — executes JS in a real browser for SPAs (React, Next.js, Vue)
- ✅ Login sessions — saves and reuses authenticated sessions for login-walled pages
- ✅ Multi-backend search — Brave, Serper, Tavily with automatic failover
- ✅ Token-saving pipeline — auto-scopes to main content, strips 30–90% of noise
- ✅ One-shot search+read — `search_and_read` finds results and fetches top pages in one call

---

## Claude Code's built-in WebFetch & WebSearch

Agents like Claude Code ship with basic HTTP fetch and web search. When they work, great. When they don't, they fail silently:

- ❌ Cloudflare-protected pages — TLS fingerprint mismatch, challenge page, or empty response
- ❌ JavaScript-rendered SPAs — React, Next.js, Vue return empty `<div id="root">` shells
- ❌ Login-walled content — X/Twitter, LinkedIn, private wikis return sign-in pages
- ❌ Full-page dump — navigation, sidebar, footer, ads all land in your context, wasting 60–95% of tokens
- ❌ Single-source search — one backend, no failover, rate-limit = dead end

---

## With Refetch

- ✅ **Fetch anything.** Cloudflare blocks, JS SPAs, login walls — three-layer escalation handles them all
- ✅ **Save 30–90% tokens.** Content pipeline auto-scopes to `<main>`/`<article>`, strips noise before it hits your context. Headings with line numbers let you grep dumps by section
- ✅ **Search + read in one call.** `search_and_read` finds results AND fetches top pages in parallel. Saves ~30%+ tokens vs manual search + N×fetch rounds
- ✅ **Login once, reuse forever.** `auth_login` opens a real browser, you log in, session is saved. `fetch_url(url, profile="x")` uses it. Password never touches the tool
- ✅ **Your machine, your data.** Your IP, your cookies, your login sessions. Nothing goes through a third-party cloud

---

## Quick start

```bash
git clone https://github.com/your-org/refetch.git
cd refetch
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,bench]"
.venv/bin/playwright install chromium
```

```bash
# Optional: search backends (pick one)
export BRAVE_SEARCH_API_KEY=...
export SERPER_API_KEY=...
export TAVILY_API_KEY=...
```

```bash
# Claude Code
claude mcp add --transport stdio refetch -- /path/to/.venv/bin/refetch-mcp

# Codex CLI
codex mcp add --transport stdio refetch -- /path/to/.venv/bin/refetch-mcp
```

---

## Fetch vs built-in WebFetch

The built-in `WebFetch` returns the **entire** page — navigation, sidebar, footer, ads — and silently fails on Cloudflare, JS rendering, or login walls.

Every request goes **HTTP+ → browser → authed browser**, escalating only as far as needed:

| Layer | Technology | What it handles |
|---|---|---|
| **L1 HTTP+** | `curl_cffi` with Chrome 120 TLS fingerprint impersonation | Static pages, most docs, news sites |
| **L2 Browser** | Playwright + `playwright-stealth` + Chromium | JS-rendered SPAs (React, Next.js, Vue), sites that return empty shells over HTTP |
| **L3 Authed** | Playwright with a saved login `storage_state` | Login-walled pages (X/Twitter, LinkedIn, internal wikis) |

Refetch auto-escalates: L1 first, then L2 on Cloudflare blocks / empty SPA shells, then L3 on login-wall detection.

### Token efficiency

Refetch's content pipeline auto-scopes to `<main>`/`<article>`, strips invisible elements, and returns structured `headings: [{level, text, line}]`. The `selector` parameter targets exact content areas (e.g. `article.markdown-body` on GitHub); `output_format=text` strips markdown syntax overhead.

| Site | Built-in WebFetch | Refetch `default` | Refetch `selector` | Refetch `output_format=text` | Best saving |
|---|---|---|---|---|---|
| **Wikipedia** Python | 58,000 chars | 40,000 | 40,000 | 40,000 | **31%** |
| **GitHub** psf/requests | 17,500 chars | 8,040 | 2,069 | 1,818 | **90%** |
| **Django docs** overview | 22,742 chars | 14,695 | 12,867 | 10,972 | **52%** |
| **Python docs** tutorial | 15,224 chars | 22,160* | 22,160* | 18,034 | — |

\*Python docs returns *more* content via Refetch because Playwright executes JS and loads the full sidebar navigation.

### Login sessions

`auth_login` opens a **headed** Chromium window for the user to log in manually. The tool never touches passwords. Once logged in, the session is saved as a named profile bound to the eTLD+1 of the login URL, and reusable via `fetch_url(url, profile=<name>)`.

---

## Search vs built-in WebSearch & tavily-search

The built-in `WebSearch` returns short snippets with no fetch capability. `tavily-search` is fast and has AI answer synthesis, but runs entirely on Tavily's cloud — no JS rendering, no login sessions, no backend fallback. Refetch runs locally with JS rendering, login sessions, and multi-backend failover.

### When Refetch helps

| Scenario | Why Refetch |
|---|---|
| **The answer is behind a login wall** | `search_and_read(query, profile="x")` — search + authed fetch in one call |
| **The top result is a JS-rendered SPA** | `search_and_read` automatically renders pages through the Playwright browser pipeline |
| **You need diverse sources across search indexes** | 2+ backends (Brave + Tavily) with automatic failover; Brave's independent index covers 17 unique domains on a deep search vs Tavily's 10 |
| **The page is huge — you want headings, not the whole thing** | Every fetched page includes structured `headings` with line numbers; the agent navigates by heading text and greps the dump file by line number |
| **One backend is rate-limited** | Automatic failover to the next configured backend — no manual intervention |

### Head-to-head: Refetch vs tavily-search

Task: "Gather the latest financial information about Anthropic"

| Dimension | Refetch | tavily-search |
|---|---|---|
| **Search depth (domains)** | **17** unique domains (deep, Brave backend) | 10 unique domains (advanced depth) |
| **Default snippet quality** | ~219 chars/result | ~148 chars/result |
| **Login-gated sources** | ✅ `auth_login` → authed fetch of X, LinkedIn, private sites | ❌ |
| **JS rendering** | ✅ Playwright browser executes JS, waits for selectors | ❌ server-side content only |
| **Raw full-content in one call** | `search_and_read` fetches top N pages (13k chars for 3 pages) | `--include-raw-content` fetches all (240k chars for 10 pages) |
| **AI answer synthesis** | ❌ | ✅ `--include-answer` gives direct answer |
| **Structured output** | ✅ headings + line numbers + dump_path | ❌ raw content blob |
| **Backend redundancy** | ✅ Brave + Tavily, auto-failover on rate-limit | ❌ single Tavily API |
| **Sovereignty** | Runs on your machine; your IP, your cookies | Runs on Tavily's cloud |

**The trade-off**: For a quick factual answer, tavily's `--include-answer` is faster (one call, 2-6s, AI-synthesized answer). For research that needs **diverse sources**, **login-gated content**, **JS rendering**, or **survives a backend outage** — Refetch is the only option that covers all four.

The built-in `TavilyBackend` inside Refetch uses Tavily for **search ranking only** (`include_raw_content=false`) — fetching always stays on your machine. If you also want `tavily-extract` / `tavily-crawl` / `tavily-map`, install `tavily-mcp` alongside this server; they're complementary, not competing.

## Tools (7)

| Tool | What it does |
|---|---|
| `fetch_url` | Fetch a URL with auto strategy escalation. Returns markdown + headings (level/text/line) + suggested selectors + dump path on overflow. |
| `search` | Web search returning structured results with rich snippets and a per-result `fetch_hint`. |
| `search_and_read` | One-shot: search + parallel-fetch top N results. Saves ~30%+ tokens vs doing it manually. |
| `list_backends` | Report which search backends are configured. |
| `auth_login` | Open a headed browser for the user to log into a site. Saves the session as a profile. |
| `auth_status` | List saved profiles (metadata only — never returns cookies). |
| `auth_revoke` | Delete a profile. |

Full input schemas in [`src/refetch/server.py`](src/refetch/server.py).

## Configuration

`~/.refetch/config.toml` (optional):

```toml
[ssrf]
extra_allowlist = ["internal.example.com"]   # explicit allowlist for private hosts

[search]
default_backend = "brave"
```

Environment variables:

| Variable | Purpose |
|---|---|
| `BRAVE_SEARCH_API_KEY` | Brave search API key (free 2k/mo). Default backend |
| `SERPER_API_KEY` | Serper (Google SERP proxy). Free 2.5k once, ~$0.001/query |
| `TAVILY_API_KEY` | Tavily (LLM-tuned snippets). Free 1k/mo, ~$0.008/query |

## Search backends

Three pluggable backends ship in-tree. The default is whichever is configured first in this order: **Brave → Serper → Tavily**. Override per-call via `search(backend="serper")`.

| Backend | Strength | When to pick |
|---|---|---|
| **Brave** | Independent index, free 2k/mo, no ToS risk | Default. Most queries. |
| **Serper** | Pure Google ranking, cheapest paid tier | When Brave's index misses something a Google user would find, or when Brave quota is exhausted |
| **Tavily** | LLM-tuned `content` field, snippets often 200–500 chars (highest quality) | When you want to skip the fetch step — long snippets answer ~70% of queries directly |

Adding a new backend is one file (~120 lines) — see `src/refetch/search/backends/brave.py` as a template.

### Where this fits vs hosted alternatives (e.g. `tavily-mcp`)

`Refetch` and Tavily's official `tavily-mcp` are **complementary, not competing** — register both and let the agent pick:

| | `tavily-mcp` (cloud) | `Refetch` (local) |
|---|---|---|
| Search ranking + LLM snippets | ✅ best-in-class | ✅ via `TavilyBackend` (snippet-only) |
| Login-walled pages (X, GitHub private, internal wikis) | ❌ | ✅ `auth_login` profiles |
| JS rendering + anti-bot | partial | ✅ Playwright + stealth + `curl_cffi` |
| Cookies / IP / browser sovereignty | runs on Tavily's servers | runs on **your** machine |
| Structured `error_code` + `dump_path` + heading line numbers | ❌ | ✅ |

`Refetch`'s built-in `TavilyBackend` deliberately uses Tavily for **search ranking only** (`include_raw_content=false`) — fetching always stays on your machine, which is the whole point of the local runtime. If you want Tavily's `tavily-extract` / `tavily-crawl` / `tavily-map` capabilities too, install `tavily-mcp` alongside this server.

## Security model

- Profiles are stored as **plaintext `storage_state` JSON with mode `0600`** — same convention Playwright uses by default. The threat model is "another local user" (where 0600 is sufficient) and not "malware running as the same user" (where keyring + AES wouldn't help anyway). See [CONTRIBUTING.md](CONTRIBUTING.md).
- The model never receives cookie contents — `auth_status` returns metadata only.
- `auth_login` always uses a **headed** browser. The user types passwords and 2FA themselves; the server only calls `context.storage_state()` after a success signal.
- Profiles are bound to the **eTLD+1** of the login URL. A `twitter` profile bound to `x.com` cannot be used to fetch `attacker.com/x.com/...`.
- All requests pass an SSRF guard that blocks loopback, private nets, and cloud metadata IPs by default.
- Fetched content is wrapped in `<fetched_content>` tags so the model treats it as data, not instructions.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture, development setup, benchmarks, and contribution guidelines.

## License

MIT — see [`LICENSE`](LICENSE).
