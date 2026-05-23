# lightcrawl v0.3 设计文档

**主题**:Local firecrawl — Map + Crawl + Cache(完整版)。
**架构契约**:保持 v0.2 的 **CLI + Skill** 双层架构。不引入 MCP server、不引入 daemon、不引入数据库服务进程。一切落本地文件 + SQLite 索引。
**Tracker**:GitHub issue #22(milestone "v0.3")。本文档是该 tracker 的可执行细化版。
**修订**:2026-05-19 第一轮 review(`v0.3-review.md`)修订;Windows 升级为一线支持平台。

---

## 1. 目标 / 非目标

### 目标
- 把 lightcrawl 从"加强版 WebFetch"升级为"本地 firecrawl":能 `map` 一个域、`crawl` 一个站点、`batch-fetch` 一组 URL,且每次拉取都受 cache 保护。
- Crawl 必须可中断、可恢复、可取消,且在进程被 `kill -9` 之后仍能从最近 flush 点续跑。
- Cache 是其余三件套(map / crawl / batch-fetch)的**前提**,而不是优化项。Crawl 复抓同一站点必须大量命中本地缓存。
- 所有新增 CLI 子命令复用 `cli._safe_run` 错误信封,保持"每次调用一行 JSON"契约。
- **Windows / macOS / Linux 三平台一线支持**。所有持久化路径、文件名、信号处理、并发原语都以"三平台都跑过测试"为准。

### 非目标(明确推迟)
- LLM 结构化抽取(`extract` / `json` 输出)→ v0.5。
- BrowserContext 跨调用复用 → v0.6(session-interact)。
- Change tracking、webhook、proxy/TLS 旋转 → v0.7+。
- `block_ads`:需要 Playwright `page.route`,在 v0.3 末作为 stretch goal 评估,默认推迟。
- `location`(国家路由):需要代理网络,推迟到 v0.7+ 的 proxy 子项目。
- `min_age_ms`:firecrawl 的 `minAge` 语义罕用且歧义,推迟到 v0.4 再评估;v0.3 只做 `max_age_ms`。

---

## 2. 与 v0.2 架构的 diff

```
                            cli.py (argparse, 已有 7 个子命令 → 扩到 13~14 个)
                              │
            ┌─────────────────┼──────────────────────────────┐
            ▼                 ▼                              ▼
        Router (v0.2)     SearchService (v0.2)        ★ CrawlEngine (新)
            │                                               │
            │  ★ 经 Cache 透写                              │
            ▼                                               ▼
        ★ Cache (新)  ←───── 共享 ────→             ★ JobManager (新)
            │                                               │
            ▼                                               ▼
   ~/.lightcrawl/cache/             ~/.lightcrawl/jobs/<job_id>.json + .pid
        ├── index.sqlite                                    │
        ├── payloads/<sha1>.json                            ▼
        ├── dumps/<sha1>.md     (从旧 ~/.lightcrawl/dumps 迁入)
        └── screenshots/<sha1>.png  (统一入口便于 GC)
```

**Router 不动主流程**,只在入口与出口各加一层 cache 切面:
- 入口:如果 `FetchRequest.cache_only=True` 或者命中且 `max_age_ms` 内,直接返回 cache 记录,绕过 L1/L2/L3。
- L1 出口:有 cache 记录且持有 ETag/Last-Modified,带 `If-None-Match` / `If-Modified-Since` 重发;304 走 cache 返回。
- 成功回写:`store_in_cache=True` 时落盘 + 更新 index。

**CrawlEngine** 是新加的、独立于 Router 之上的编排层 —— 它**不下钻**到 fetch_http / fetch_browser,所有 fetch 都经 `Router.fetch`,从而自动享受现有 L1→L2→L3 升级和 SSRF 守卫。

---

## 3. CLI surface

### 新增子命令
| 子命令 | 用途 | 同步 / 异步 |
|---|---|---|
| `lightcrawl map <url>` | 列出域内可达 URL(sitemap 优先,homepage 兜底) | 同步 |
| `lightcrawl crawl <url>` | BFS 抓取整站或子树 | 同步默认 `--wait`,可 `--async` 后台 |
| `lightcrawl crawl-status <job_id>` | 查询任务进度 | 同步 |
| `lightcrawl crawl-cancel <job_id>` | 取消运行中的任务 | 同步 |
| `lightcrawl crawl-resume <job_id>` | 从 interrupted 状态恢复 | 同步默认 `--wait`,可 `--async` |
| `lightcrawl jobs` | 列出所有 job 状态 | 同步 |
| `lightcrawl batch-fetch ...` | 并发抓取一组已知 URL,不走 job 框架 | 同步 |
| `lightcrawl cache stats` | cache 容量 / 命中率;同时报告 legacy `~/.lightcrawl/dumps/` 占用 | 同步 |
| `lightcrawl cache clear [--older-than DUR] [--host HOST]` | 受控清理 | 同步 |

### Cache 控制标志(所有支持 cache 的子命令共用)
```
--max-age DUR       最大允许 cache 年龄,命中即返回(对应 firecrawl maxAge)
--cache-only        只读 cache,未命中直接返回 cache_miss 错误,不访问网络
--no-cache          完全跳过 cache(既不读也不写),显式覆盖默认行为
--no-store          读 cache 但不回写(一次性抓取,不污染 cache)
```
`DUR` 接受 `300ms / 5s / 10m / 2h / 7d` 这种带单位写法,解析器复用 `wait_for` 的 duration parser。`--min-age` 已从 v0.3 移除(见 §1)。

#### Cache flag 合法组合 truth table(写进 argparse 校验)

| 组合 | read | write | 网络 | 说明 |
|---|---|---|---|---|
| (无 flag) | ✗ | ✗ | ✓ | v0.2 行为,默认。`fetch` 默认。 |
| `--max-age X` | ✓(年龄约束) | ✓ | 命中跳过 | 推荐用法。 |
| `--max-age X --no-store` | ✓(年龄约束) | ✗ | 命中跳过 | 抓一次性 URL 但允许命中既有 cache。 |
| `--cache-only` | ✓(无约束) | ✗ | ✗ | 离线模式;未命中返回 `CACHE_MISS`。 |
| `--cache-only --max-age X` | ✓(年龄约束) | ✗ | ✗ | 离线 + 不要太旧的 cache。 |
| `--no-cache` | ✗ | ✗ | ✓ | 显式跳过 cache。在 `crawl` / `batch-fetch` 中**覆盖默认开启的 cache**。 |

**argparse 互斥规则**:`--no-cache` 与 `{--max-age, --cache-only, --no-store}` 任一并存 → 参数错误。所有其他组合合法。

### `crawl` 子命令完整标志
```
<seed_url>                          种子 URL,必填
--max-depth N            (default 3) BFS 最大深度
--max-pages N            (default 100) 上限;触发后退出并标记 completed
--include-paths REGEX    (repeatable) 仅访问匹配的路径
--exclude-paths REGEX    (repeatable) 跳过匹配的路径
--allow-subdomains                  允许跨子域(默认仅 host 完全相等)
--crawl-entire-domain               用 eTLD+1 替代 host 做边界
--ignore-robots-txt                 跳过 robots.txt 限制(慎用,默认遵守)
--ignore-query-parameters           URL 规范化时丢弃 query(仅影响去重 / cache key,不影响 include/exclude 匹配,见 §5.5 表)
--concurrency N          (default 4) asyncio.Semaphore 大小
--user-agent UA                     覆盖默认 UA(透传到 Router)
--output-format FMT      (default markdown) 透传到 Router
--async                              后台运行,立即返回 {job_id}
--wait                               同步运行,进度流到 stderr,终态 JSON 到 stdout(默认行为)
+ 所有 cache 控制标志(见上)。crawl 默认 `--max-age 1h` 等价于内部强制开 cache;
  用户显式 `--no-cache` 视为权威,关闭 cache。
+ 所有 fetch 透传标志(--header / --include-tag / --exclude-tag / --mobile / ...)
```

### 命名一致性规则
- 子命令小写、单词以 `-` 连接:`crawl-status`、`batch-fetch`、`cache clear`。和现存的 `search-and-read` / `list-backends` / `auth list` 一致。
- 多字标志走 `--kebab-case`,Python 层用 `dest="snake_case"`(与 v0.2 `--max-results`/`max_results` 同款)。
- 不引入 `--json` 类全局标志:stdout 永远是单 JSON,这点已是项目契约。
- **Windows 文件名兼容**:子命令绝不出现 `:` / `<` / `>` / `|` / `"` / `*` / `?`。job_id 同此约束(见 §5.4)。

---

## 4. Skill 更新点(`skills/lightcrawl/SKILL.md`)

新增 decision flow 顶部分流表(只摘骨架):

```
单 URL,已知 → fetch
一组已知 URL(< 50)→ batch-fetch
不知道 URL,需要发现 → map  → 再 batch-fetch / read top N
要抓整个文档站 → crawl --max-pages N(必填上限,防失控)
查 crawl 进度 / 续跑 / 取消 → crawl-status / -resume / -cancel
查 cache 占用 / 清理 → cache stats / cache clear
```

新增 cache 行为段:
- **`fetch` 默认不走 cache**(向后兼容 v0.2 调用语义)。Agent 需主动加 `--max-age DUR` 才会复用。
- **`search-and-read` 默认行为不变**,与 v0.2 等价(不读 cache)。如果你想让相同查询复用最近抓过的页面,在调用时显式 `--max-age DUR`。
- **`crawl` 与 `batch-fetch` 默认开启 cache**,因为它们的语义就是批量,不缓存等于浪费配额。`--no-cache` 是用户对默认的显式覆盖,agent 应当尊重。

新增 honesty contract 段(在现有 contract 之后追加 3 条):

**3. crawl 部分失败不掩盖**。job 终态 JSON 中 `results[].status` 字段必须反映每条 URL 的真实结果(`ok` / `error_code`),agent 不得把 `pages_failed > 0` 当成 success 报告给用户。

**4. `count=0` 必须解释原因**。`crawl` / `map` / `batch-fetch` 返回 `ok: true, count: 0` 是**合法响应**(robots 全拒 / include-exclude 过滤全空 / max_pages=0 / sitemap 空 …),不是 hard failure。但 agent 报告时必须说明原因(从 `progress.skipped_robots` / `progress.skipped_filter` / `notes` 字段读取),不能简单说"抓取完成"了事。

**5. `batch-fetch` 的 `ok=true` 表示"批次完成",不表示"全部 URL 抓取成功"**。即使 `results` 内每一条都是 `ok: false`,顶层 `ok` 仍然为 `true`(批次本身正常返回)。agent 在使用 `ok` 时必须同时检查 `ok_count / failed_count`。

---

## 5. 模块设计

### 5.1 `canonical.py`(新,~80 LOC)

```python
def canonicalize_url(url: str, *, ignore_query: bool = False,
                     drop_tracking: bool = True) -> str: ...
def url_hash(canonical_url: str, *, profile: str | None) -> str:
    """sha1(canonical_url + "\\0" + (profile or "")),40 hex 字符。
    profile 维度参与 hash 是 v0.3 的 cache 安全不变量,见 §5.2。"""
```

规范化步骤(顺序固定,可单元测试):
1. 解析 → `urlparse`。
2. scheme/host 小写;丢 default port(80/443)。
3. path 保留大小写,但 `""` → `"/"`,末尾 `/` 仅根保留。
4. query:按 key 升序排序;`drop_tracking=True` 时剥离 `utm_*`、`fbclid`、`gclid`、`ref` 等(白名单常量,~15 条)。
5. fragment 永远丢弃。
6. `ignore_query=True` 时完全丢 query。

**纯函数**、无副作用、表驱动测试。Cache key 与 crawl 去重共用这个函数 —— 二者必须一致,否则 cache 命中率与 crawl 完整性会错位。

**URL 形态的多用途约定**(crawl / map 内部交叉引用 §5.5):

| 用途 | 使用的 URL 形态 | 理由 |
|---|---|---|
| Cache key | `canonicalize_url(u, ignore_query=False, drop_tracking=True)` + profile | 命中率最大化,但 tracking 参数不应该影响 cache |
| Crawl 去重 (`visited` / `claimed`) | 同上 | 与 cache key 一致,避免错位 |
| `--include-paths` / `--exclude-paths` 匹配 | **原始 URL**(canonical 之前) | 用户可能想 exclude `utm_*` 之类参数,canonical 化后这些参数已被剥离 |
| robots.txt allow 判定 | **原始 URL**(canonical 之前) | robots spec 在 path+query 原文上匹配 |
| 域过滤(host / eTLD+1) | canonical 之后 | 大小写 / 默认端口归一化 |

### 5.2 `cache.py`(新,~280 LOC)

#### 存储布局
```
~/.lightcrawl/cache/
  index.sqlite                      # 元数据 + 索引,可重建
  payloads/<sha1>.json              # 单 URL 一文件,内含 markdown + headings + meta
  dumps/<sha1>.md                   # overflow dump,与 cache 同寿命(吸收旧 ~/.lightcrawl/dumps)
  screenshots/<sha1>.png            # 截图,与 cache 同寿命
```

#### `index.sqlite` 表结构
```sql
CREATE TABLE entries (
  url_hash      TEXT PRIMARY KEY,           -- sha1(canonical_url + "\0" + profile_or_empty)
  canonical_url TEXT NOT NULL,
  profile       TEXT NOT NULL DEFAULT '',   -- 与 url_hash 中的 profile 维度对齐;'' 表示无 profile
  host          TEXT NOT NULL,              -- 用于按域清理与统计
  etld1         TEXT NOT NULL,              -- tldextract 结果,用于 crawl 域过滤
  fetched_at    INTEGER NOT NULL,           -- unix ms
  accessed_at   INTEGER NOT NULL,           -- LRU
  status_code   INTEGER NOT NULL,
  etag          TEXT,
  last_modified TEXT,
  content_hash  TEXT NOT NULL,              -- sha1(markdown),用于 change detect
  payload_bytes INTEGER NOT NULL,
  dump_bytes    INTEGER DEFAULT 0,
  screenshot_bytes INTEGER DEFAULT 0,
  has_dump      INTEGER DEFAULT 0,
  has_screenshot INTEGER DEFAULT 0
);
CREATE INDEX idx_host ON entries(host);
CREATE INDEX idx_fetched_at ON entries(fetched_at);
CREATE INDEX idx_accessed_at ON entries(accessed_at);
CREATE INDEX idx_profile_host ON entries(profile, host);
PRAGMA journal_mode = WAL;
```

**安全不变量**:`profile` 参与 `url_hash` 计算意味着 `twitter` profile 抓的 `x.com/...` 与无 profile 抓的同 URL 是**两条独立 cache 条目**,不会互相覆盖、不会数据泄漏。这是 review A2 的修订点。

#### Payload JSON 结构
```json
{
  "url": "<original>",
  "canonical_url": "<after canonicalize>",
  "profile": "twitter",             // 或 null
  "fetched_at": 1717000000000,
  "status_code": 200,
  "headers": {"etag": "...", "last-modified": "..."},
  "markdown": "...",
  "headings": [{"level": 1, "text": "...", "line": 1}],
  "metadata": { ... 与 v0.2 fetch 返回一致 ... },
  "dump_path": "~/.lightcrawl/cache/dumps/<sha1>.md",
  "screenshot_path": "~/.lightcrawl/cache/screenshots/<sha1>.png"
}
```

#### 公开 API
```python
class Cache:
    def __init__(self, root: Path = Path("~/.lightcrawl/cache").expanduser()): ...

    def lookup(self, url: str, *, profile: str | None,
               max_age_ms: int | None) -> CacheHit | None:
        """命中且 age ≤ max_age 才返回。touch accessed_at。
        max_age_ms=None → 不读 cache;调用方应在外层短路,不要进 lookup。"""

    def lookup_for_revalidation(self, url: str, *,
                                profile: str | None) -> CacheHit | None:
        """无视 age,用于条件请求(取 etag/last-modified)。"""

    def store(self, url: str, *, profile: str | None,
              response: FetchResponse) -> None:
        """原子写:payload 写临时文件 + os.replace,再 INSERT OR REPLACE index。"""

    def touch(self, url: str, *, profile: str | None) -> None:
        """304 / 命中后更新 accessed_at + fetched_at。"""

    def delete(self, url: str, *, profile: str | None) -> None: ...

    def gc(self, *, max_total_bytes: int | None = None,
           older_than_ms: int | None = None,
           host: str | None = None) -> GCStats:
        """GC 使用独立 sqlite connection,避免与 store/lookup 共享事务。"""

    def stats(self) -> CacheStats: ...

    def legacy_dumps_usage(self) -> int:
        """报告 ~/.lightcrawl/dumps/(v0.2 旧目录)占用字节数。
        `lightcrawl cache stats` 子命令展示这个数,提示用户手动清理。"""
```

#### `max_age_ms` 语义
- `max_age_ms`:cache age ≤ max_age → 用 cache;否则刷新。`None` 表示永不接受 cache(调用方应短路,不进 lookup)。
- 不再实现 `min_age_ms`(review A1)。

#### 原子性
- payload 写盘:`payloads/<sha1>.json.tmp` → `os.replace(...)` → SQLite INSERT OR REPLACE。`os.replace` 在 Windows 上目标存在仍可成功,且语义上跨平台原子。
- 崩溃恢复:启动时不主动 reconcile;`gc(repair=True)` 提供手动修复(扫描 `payloads/` 与 index 求差集)。

#### GC 触发
- **被动**:每次 `store` 后,以 1/256 概率检查总容量;超过 `max_total_bytes`(默认 1 GiB,可在 `~/.lightcrawl/config.toml` 配)则按 `accessed_at` 升序删,直到回到 80% 水位。GC 走**独立 SQLite connection** + 独立事务,避免与并发 `store` 共享游标导致 stall。
- **主动**:`lightcrawl cache clear` 子命令。

### 5.3 `sitemap.py`(新,~150 LOC)

```python
class SitemapEntry(NamedTuple):
    url: str
    lastmod: datetime | None
    changefreq: str | None
    priority: float | None

async def discover_sitemaps(host_or_url: str, *,
                            router: Router) -> list[str]:
    """robots.txt → Sitemap: 行;若无,尝试 /sitemap.xml /sitemap_index.xml。"""

async def parse_sitemap(url: str, *, router: Router,
                        max_entries: int = 50_000) -> list[SitemapEntry]:
    """支持 sitemap index(递归一次,深度上限 2)。"""

async def fetch_robots(host: str, *, router: Router) -> RobotsRules:
    """按 host 拉取并解析 robots.txt(用 Python 标准库 urllib.robotparser
    + 自己读 robots.txt 文本以提取 Sitemap: 行)。
    跨子域 crawl 时,每个 host 单独 fetch 一次(见 §5.5 C2)。"""
```

- 所有抓取走 `Router.fetch(strategy="http")`,sitemap 是 XML、robots 是文本,L1 足够,跳过 L2 节省成本。
- 解析器对 XML 用 `lxml.etree`(已是项目依赖),namespace 容错。
- `max_entries` 防止巨型 sitemap 把内存吃掉(Cloudflare 的 sitemap 可达 50k 条)。

### 5.4 `jobs.py`(新,~250 LOC)

#### 状态机
```
created → running → completed
                  ↓
                  ├→ interrupted (进程消失)
                  ↓        ↑ crawl-resume
                  └→ cancelled (用户主动)
```

#### 落盘
```
~/.lightcrawl/jobs/
  <job_id>.json                 # 任务状态(progress + status),5s + 10 页定期 flush
  <job_id>.pid                  # {"pid": ..., "create_time": ...},用于 reconcile
  <job_id>.cancel               # crawl-cancel 写空文件;工作循环每页轮询一次
  <job_id>.visited.txt          # append-only:每行一条 (canonical_url, status) 元组
  <job_id>.frontier.jsonl       # 待访问 URL 队列,head pop / tail push;周期 compaction
  <job_id>.results.jsonl        # 成功每页一行:{url, status, fetched_at, cache_hit, ...}
```

**job_id 格式**:`crawl-<utc_iso_basic>-<uuid4_hex_12>`,例如 `crawl-20260518T143012-7af3b921c4d2`。可读、可按时间排序、12 字符随机段使碰撞概率 ~1/2⁴⁸,可忽略(review B4)。**不使用 `:` 字符**以兼容 Windows NTFS。

#### Visited 双状态(review B1 修订)
原设计的"乐观 visited" 取舍在 resume 场景下损失过多。改为两个集合:
- **`claimed`**:fetch 即将开始时立刻写入 `visited.txt`,记 `(url, "claimed", ts)`。**用于死循环防护、frontier 去重**。
- **`completed`**:fetch 成功后写入 `(url, "completed", ts)`。
- Resume 时:扫描 `visited.txt`,把 `claimed - completed` 的 URL 重新入 frontier,给瞬时失败第二次机会。
- 内存中维护两个 `set[str]`,启动时从 `visited.txt` 加载。

#### Job JSON 结构(瘦身版)
```json
{
  "job_id": "crawl-...",
  "type": "crawl",
  "params": { ... 完整保留 CLI 参数,resume 时直接复用 ... },
  "status": "running",
  "started_at": 1717000000000,
  "updated_at": 1717000123000,
  "completed_at": null,
  "progress": {
    "pages_fetched": 42,
    "pages_failed": 3,
    "pages_pending": 17,
    "pages_skipped_cache": 31,
    "pages_skipped_robots": 0,
    "pages_skipped_filter": 0
  },
  "errors_tail": [
    {"url": "...", "error_code": "FETCH_TIMEOUT", "at": 1717000050000}
  ]
}
```
**`visited` / `frontier` / `errors_full` 不再放进 job JSON**(review C1):
- `visited.txt` append-only,reload 时一次性 stream 读入内存
- `frontier.jsonl` head/tail 操作,每 1000 行触发 compaction
- `errors_tail` 只保留最近 50 条;完整错误日志在 `results.jsonl` 中 `ok=false` 的行

这样 10k 页的 crawl,job JSON 始终在 ~10KB 量级,5s flush 不再有写盘压力。

#### Flush 节奏
- Job JSON:每 5 秒或每 10 页(取早者),`os.replace` 原子写
- `visited.txt` / `results.jsonl`:每条记录立即 append + `fsync`,**不缓冲**(append 是 atomic)
- `frontier.jsonl`:head pop / tail push 也立即 append + 标记 tombstone;每 1000 行 compaction

#### PID + create_time 判活(review B5,Windows 适配)
用 **psutil**(跨平台一致;Unix 上避开 fcntl/flock 与防病毒、OneDrive 同步目录的边角冲突):

```python
import psutil, json

def write_pid_file(path: Path) -> None:
    me = psutil.Process()
    path.write_text(json.dumps({
        "pid": me.pid,
        "create_time": me.create_time(),  # 浮点秒,跨平台
    }))

def is_owner_alive(path: Path) -> bool:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    try:
        proc = psutil.Process(data["pid"])
        return abs(proc.create_time() - data["create_time"]) < 0.01
    except psutil.NoSuchProcess:
        return False
```

**Reconcile 流程**:任何 lightcrawl CLI 启动时扫 `jobs/`,对 `status=running` 但 `is_owner_alive(.pid) == False` 的,改写 status=interrupted。**PID 复用免疫**:create_time 不匹配即认为原 owner 已死,即使新进程占用同一 PID 也不会误判。

#### 信号处理(三平台)
```python
# 在 crawl 主入口,而不是 jobs.py 内部 —— jobs.py 是数据层
def install_signal_handlers(job: Job):
    # SIGINT 三平台都支持;Ctrl+C 会触发
    signal.signal(signal.SIGINT, lambda *_: job.request_shutdown("interrupted"))
    if sys.platform != "win32":
        # SIGTERM 仅 POSIX;Windows 没有等价物
        signal.signal(signal.SIGTERM, lambda *_: job.request_shutdown("interrupted"))
    # 远程取消(跨平台)走 .cancel 文件轮询,见 crawl.py
```

`job.request_shutdown` 设置内部 flag,主循环每页检查;触发后 flush、删除 `.pid`、退出。SIGKILL / Windows TaskKill /F 无法捕获 —— 那走"启动期 reconcile"路径兜底。**`loop.add_signal_handler` 不使用**,因为它在 Windows `SelectorEventLoop` 上 raise NotImplementedError。

#### 取消
- `crawl-cancel <job_id>` 写 `<job_id>.cancel`(空内容,存在即生效)。**跨平台**,不依赖信号。
- 工作循环每完成一页检查一次该文件;存在则把 status 改 cancelled、flush、退出。
- 若 PID 仍活且超过 10s 无反应(用户脚本卡死):
  - Unix:`os.kill(pid, SIGTERM)`,再走 reconcile 标 interrupted
  - Windows:`psutil.Process(pid).terminate()`,等价于 TerminateProcess API

### 5.5 `crawl.py`(新,~320 LOC)

#### BFS 主循环骨架
```python
async def run_crawl(params: CrawlParams, job: Job, router: Router, cache: Cache) -> None:
    frontier: asyncio.Queue[FrontierItem] = asyncio.Queue()
    for seed in await seed_urls(params, router):
        await frontier.put(FrontierItem(url=seed, depth=0))

    sem = asyncio.Semaphore(params.concurrency)
    in_flight: set[asyncio.Task] = set()
    robots_cache: dict[str, RobotsRules] = {}  # host -> rules,见 C2

    while not job.should_stop():
        if frontier.empty() and not in_flight:
            break
        while not frontier.empty() and len(in_flight) < params.concurrency:
            item = await frontier.get()
            if item.canonical in job.claimed or not allow(item, params, robots_cache):
                continue
            job.mark_claimed(item.canonical)         # append visited.txt: (url, "claimed", ts)
            t = asyncio.create_task(fetch_one(item, sem, router, cache, params))
            in_flight.add(t)
        done, in_flight = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            result = t.result()
            job.record(result)                       # 成功 → mark_completed; 失败 → errors_tail
            if result.ok and result.depth < params.max_depth:
                for link in result.outlinks:
                    await frontier.put(FrontierItem(url=link, depth=result.depth + 1))
        if job.progress.pages_fetched >= params.max_pages:
            break
    await job.finalize()
```

#### 边界条件清单(逐项实现,有对应测试)
1. **死循环防护**:`claimed` 集合用 canonical URL,所有入队前规范化。
2. **域过滤**:默认 host 完全相等;`--allow-subdomains` 切 eTLD+1 同源;`--crawl-entire-domain` 强制 eTLD+1。
3. **robots.txt 按 host 缓存**(review C2):`robots_cache` 字典以 host 为 key;首次访问该 host 时按需 `fetch_robots(host, router)`;失败(404 / 网络问题)视为"无限制"。`--ignore-robots-txt` 整体跳过该子系统。Disallow 命中的 URL 直接丢,记入 `progress.pages_skipped_robots`,不算 failed。
4. **include/exclude paths**:`re.search` 在**原始 URL**(canonical 化之前)的 `path + "?" + query` 上匹配。canonical 化的 URL 只用于去重 / cache key(review C4)。**exclude 先于 include**(safer fail-closed)。命中 exclude → 记入 `progress.pages_skipped_filter`。
5. **失败不阻塞**:`fetch_one` 内部 try/except 任何异常都返回 `CrawlResult(ok=False, error_code=...)`;失败不入 frontier 但记录 errors。
6. **outlinks 提取**:复用 v0.2 `content._extract_links`,取 `internal=True`(或在 allow_subdomains 模式下取 same-etld1)。`rel=nofollow` 默认遵守,可加 `--follow-nofollow` 关闭(stretch)。
7. **`max_pages` 软上限**:循环每完成一页检查;并发情况下实际抓取数可能 = max_pages + concurrency - 1,接受这一误差,不为此加锁。
8. **cache 命中**:`fetch_one` 内部先 `cache.lookup(url, profile=params.profile, max_age_ms=params.max_age_ms)`,命中走 cache(`progress.pages_skipped_cache += 1`),否则 `router.fetch(req)` 并 `cache.store`。
9. **`--no-cache` 覆盖默认**(review B3):crawl 默认 `max_age_ms=1h`;用户显式 `--no-cache` 时 `max_age_ms=None` 且 `store_in_cache=False`。命令行参数权威。

### 5.6 `map_url` 实现

```python
async def run_map(seed: str, *, search_filter: str | None,
                  limit: int, router: Router) -> MapResult:
    sitemap_urls = await discover_sitemaps(seed, router=router)
    if sitemap_urls:
        urls = []
        for s in sitemap_urls:
            urls.extend(await parse_sitemap(s, router=router))
        source = "sitemap"
    else:
        resp = await router.fetch(FetchRequest(url=seed, output_format="links"))
        urls = [SitemapEntry(url=l["url"], ...) for l in resp["metadata"]["links"]
                if l["internal"]]
        source = "homepage"
    urls = dedupe_canonical(urls)
    if search_filter:
        urls = [u for u in urls if search_filter.lower() in u.url.lower()]
    return MapResult(source=source, urls=urls[:limit], count=len(urls))
```

输出:
```json
{"ok": true, "source": "sitemap", "count": 1247,
 "urls": [{"url": "...", "lastmod": "..."}, ...]}
```

`count=0` 时 `ok` 仍可为 `true`,但 `notes` 字段说明原因(见 SKILL.md honesty contract 第 4 条)。

### 5.7 `batch-fetch` 实现

不走 job 框架。语义:已知 URL 列表,并发抓取,全部完成后一次性返回。

```python
async def run_batch_fetch(urls: list[str], params: BatchParams,
                          router: Router, cache: Cache) -> BatchResult:
    sem = asyncio.Semaphore(params.concurrency)
    async def one(u: str):
        async with sem:
            return await fetch_with_cache(u, params, router, cache)
    results = await asyncio.gather(*(one(u) for u in urls), return_exceptions=True)
    return BatchResult(results=[
        r if isinstance(r, dict) else _exc_to_failure(r) for r in results
    ])
```

CLI:
```
lightcrawl batch-fetch URL1 URL2 ...
lightcrawl batch-fetch --urls-file urls.txt
```
`urls.txt` 一行一 URL,`#` 开头注释。

输出:
```json
{"ok": true, "count": 12, "ok_count": 10, "failed_count": 2,
 "results": [ {ok: true, url, markdown, ...}, {ok: false, url, error_code, ...}, ... ]}
```

**顶层 `ok=true` 表示"批次完成",不表示"所有 URL 都成功"** —— SKILL.md honesty contract 第 5 条明文化。

---

## 6. `FetchRequest` 改动

新增字段(全部带默认,**不破坏现有调用方**):
```python
@dataclass
class FetchRequest:
    # ... 已有字段 ...
    max_age_ms: int | None = None     # None = 不读 cache
    cache_only: bool = False           # True 且未命中 → 返回 CACHE_MISS error
    store_in_cache: bool = False       # True 时成功响应入 cache
    no_cache: bool = False             # True 时既不读也不写(显式覆盖)
```

Cache key 计算口径:`url_hash(canonicalize_url(req.url), profile=req.profile)`。即 cache key 与 profile 维度绑定(review A2)。

**默认值翻转**:`remove_base64_images: False → True`。这是 v0.3 唯一的**破坏性默认**。理由:base64 内联图片对 LLM 几乎无用,但会显著膨胀 token 与 cache 体积。v0.2 README 已声明 v0.3 翻转计划;v0.3 README 首屏加 changelog 块。

**`min_age_ms` 不引入**(review A1)。

### Python 依赖新增

`pyproject.toml`:
```toml
dependencies = [
    # 已有项 ...
    "psutil>=5.9",  # 跨平台进程判活,Windows 一线支持依赖
]
```

---

## 7. 错误码新增(`errors.py::ErrorCode`)

```
CACHE_MISS              cache_only=True 且未命中
CACHE_CORRUPT           payload 文件损坏或与 index 不一致
ROBOTS_DISALLOWED       crawl 中被 robots.txt 拒绝(不算 failure,统计单列)
JOB_NOT_FOUND           crawl-status/resume/cancel 找不到 job_id
JOB_NOT_RESUMABLE       状态不是 interrupted(已 completed/running/cancelled)
JOB_ALREADY_RUNNING     resume 时发现 owner 进程仍活(psutil 校验通过)
SITEMAP_PARSE_ERROR     XML 解析失败,可降级到 homepage 模式
CRAWL_MAX_PAGES         达到 max_pages 上限(info 性质,非 failure)
CRAWL_BUDGET_EXCEEDED   单 job 超出 cache 容量预算(可配,默认无限)
CACHE_FLAG_CONFLICT     --no-cache 与 --max-age / --cache-only / --no-store 并存
```

约定:`CACHE_MISS` / `ROBOTS_DISALLOWED` / `CRAWL_MAX_PAGES` 这三类是"预期分支",`ok` 仍可为 `true`(对应字段在 result 内表达),不视为 hard failure。

---

## 8. 数据布局变更与迁移

```
~/.lightcrawl/
  config.toml
  profiles/<name>.json                ← 不变
  cache/                              ← 新
    index.sqlite
    payloads/<sha1>.json
    dumps/<sha1>.md
    screenshots/<sha1>.png
  jobs/                               ← 新
    <job_id>.json
    <job_id>.pid
    <job_id>.cancel
    <job_id>.visited.txt
    <job_id>.frontier.jsonl
    <job_id>.results.jsonl
  dumps/                              ← v0.2 旧目录,v0.3 起停止写入
```

**迁移策略**:不自动迁移。v0.3 启动时探测 `~/.lightcrawl/dumps/` 是否存在,在 stderr 打一行警告:
```
[lightcrawl] note: legacy ~/.lightcrawl/dumps/ found (X MB); new dumps go to ~/.lightcrawl/cache/dumps/.
```
`lightcrawl cache stats` 同样会在输出末尾报告 legacy 占用,提示手动 `rm` 释放。

**Windows 路径展开**:所有 `~/.lightcrawl/...` 经 `Path.home()` 展开,在 Windows 上对应 `C:\Users\<user>\.lightcrawl\...`。OneDrive 同步目录、防病毒目录可能对 SQLite 加临时锁 —— 我们用 WAL 模式 + `timeout=5.0` 容忍。

---

## 9. 测试矩阵(全部离线)

新增 7 个测试文件,沿用现有 monkeypatch 模式:

| 文件 | 覆盖 | 关键 fixture |
|---|---|---|
| `tests/test_canonical.py` | 30+ URL 规范化用例(IPv6、tracking 参数、% encoded);profile 维度参与 hash 的不变量测试 | 纯函数 |
| `tests/test_cache.py` | lookup/store/touch/gc/原子写崩溃模拟;不同 profile 同 URL 不串扰 | tmp_path |
| `tests/test_cache_concurrency.py` | SQLite WAL 模式下多进程并发 store/lookup;独立 connection 不互相 stall | `multiprocessing` |
| `tests/test_sitemap.py` | robots.txt、sitemap.xml、sitemap index 解析 | 静态 XML/TXT 字符串 |
| `tests/test_jobs.py` | 状态机、flush 节奏、PID + create_time reconcile、cancel 标志文件、claimed/completed 拆分、resume 不重抓 | tmp_path + fake clock + psutil mock |
| `tests/test_crawl.py` | BFS 图(deterministic)、并发上限、robots per-host、include/exclude 在原始 URL 上、max_pages 软上限、cache 跳过、`--no-cache` 覆盖 | monkeypatch `Router.fetch` |
| `tests/test_batch_fetch.py` | 部分失败、并发上限、cache 复用、`ok=true && ok_count=0` 语义 | 同上 |
| `tests/test_pr1a_params.py` 等已有 | 默认 `remove_base64_images=True` 后所有断言更新 | 既有 |

**关键禁忌**:测试不允许访问真实网络。Router 在 `tests/conftest.py` 通过 monkeypatch `fetch_http.fetch` 和 `fetch_browser.fetch` 全程屏蔽。

**fake clock**:`jobs.py` / `cache.py` 内部全部用 `time_ms()` 函数获取时间,测试中 monkeypatch 该函数实现确定性时间。

**Windows CI**:GitHub Actions matrix 加 `windows-latest`。最小覆盖目标:
- `test_jobs.py`(psutil + os.replace + signal.signal SIGINT)
- `test_cache.py`(SQLite WAL + os.replace + Windows 路径展开)
- `test_canonical.py`(纯函数,平台无关但保险)
- `test_crawl.py` 不强求全过(playwright on Windows 慢且占盘),可跳过 browser-touching 子测试

---

## 10. 验收标准(对照 issue #22 + review C5)

1. **端到端 crawl 中等规模文档站**:`lightcrawl crawl https://fastapi.tiangolo.com/ --max-pages 200 --max-depth 4` 完成,200 页每页 markdown 可读、无 HTML 残留。手动 benchmark,记入 `bench/results/v0.3_fastapi.md`。
2. **二次 crawl 命中率(拆两档)**:
   - **(a)** 二次 crawl 同命令、间隔 < 1h、`--max-age 1h` → `pages_skipped_cache / pages_fetched ≥ 0.95`(主路径,必须达成)
   - **(b)** 二次 crawl 同命令、间隔 > 24h、不设 `--max-age` → 走 ETag/304 路径,304 命中率 ≥ 0.5(**条件**:R1 探针通过且 PR 3 合入;否则本条不作硬性要求,降级为"已知 limitation")
3. **静态资源 304 路径**:`bench/diagnostic` 增加用例,fetch 一个带稳定 `etag` 的页面两次,第二次断言走 304(通过日志或 cache stats 验证)。仅在 R1 探针通过时验收。
4. **崩溃恢复**:`crawl --max-pages 100`,在 30 页时 `kill -9`(Windows:`Stop-Process -Force`);重启进程跑 `lightcrawl crawl-resume <job_id>`,最终 `pages_fetched` 不重复计数;`claimed - completed` 的 URL 被重新尝试。
5. **取消生效**:运行中 crawl 触发 `crawl-cancel` 后 ≤ 1 个并发批次内停止,status 终态为 cancelled,无僵尸进程。Windows 与 Unix 各跑一次。
6. **PID 复用免疫**:测试构造场景:先跑一个 crawl 拿到 pid=12345 然后 kill;手动找一个新进程占用 12345(测试中可以 fork bomb 直到拿到);跑 reconcile,断言 job 被标 interrupted 而非误判 running。
7. **v0.2 所有测试通过**:零回归。
8. **`remove_base64_images=True` 默认翻转**:CHANGELOG / README / SKILL.md 三处同步更新,带迁移说明。
9. **Windows CI 绿灯**:`windows-latest` runner 上至少 `test_canonical.py / test_cache.py / test_jobs.py / test_sitemap.py / test_batch_fetch.py` 全过。

---

## 11. 风险与开放问题

### R1:curl_cffi 条件请求兼容性 + PR 3 gate(review B2 修订)
风险:`If-None-Match` / `If-Modified-Since` 经过 `impersonate` 模板时,header 顺序可能影响 TLS 指纹特征,导致 Cloudflare 后端 200 而非 304。
处置:
1. PR 3 启动前先写 `bench/probe_conditional.py`,对若干代表性站点(Cloudflare 后端的小博客、GitHub Pages、Vercel 部署、static S3)各做一次 304 验证。
2. **probe 通过才合并 PR 3**;不通过则把 ETag/Last-Modified 整个推迟到 v0.4,**不引入"降级到非 impersonate 路径"** —— 那等于关掉 curl_cffi 的核心价值,304 永不命中,是空头降级。
3. 验收 #2 主要靠 `max_age_ms` 路径达成;ETag 仅作锦上添花。

### R2:SQLite 多进程写并发
风险:用户同时跑 `crawl` + `batch-fetch` 都要写 index,Windows 上 OneDrive / 防病毒目录还可能瞬时持有锁。
处置:`sqlite3.connect(..., timeout=5.0)` + `PRAGMA journal_mode=WAL`。冲突时退而重试 3 次。`test_cache_concurrency.py` 用 `multiprocessing` 模拟并发,Windows CI 上同样跑。

### R3:Job 框架 LOC 预算
issue 估算 200 LOC,实际包含信号处理、flush 调度、reconcile、cancel、psutil 抽象、claimed/completed —— 现估 300–400 LOC。可接受。**红线**:不允许引入 SQLite / Redis / 任何外部 broker;JSON + append-only 文件 + psutil 是上限。

### R4:Resume frontier 一致性(review B1 修订)
原设计的"乐观 visited 标记"会让瞬时网络抖动 = 永久跳过。
处置:visited 拆 `claimed` / `completed`,resume 时 `claimed - completed` 重新入 frontier。死循环防护仍由 `claimed` 保证(同一 URL 不会被 claim 两次),但瞬时失败在 resume 时得到第二次机会。代价仅是每条记录多 8 字节状态。

### R5:`block_ads` 决策
issue 标注 "pending decision"。本设计明确**推迟**到 v0.4。理由:需要 Playwright `page.route` + 维护规则集(uBlock filter 兼容?),范围会显著扩展;不应该塞进已经较重的 v0.3。

### R6:Windows 信号 / 子进程语义差异
Windows 没有 SIGTERM 等价物;`asyncio.SelectorEventLoop.add_signal_handler` 不可用;`os.kill` 仅能发 SIGTERM/SIGKILL 在 POSIX 上有意义。
处置:统一走 `signal.signal(SIGINT, ...)` + `.cancel` 文件轮询;远程终止用 `psutil.Process.terminate()`(Windows 上对应 TerminateProcess API)。所有 Windows 行为有 `test_jobs.py` 在 Windows CI 上的覆盖。

---

## 12. 实施切片(参照 v0.2 PR 系列节奏)

| PR | 内容 | 大小 | 依赖 |
|---|---|---|---|
| **PR 1** | `canonical.py` + URL 形态用途表 + 测试;翻转 `remove_base64_images=True` + 文档同步 | S | — |
| **PR 2** | `cache.py`(profile 维度 key、无条件请求、store/lookup/gc 独立 connection)+ `FetchRequest` 新字段 + cache flag truth table argparse 校验 + Router 切面 + 测试 | M | PR 1 |
| **PR 3** | ETag/Last-Modified 条件请求(L1 only)+ R1 probe 脚本 + 测试。**probe 不通过则关闭此 PR,推 v0.4** | S | PR 2 |
| **PR 4** | `sitemap.py` + `lightcrawl map` 子命令 + 测试 | M | PR 1 |
| **PR 5** | `jobs.py`(状态机、flush、reconcile、cancel、psutil、claimed/completed、append-only 落盘)+ 单测;**提供 1 页 stub crawl 入口**让 PR 6 可 incremental 推进 | M | psutil 加 pyproject |
| **PR 6** | `crawl.py` + `lightcrawl crawl/-status/-resume/-cancel/jobs` 子命令 + robots per-host + include/exclude 用原始 URL + `--no-cache` 覆盖 + 测试 | L | PR 2, 4, 5 |
| **PR 7** | `batch-fetch` + `cache stats`/`cache clear` 子命令 + legacy dumps 占用报告 + 测试 | S | PR 2 |
| **PR 8** | bench:fastapi 端到端、cache 命中率两档基准、Windows CI matrix、README / SKILL.md / CLAUDE.md 同步到 v0.3 + version bump | S | 全部 |

总计 8 个 PR,与 v0.2 的 5 个 PR 节奏可比。预计 3.5 周与 issue ETA 一致。**PR 5 的 stub 设计**:`run_crawl_stub(seed, max_pages=1)` 跑一页就返回,让 PR 6 在 PR 4/5 merge 前可以并行推进 crawl 子命令的 argparse + 输出格式,真实 BFS 在 PR 6 内补全。

---

## 13. 不变量(reviewer checklist)

- [ ] CLI stdout 永远是单一 JSON,新子命令仍走 `cli._safe_run`。
- [ ] 任何新公开 API 失败返回 `{ok: false, error_code, error_detail}`,不抛栈到 stdout。
- [ ] 新模块的测试**全部离线**,网络访问代码进 `bench/`。
- [ ] cache 与 crawl 共用 `canonical.py`;新增 URL 处理路径不能绕过它。
- [ ] **Cache key 包含 profile 维度**;不同 profile 同 URL 是两条独立 entry,不可串扰。
- [ ] Job 状态写盘原子(tmp + `os.replace`,跨平台);任何写中断不损坏现有 job。
- [ ] 不引入 MCP / daemon / 外部 broker;jobs.py 之外不允许新增持久化组件。
- [ ] `~/.lightcrawl/` 下文件全部用户可读;不写超出该目录的任何持久化数据。
- [ ] **所有文件名 / 子命令在 Windows NTFS 上合法**(无 `: < > | " * ?`)。
- [ ] **所有原子写用 `os.replace`,不用 `os.rename`**(后者在 Windows 上目标存在时失败)。
- [ ] **进程判活用 psutil PID + create_time 双重比对**,不用 PID-only / fcntl.flock / msvcrt.locking。
- [ ] **`loop.add_signal_handler` 不出现在源码中**(Windows 不支持);信号通过 `signal.signal` 注册,远程信号通过 `.cancel` 文件。
