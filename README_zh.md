<div align="center">

# Refetch

**Refetch 一键升级 Agent（Claude Code、Codex、Gemini CLI、Copilot CLI 等）的网页抓取与搜索能力。反爬、JS 渲染、登录态、多后端搜索全部内置，内容管线智能去噪，节省 30–90% 的 token 消耗。本地 CLI + 一份 skill，Agent 通过 shell 直接调用。**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-128%20passing-brightgreen.svg)](tests/)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](CONTRIBUTING.md)

[English](README.md) · [中文](README_zh.md) · [CONTRIBUTING](CONTRIBUTING.md)

</div>

---

## Refetch

Refetch 是一个本地 CLI + 一份 skill 文件，升级 Agent 的网页抓取与搜索能力。它支持：

- ✅ 反爬绕过 — 穿透 Cloudflare、TLS 指纹检测、浏览器挑战
- ✅ JavaScript 渲染 — 真实浏览器执行 JS，覆盖 React、Next.js、Vue 等 SPA
- ✅ 登录态会话 — 保存并复用登录凭据，访问登录墙后的页面
- ✅ 多后端搜索 — Brave、Serper、Tavily 自动故障转移
- ✅ 省 token 管线 — 自动定位到主内容区域，砍掉 30–90% 噪声
- ✅ 一站式搜索+阅读 — `refetch search-and-read` 一次调用完成搜索与并发抓取

---

## Claude Code 内置的 WebFetch 和 WebSearch

Claude Code 等 Agent 内置的基础 HTTP 抓取和网页搜索，能用，但遇到以下情况就静默失败：

- ❌ Cloudflare 保护的页面 — TLS 指纹不匹配，返回挑战页或空响应
- ❌ JavaScript 渲染的 SPA — React、Next.js、Vue 返回空壳 `<div id="root">`
- ❌ 登录墙后的内容 — X/Twitter、LinkedIn、私有 Wiki 只拿到登录页
- ❌ 整页 dump — 导航栏、侧边栏、footer、广告全塞进上下文，浪费 60–95% token
- ❌ 单一搜索源 — 一个后端，无限速容灾，挂了就是挂了

---

## 使用 Refetch 之后

- ✅ **什么都能抓。** Cloudflare 拦截、JS SPA、登录墙 — 三层逐步升级全部搞定
- ✅ **省 30–90% token** 内容管线自动定位 `<main>`/`<article>`，先清洗再输出。结构化标题+行号，可按章节 grep dump 文件
- ✅ **搜索+阅读一步到位** `refetch search-and-read` 搜索结果和 top N 页面全文一起返回，比手动搜索+N 次 fetch 省 ~30%+ token
- ✅ **持久化登入状态** `refetch auth login` 打开真实浏览器，手动登录，session 保存为 profile，下次 `refetch fetch <url> --profile <name>` 直接复用
- ✅ **隐私** 抓取过程均在本地完成，不过任何第三方云端

---

## 快速开始

```bash
git clone https://github.com/yaoyi1222/Refetch.git
cd refetch
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,bench]"
.venv/bin/playwright install chromium
```

```bash
# 可选：搜索后端（选一个配置即可）
export BRAVE_SEARCH_API_KEY=...
export SERPER_API_KEY=...
export TAVILY_API_KEY=...
```

### 接入 Agent

Refetch 是一个普通的本地 CLI — 每个命令在 stdout 输出一个 JSON 对象,成功 exit 0,失败 exit 1。把 skill 文件丢给 Agent,它就知道什么时候调用 CLI:

```bash
# Claude Code(项目级)
mkdir -p .claude/skills/refetch
cp skills/refetch/SKILL.md .claude/skills/refetch/SKILL.md

# Claude Code(用户级)
mkdir -p ~/.claude/skills/refetch
cp skills/refetch/SKILL.md ~/.claude/skills/refetch/SKILL.md
```

其他 Agent(Codex、Gemini、Copilot CLI)同样指向 `skills/refetch/SKILL.md` — 这是一份纯 markdown,说明 CLI 的命令、JSON 契约、错误处理规则。不需要常驻进程、不需要 MCP server、不需要 transport 配置。

```bash
# 自检
.venv/bin/refetch list-backends
.venv/bin/refetch fetch https://example.com/
```

---

## Fetch vs 内置 WebFetch

内置 `WebFetch` 返回**整个**页面——导航、侧边栏、footer、广告——并且对 Cloudflare、JS 渲染、登录墙后的内容静默失败。

每个请求按 **HTTP+ → 浏览器 → 已登录浏览器** 逐级尝试,只升级到必要的层级:

| 层级 | 技术 | 能处理什么 |
|---|---|---|
| **L1 HTTP+** | `curl_cffi` 模拟 Chrome 120 TLS 指纹 | 静态页面、大多数文档站、新闻站 |
| **L2 浏览器** | Playwright + `playwright-stealth` + Chromium | JS 渲染的 SPA(React、Next.js、Vue)、HTTP 下返回空壳的页面 |
| **L3 已登录** | Playwright 加载已保存的登录 `storage_state` | 需要登录的页面(X/Twitter、LinkedIn、内网 wiki) |

Refetch 自动逐步升级:L1 先尝试,遭遇 Cloudflare / 空 SPA 壳时升级 L2,检测到登录墙时升级 L3。

### Token 效率

Refetch 的内容管线自动定位到 `<main>`/`<article>`,剥离不可见元素,返回结构化 `headings: [{level, text, line}]`。`--selector` 参数精确锁定内容区域(如 GitHub 的 `article.markdown-body`);`--output-format text` 去掉 markdown 语法开销。

| 网站 | 内置 WebFetch | Refetch `默认` | Refetch `--selector` | Refetch `--output-format text` | 最多节省 |
|---|---|---|---|---|---|
| **Wikipedia** Python 词条 | 58,000 chars | 40,000 | 40,000 | 40,000 | **31%** |
| **GitHub** psf/requests | 17,500 chars | 8,040 | 2,069 | 1,818 | **90%** |
| **Django docs** 概览 | 22,742 chars | 14,695 | 12,867 | 10,972 | **52%** |
| **Python docs** 教程 | 15,224 chars | 22,160* | 22,160* | 18,034 | — |

\*Python docs 通过 Refetch 拿到了更多内容,是因为 Playwright 执行 JS 后加载了完整的侧边栏导航。

### 登录会话

`refetch auth login <profile> <url>` 打开**有头** Chromium 窗口让用户手动登录。工具永不接触密码。登录后,session 保存为命名 profile,绑定到登录 URL 的 eTLD+1,并可通过 `refetch fetch <url> --profile <name>` 复用。

---

## Search vs 内置 WebSearch 和 tavily-search

内置 `WebSearch` 返回短片段,没有抓取能力。`tavily-search` 速度快、有 AI 合成答案,但完全跑在 Tavily 的云端——没有 JS 渲染、没有登录态、没有后端容灾。Refetch 在本地运行,具备 JS 渲染、登录态和多后端故障转移。

### Refetch 的优势场景

| 场景 | 为什么用 Refetch |
|---|---|
| **答案在登录墙后面** | `refetch search-and-read "<query>" --profile x` — 一次调用完成搜索 + 已登录抓取 |
| **排名靠前的结果是 JS 渲染的 SPA** | `search-and-read` 自动通过 Playwright 浏览器管线渲染页面 |
| **需要跨搜索引擎的多样化来源** | 2+ 后端(Brave + Tavily),自动故障转移;Brave 的独立索引在 deep 搜索时覆盖 17 个独立域名 vs Tavily 的 10 个 |
| **页面很长 — 需要标题导航,而非全文** | 每个抓取到的页面都带结构化 `headings` + 行号;agent 按标题文本定位,按行号 grep dump 文件 |
| **一个后端被限制了** | 自动故障转移到下一个已配置的后端 |

### 直接对比:Refetch vs tavily-search

任务:"收集 Anthropic 最新的财务信息"

| 维度 | Refetch | tavily-search |
|---|---|---|
| **搜索覆盖面(域名数)** | **17** 个(deep,Brave 后端) | 10 个(advanced depth) |
| **默认 snippet 质量** | ~219 chars/条 | ~148 chars/条 |
| **登录墙后的来源** | ✅ `refetch auth login` → 已登录抓取 X、LinkedIn、私仓 | ❌ |
| **JS 渲染** | ✅ Playwright 浏览器执行 JS,等待选择器 | ❌ 仅服务端内容 |
| **单次调用拿全文** | `search-and-read` 抓取 top N 页(3 页约 13k chars) | `--include-raw-content` 抓取全部(10 页约 240k chars) |
| **AI 合成答案** | ❌ | ✅ `--include-answer` 直接给答案 |
| **结构化输出** | ✅ headings + 行号 + dump_path | ❌ 原始内容块 |
| **后端冗余** | ✅ Brave + Tavily,限速时自动切换 | ❌ 单一 Tavily API |
| **数据主权** | 跑在你机器上;你的 IP,你的 cookie | 跑在 Tavily 的云端 |

**取舍**:要快速得到一个事实答案,tavily 的 `--include-answer` 更快(一次调用,2-6s,AI 合成答案)。要做需要**多样化来源**、**登录态内容**、**JS 渲染**、**或者能扛住后端故障**的研究——Refetch 是唯一能同时覆盖这四个需求的选项。

Refetch 内置的 `TavilyBackend` 只用 Tavily 的**搜索排名**能力(`include_raw_content=false`)——抓取始终在你本地机器。如果还需要 `tavily-extract` / `tavily-crawl` / `tavily-map`,同时安装 `tavily-mcp` 即可;它们**互补,不冲突**。

## 命令清单

每条命令都向 stdout 输出一个 JSON 对象。exit 0 = `ok: true`,exit 1 = `ok: false`。完整 flag 见 `refetch <subcmd> --help`。

| 命令 | 用途 |
|---|---|
| `refetch fetch <url>` | 抓取 URL,自动按策略升级(L1 HTTP → L2 浏览器 → L3 已登录)。返回 markdown + headings(level/text/line)+ 推荐 selector + 超长时的 dump 路径。 |
| `refetch search <query>` | Web 搜索,返回结构化结果,含富 snippet 和每条结果的 `fetch_hint`。 |
| `refetch search-and-read <query>` | 一站式:搜索 + 并发抓取 top N。比手动分步省 ~30%+ token。 |
| `refetch list-backends` | 报告当前可用的搜索后端及配置状态。 |
| `refetch auth login <profile> <url>` | 弹出有头浏览器让用户登录某站点,保存为 profile。 |
| `refetch auth list` / `refetch auth show <profile>` | 列出已保存的 profile(只返回元信息,不返回 cookie)。 |
| `refetch auth revoke <profile>` | 删除 profile。 |

Skill 文件 [`skills/refetch/SKILL.md`](skills/refetch/SKILL.md) 是 Agent 实际读取的参考 — flag 表、决策流、错误处理、诚实契约都在里面。

## 配置

`~/.refetch/config.toml`(可选):

```toml
[ssrf]
extra_allowlist = ["internal.example.com"]   # 显式 allowlist 内网域名

[search]
default_backend = "brave"
```

环境变量:

| 变量 | 用途 |
|---|---|
| `BRAVE_SEARCH_API_KEY` | Brave 搜索(默认后端,免费 2k/月) |
| `SERPER_API_KEY` | Serper(Google SERP 代理,免费 2.5k 一次性、~$0.001/次) |
| `TAVILY_API_KEY` | Tavily(LLM 优化 snippet,免费 1k/月、~$0.008/次) |

## 搜索后端

内置三个可插拔后端。默认按 **Brave → Serper → Tavily** 顺序选第一个已配置的;可通过 `refetch search "<query>" --backend serper` 显式覆盖。

| 后端 | 强项 | 何时选 |
|---|---|---|
| **Brave** | 独立索引、免费 2k/月、无 ToS 风险 | 默认。绝大多数查询 |
| **Serper** | 纯 Google 排名,付费档最便宜 | Brave 索引找不到、或 Brave 配额用尽时 |
| **Tavily** | LLM 优化的 `content` 字段,snippet 常 200–500 字(质量最高) | 想跳过 fetch — 长 snippet 直接答 ~70% 的查询 |

加新后端约 120 行 — 参考 `src/refetch/search/backends/brave.py`。

### 与云端方案(如 `tavily-mcp`)的关系

`Refetch` 与 Tavily 官方 `tavily-mcp` **互补,不冲突** — Refetch 是本地 CLI,`tavily-mcp` 是云端 MCP server,两者可同时使用:

| | `tavily-mcp`(云端) | `Refetch`(本地 CLI) |
|---|---|---|
| 搜索排名 + LLM snippet | ✅ 业界最强之一 | ✅ 通过 `TavilyBackend`(仅 snippet 路径) |
| 登录态站点(X、私有 GH、内网 wiki) | ❌ | ✅ `refetch auth login` profile |
| JS 渲染 + 反爬 | 部分 | ✅ Playwright + stealth + `curl_cffi` |
| Cookie / IP / 浏览器主权 | 跑在 Tavily 服务器 | 跑在**你**的机器 |
| 结构化 `error_code` + `dump_path` + heading 行号 | ❌ | ✅ |

`Refetch` 内置的 `TavilyBackend` 故意只用 Tavily 的搜索路径(`include_raw_content=false`)— 抓取始终在本地,这是本地运行时的核心价值。如果还想要 `tavily-extract` / `tavily-crawl` / `tavily-map`,直接装一份 `tavily-mcp` 与本项目并存即可。

## 安全模型

- Profile 以 **0600 权限的明文 `storage_state` JSON** 存储 — 与 Playwright 官方默认一致。威胁模型是"同机其他用户"(0600 已足够),不是"以当前用户身份运行的恶意进程"(那种情况下 keyring + AES 也挡不住,加密就是安全剧场)。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 模型永远拿不到 cookie 内容 — `refetch auth show` 只返回元信息。
- `refetch auth login` 永远使用**有头**浏览器。密码和 2FA 由用户亲自输入,CLI 只在检测到登录成功后才调用 `context.storage_state()`。
- Profile 绑定到登录 URL 的 **eTLD+1**。绑定到 `x.com` 的 `twitter` profile 不能被用来抓 `attacker.com/x.com/...`。
- 所有请求经过 SSRF 防护,默认拦截 loopback、私有网段、云元数据 IP。
- 抓取到的内容被 skill 视为数据而非指令;skill 明确告知 Agent 忽略页面内的指令性文字。

## 贡献

详见 [CONTRIBUTING.md](CONTRIBUTING.md) 了解架构、开发配置、基准测试和贡献指南。

## 许可证

MIT — 见 [`LICENSE`](LICENSE)。
