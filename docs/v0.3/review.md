# v0.3 设计文档评审

**评审对象**:`v0.3-design.md`(lightcrawl v0.3 — Local firecrawl: Map + Crawl + Cache)
**评审日期**:2026-05-19
**评审视角**:架构一致性、可实现性、边界条件、与 v0.2 既有不变量的兼容

---

## 总体判断

**结论:可批准实施,但有 3 处需在 PR 1 / PR 2 之前澄清,5 处需在对应 PR 内修正,其余为建议性 nit。**

文档整体很扎实:
- 章节 2 的 diff 图清楚地把"Cache 是切面、CrawlEngine 是编排层、不下钻 Router"这一原则讲透,这是这版设计的关键架构决定,把范围控制在了 CLI + Skill 两层不变。
- 章节 11 风险 R1/R2/R4 已经提前点名了 curl_cffi 条件请求、SQLite WAL、resume frontier 三个最容易翻车的地方。R4 的取舍("丢一个 URL 比死循环重抓更可接受")是一个值得保留的明确判断。
- 章节 13 不变量清单覆盖了 stdout-单 JSON、错误信封、离线测试、cache/crawl 共用 canonical 等 v0.2 已有契约,reviewer checklist 直接可用。
- PR 切片节奏与 v0.2 5 个 PR 的实际工作量基本对齐,PR 间依赖图无环。

下面按"必须澄清 / 需要修正 / 建议改进 / 小问题"四档列出具体意见。

---

## 一、必须在 PR 1 / PR 2 前澄清(3 项)

### A1. `min_age_ms` 语义需要核对 firecrawl 真实行为

**位置**:§5.2 "`max_age_ms` / `min_age_ms` 语义(对齐 firecrawl)"

文档当前定义:
> `min_age_ms`:cache age ≥ min_age → 用 cache(即使本来想刷新)。这是 firecrawl `minAge` 的语义,常用于"我只是保持稳定输出,别太勤地重抓"。

这条语义读起来反直觉。把它翻译成场景:

- 设 `min_age=1h`。cache 是 30 分钟前的 → 按当前定义**会刷新**(因为 cache 还不够旧)。cache 是 2 小时前的 → **用 cache**。
- 但用户写 `min_age=1h` 的心智模型通常是"1 小时内别再打它",即"距上次 fetch 不到 1 小时则用 cache,超过 1 小时才刷新"——这恰好和文档的定义**相反**。

文档同时说 `min_age` 与 `max_age` 同时设置时 `min_age` 优先,等同 `cache_only on a stale-OK basis`,但这又把 `min_age` 描述成"接受陈旧 cache 的开关",和上一段的"频率限制"用途又对不上。两个解释互相矛盾。

**建议处置**:在 PR 2 动工之前,跑一次 firecrawl 官方 SDK / API 对 `maxAge` / `minAge` 的小实验,把真实语义写进设计文档,再决定 lightcrawl 是 1:1 跟随还是只实现 `max_age`。如果时间紧,**先只做 `max_age`,把 `min_age` 推迟到 v0.4**——后者在 firecrawl 自身的实际使用中也较少见。这能省掉一个非关键的歧义点。

### A2. Authed fetch 的 cache key 是否包含 profile?

**位置**:§5.2 index 表结构 + §8 数据布局

设计文档完全没提到 `auth.py` profile 与 cache 的交互。但这是个一旦上线就难改的决定:

- `twitter` profile 抓取 `x.com/user/123/private-tweet`(看得到隐藏内容)
- 无 profile 调用同一 URL(看到的是 wall)
- 二者若共用一条 `url_hash` 索引,**第二次调用会把第一次的"已登录"结果回放给"未登录"的请求方**,这是数据泄漏面。

`fetch_browser.py` 中 L3 是按 profile 加载 storage_state 的,意味着同一 URL 在不同 profile 下**确实会产生不同内容**。Cache key 必须把这一维度纳入。

**建议**:`url_hash = sha1(canonical_url + "\0" + (profile or ""))`。同时 `index.sqlite` 增加 `profile TEXT` 列(可空),`PRIMARY KEY (url_hash)` 改为 `PRIMARY KEY (url_hash)` 不动但 `url_hash` 计算口径变。Payload JSON 内冗余记录 `profile` 以便人工排查。

**这是个不变量级别的问题**,应在 PR 2 进入主分支前固定下来,不然后期改 cache key 等于全量失效。

### A3. `--no-cache` 与 `--no-store` 的语义重叠

**位置**:§3 "`fetch` 子命令新增标志"

```
--cache-only       只读 cache,未命中直接返回 cache_miss 错误,不访问网络
--no-cache         完全跳过 cache(既不读也不写)
--no-store         读 cache 但不回写(用于一次性抓取)
```

三个 cache 控制标志、四种组合,但对应到 `FetchRequest` 的两个布尔字段 `cache_only` / `no_cache` / `store_in_cache`,加上 `max_age_ms=None` 这个隐式开关,语义状态空间已经有 4×3=12 种组合。其中**多数组合无意义**:

- `--cache-only --no-cache` 是矛盾的
- `--no-cache --no-store` 等价于 `--no-cache`
- `--no-store` 单独使用时,如果 `max_age_ms=None`,本来就不读 cache,这个 flag 实际只在和 `--max-age` 一起用时才生效

**建议**:在 PR 2 实现前,用一张 truth table 把"哪些组合合法、其余的 CLI 直接报参数冲突"明确下来,**写进 `argparse` 校验**。否则 agent 会 trial-and-error 试出各种边角语义,导致 SKILL.md 不得不写一堆 caveat。

可参考 HTTP `Cache-Control` 的命名:`--cache-control no-cache,no-store` 单 flag 多值,语义直接对齐 RFC 7234,agent 也更容易理解。但这是 nice-to-have,不必现在切。

---

## 二、需要在对应 PR 内修正(5 项)

### B1. R4 的"乐观 visited 标记"会让瞬时网络抖动 = 永久跳过

**位置**:§11 R4

> 处置:`fetch_one` 启动时立即把 URL 加入 `visited`(乐观),即使后续失败也不重抓。

后果:某 URL 在第 30 页时因为 502 失败,被加入 `visited`。Resume 之后这条 URL **永远**不会被再次尝试。对一个声称"可中断、可恢复"的 crawl,这个语义偏严苛。

**建议**:把 `visited` 拆成两个集合:
- `claimed`(进 fetch 前写入,持久化)→ 用于死循环防护、frontier 去重
- `completed`(fetch 成功后写入)→ 用于 resume 时识别"真的抓过的"

Resume 时,`claimed - completed` 的 URL 重新入 frontier。这样:
- 死循环依然被防住(同一 URL 不会被 claim 两次)
- 瞬时失败的 URL 在 resume 时得到第二次机会
- 多算的代价仅是每条记录多 8 字节状态,完全可接受

文档里 R4 的取舍其实只在"同一进程内 fetch 失败立刻再试"的场景下成立;对 resume 场景,这个取舍是不必要的损失。

### B2. R1 的降级方案实际上是放弃 304

**位置**:§11 R1 + §12 PR 3

> 处置:...若失败,把条件请求降级为"只对没启用 `impersonate` 的 L1 路径生效"。

但生产中 L1 默认是开启 `impersonate` 的(curl_cffi 的核心价值),走"非 impersonate 路径"等于退回到 `requests`,会立刻被 Cloudflare 拦掉,触发 L2。这意味着**降级路径等于 304 永不命中**——验收标准 #3 直接挂掉。

**建议**:
1. PR 3 的 probe 脚本必须先跑通,**通过才合并 PR 3**;不通过则把 ETag/Last-Modified 整个推迟到 v0.4,不要勉强合一个废功能。
2. 验收标准 #2(二次 crawl ≥0.9 cache 命中)主要靠 `max_age_ms` 路径达成,而不是依赖 304。把 ETag 视作锦上添花,降低其在验收中的权重。

### B3. `crawl` 强制开 cache 与 `--no-cache` 标志冲突未定义

**位置**:§4 + §3 crawl 完整标志

§4 写:"`crawl` 与 `batch-fetch` 内部**强制开启 cache**"。§3 又说 crawl 接受"所有 cache 控制标志(见上)",其中包含 `--no-cache`。

`lightcrawl crawl https://foo/ --no-cache` 的行为是?
- 选项 a:`--no-cache` 优先,关 cache(用户显式表达意图)
- 选项 b:`--no-cache` 被静默忽略,仍走 cache(因为 crawl 强制)
- 选项 c:argparse 报错(crawl 不允许这个组合)

任一选项都合理,但**必须选一种**,并写进 SKILL.md 的 honesty contract,否则 agent 会得到不同实验结果。

**建议**:选 a。"强制开启"应改述为"默认开启";用户显式关掉是用户的责任。

### B4. Job ID 冲突概率

**位置**:§5.4 "`job_id` = `crawl-<utc_iso_basic>-<random4>`"

同一秒启动两个 crawl 的碰撞概率:`1 / 65536`。在测试套件/CI 中并发跑就有可能撞,在生产中一个 cron 启动两个并发 crawl 也会撞。撞了之后 `.json`/`.pid`/`.cancel`/`.results.jsonl` 互相覆盖,**症状是 cancel 一个 job 误杀了另一个**——非常难调。

**建议**:`random4` → `random8`(碰撞概率 1/2^32,可忽略),或直接 `uuid4().hex[:12]`。文件名增加 4 字符没什么成本。

### B5. PID reconcile 没处理 PID 复用

**位置**:§5.4 "对 PID 不存在的"

Unix PID 会复用。`.pid` 里写的是 12345,进程死亡后系统迟早把 12345 再分配给一个无关进程。Reconcile 时看到 12345 还活着,会误判 job 仍 running。

**建议**:`.pid` 文件改为 `{"pid": 12345, "started_at_ns": 1717000000000000000}`。Reconcile 时:
1. 读 PID 与 start time
2. `psutil.Process(pid).create_time()` 对比;mismatch → 视作 interrupted
3. 没装 psutil 的环境退化为只看 PID(标注 best effort)

这事在测试中很难复现,但生产事故出现一次就够痛。

---

## 三、建议改进(可在 v0.3 内、也可推迟)

### C1. Job 的 `visited` 集合也会膨胀

§5.4 提到"results 单独写 JSONL,避免 job JSON 膨胀到几十 MB"——很好。但同一 job 的 `visited` / `frontier` 数组依然在 job JSON 里。一次 10k 页的 crawl,visited 仅 URL 字符串就 ~1 MB,每 5s flush 一次原子写(tmp + rename),实际是每 5s 把 1 MB 写盘并 fsync。

**建议**:`visited` 改用 `<job_id>.visited.txt`(append-only,一行一 URL),`frontier` 改用 `<job_id>.frontier.jsonl`(头部 pop、尾部 push,定期 compaction)。Job JSON 只保留 progress 计数和 status。这一改动也让 resume 不需要从 JSON 解析数千条 URL。

不算必须,但 PR 5 设计 `JobWriter` 时一并把这事考虑进去最经济;v0.3 内能做就做,做不完也不破坏接口。

### C2. Robots.txt 与多子域

§5.5 item 3:"在 seed 域上 fetch 一次并缓存到 job 内存"。但 `--allow-subdomains` / `--crawl-entire-domain` 会跨子域抓,而每个子域的 robots 可能不同(`docs.foo.com` 与 `api.foo.com` 通常各有一份)。当前设计在跨子域抓取时**只查 seed 子域的 robots**,这既不严谨也不符合 robots spec。

**建议**:robots 缓存按 `host` 分桶,首次访问该 host 时按需 fetch。失败(404 / 网络问题)视为"无限制"。这是 BFS 主循环的小改,内存开销可忽略(每个 host 一个 `RobotsRules` 对象)。

### C3. Cache 与 search-and-read 的关系未定义

设计文档完全没提到现有 `search-and-read` 是否会经过 cache。但 `search/service.py` 既然是用 `Router.fetch` 拉取结果页,只要 PR 2 在 Router 入口加了 cache 切面,search-and-read **自动**就会有 cache(取决于 `max_age_ms` 默认值)。

**建议**:在 §4 Skill 更新点里明确写一行:"search-and-read 默认行为不变(不读 cache),如需复用 cache 命中,显式传 `--max-age DUR`"。否则 reviewer 与 user 都会带着"search 是否变了"的疑问读 PR。

### C4. `include_paths` / `exclude_paths` 与 `--ignore-query-parameters` 的顺序

§5.5 item 4:"`re.search` 在 canonical URL 的 path+query 上匹配"。但当 `--ignore-query-parameters` 开启时,canonical URL 不带 query,那么 `--exclude-paths "utm_"` 这种 pattern 就永远不会命中。

**建议**:include/exclude 匹配应该在**未丢 query** 的 URL 上跑,canonical 化只用于去重/cache key。`canonicalize_url` 应该支持两种产物:`canonical_for_dedup` 与 `path_for_filter`,或者 filter 直接对原 URL 跑。文档需要把"哪个 URL 用于什么目的"列一张小表。

### C5. 验收标准 #2 的 0.9 门槛在没有 ETag 时是否实际?

§10 #2:"`progress.pages_skipped_cache + ETag 304 命中数 ≥ 0.9 × pages_fetched`"。

如果按 B2 把 ETag 视作 stretch,则 0.9 几乎全靠 `max_age_ms` 命中。但二次 crawl 紧跟一次 crawl 跑(几分钟内),只要给一个合理的 `--max-age 1h` 默认,所有页都会被 cache 命中,实测会接近 1.0 而不是 0.9。

**建议**:把 #2 改成两条:
- (a) 二次 crawl(同命令、间隔 < 1h、`--max-age 1h`)→ `pages_skipped_cache / pages_fetched ≥ 0.95`
- (b) 二次 crawl(同命令、间隔 > 24h、`--max-age 24h` 不设)→ 走 304 路径,命中率 ≥ 0.5(若 R1 探针通过)

两档分开评估,免得验收时遮蔽 ETag 路径的真实失败。

### C6. SKILL.md 新增 honesty contract 第 3 条措辞偏弱

§4:"crawl 部分失败不掩盖。... agent 不得把 `pages_failed > 0` 当成 success 报告给用户。"

实际还会有更隐蔽的情况:`ROBOTS_DISALLOWED` 与 `CRAWL_MAX_PAGES` 在 §7 被定为"预期分支,`ok` 仍可为 true"。若 agent 拿到 `count=0` 但 `ok=true`(因为 robots 全拒),用户得到"crawl 完成,0 页"的结果,语义上不算撒谎但严重误导。

**建议**:honesty contract 加一条:"crawl/map 的 `count=0` 必须被 agent 报告为'未发现页面/全部被规则过滤',并解释原因(robots / include-exclude / max_pages=0 等)。`ok=true` 不能等同于'有内容'"。

---

## 四、Nits(可不改)

- **§5.2 GC 触发** "1/256 概率"——可以,但 SQLite WAL 模式下 GC 写入和正在 crawl 的写入仍可能互相 stall。建议 GC 跑在独立连接 + 自己的事务里;文档没必要写细,但实现时记得别让 GC 和 store 共享同一 connection。
- **§5.6 `run_map`** 兜底用 `output_format="links"` 取 internal links——很好,但 sitemap 也应该取 SitemapEntry 之后**再次按 canonical 去重**,文档里 `dedupe_canonical(urls)` 已经写了,只是要确认 `canonicalize_url` 接受 `SitemapEntry.url` 不是 `str` 的细节。
- **§5.7 batch-fetch 输出**:`ok: true` 总是 true、即使所有 URL 都失败?当前 schema 是这样。这是个设计选择(batch 操作本身完成 = ok),需要在 SKILL.md 说明,否则 agent 会拿 `ok` 当"有有效内容"用。
- **§6 默认翻转 `remove_base64_images=True`**:已确认 v0.2 当前默认是 False(`src/lightcrawl/router.py:58`),flip 确实是 breaking。建议 v0.3 启动时若检测到 base64 图被 strip 且 `metadata.images` 中存在被去掉的项,加一条 `notes:["base64_images_stripped"]`,让 agent 有机会回退到 `--keep-base64-images`(若你打算加这个开关)。
- **§9 测试矩阵**:漏了 `test_cache_concurrency.py`(§11 R2 处置中提到的多进程 SQLite 压测)。要么补进矩阵,要么把 R2 处置改成"只做单进程,多进程视作未来工作"。
- **§12 PR 切片**:PR 5(jobs.py)和 PR 4(sitemap.py)的"可并行"标注成立,但 PR 6(crawl.py)依赖 PR 2/4/5,要等三者都 merge。建议在 PR 5 内提供一个 stub crawl 入口(只跑 1 页),让 PR 6 可以 incremental 推进,而不是等所有依赖到位再开工。

---

## 五、跟 v0.2 既有契约的兼容性核对

| 项 | 状态 |
|---|---|
| stdout 单 JSON / `cli._safe_run` 错误信封 | ✅ 文档 §3、§13 已声明遵守 |
| 测试全离线 / monkeypatch 模式 | ✅ §9 明确,且 fake clock 设计合理 |
| L1→L2→L3 自动升级、SSRF 守卫 | ✅ CrawlEngine 不下钻 Router,保持 §2 架构图所示 |
| `errors.py::ErrorCode` 集中 | ✅ §7 新增 9 个错误码,集中在同一处 |
| 不引入 MCP / daemon / 外部 broker | ✅ §13 明文不变量 |
| `~/.lightcrawl/dumps/` 迁入 cache | ⚠️ §8 选择"不自动迁移"——可以,但建议 `cache stats` 子命令报告"legacy dumps 占用 X MB,可手动 `rm` 释放",降低用户困惑 |
| `remove_base64_images` 默认翻转 | ⚠️ Breaking,但 v0.x 允许,且文档 §6 已明确 |

整体兼容性良好,没有破坏 v0.2 既有 7 个子命令的对外行为。

---

## 六、建议的修改优先级

1. **PR 1 之前**:A1(min_age 语义)、A2(cache key 包含 profile)、A3(三个 cache flag 的 truth table)→ 这些是接口形状决定,后期改成本高。
2. **PR 2 内**:B3(crawl 与 --no-cache 冲突解决方案,需写进 argparse)。
3. **PR 3 内**:B2(R1 探针不通过即推迟 ETag)。
4. **PR 5 内**:B1(claimed vs completed 拆分)、B4(job_id 加长)、B5(PID + start time 双重校验)。
5. **PR 6 内**:C2(robots 按 host)、C4(include/exclude 在未丢 query 的 URL 上跑)。
6. **PR 8 内**:C3、C5、C6(SKILL.md 与验收标准的描述精修)。

---

## 七、结论

文档已经达到"可拆 PR 开工"的精度,但需要在 PR 1 / PR 2 之前完成上述 3 项接口澄清(A1/A2/A3),并在 R4 的 visited 取舍上重新评估(B1)。其余修正可在对应 PR 内一并完成。

3.5 周 / 8 个 PR 的预算偏紧但可达成,前提是 R1 探针快速 go/no-go,不要为不通的 304 路径反复挣扎。
