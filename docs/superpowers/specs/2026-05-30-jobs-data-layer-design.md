# PR 5 — `jobs.py` (crawl 数据层)

> v0.3 tracker #22 · design.md §5.4 · 2026-05-30

## 1. 范围与边界

`jobs.py` 是 crawl 的**持久化数据层**,不含任何 crawl 业务逻辑。它提供一个 `Job`
类管理 `~/.lightcrawl/jobs/<job_id>.*` 的全部六个文件,加上模块级的 reconcile /
PID 工具函数。

**纳入 PR 5:** `Job` 类(状态机 + 进度 + 六文件落盘)、`frontier.jsonl` 持久化
(push/pop/tombstone/compaction)、`reconcile_jobs` + PID 判活、`should_stop()`、
`JOB_NOT_FOUND` / `JOB_NOT_RESUMABLE` 错误码、psutil 硬依赖。

**不在 PR 5(留给 PR 6 `crawl.py`):** `install_signal_handlers`、BFS 主循环、
`.cancel` 文件的*写入*(由 `crawl-cancel` 子命令)、`crawl` / `crawl-status` /
`crawl-resume` / `crawl-cancel` / `jobs` 子命令。PR 5 只提供 `Job.should_stop()`
让上层轮询。

设计决定(与用户确认):
- PR 5 = 纯数据层(不含信号安装 / BFS / 子命令)。
- `frontier.jsonl` 纳入 PR 5 —— 它是 jobs/ 落盘文件,resume 不重抓必须靠它恢复
  待访问队列;`FrontierItem(url, depth)` 形状 design 已定,push/pop/compaction 是
  纯数据机制。
- psutil 作为硬运行时依赖现在加入(design review B5 否决了自实现 PID 判活)。
- `JOB_NOT_FOUND` / `JOB_NOT_RESUMABLE` 随 PR 5 一起加,在 jobs 层 load/resume
  校验里就地抛出,PR 6 子命令直接消费。

## 2. 数据模型

```python
def time_ms() -> int                    # 镜像 cache.py 的可 monkeypatch 时钟,
                                        # jobs.py 自有一份(模块解耦,不交叉 import cache)

class JobStatus(str, Enum):             # created running completed interrupted cancelled
class FrontierItem(NamedTuple):         # url: str, depth: int
class Progress(dataclass):              # pages_fetched/failed/pending/skipped_cache/
                                        #   skipped_robots/skipped_filter,全 int,默认 0

class Job:
    job_id, type, params: dict, status, started_at, updated_at,
    completed_at, progress: Progress, errors_tail: list[dict]  # 最多 50 条
    # 内存态:claimed: set[str], completed: set[str], _shutdown_reason: str | None
```

`job_id` 格式:`crawl-<utc_basic>-<uuid4hex12>`,例如
`crawl-20260518T143012-7af3b921c4d2`。不含 `:` 字符(Windows NTFS)。

## 3. 六个文件与各自的写盘纪律

| 文件 | 写法 | 时机 |
|------|------|------|
| `<id>.json` | `os.replace` 原子写 | 每 5s 或每 10 页(取早) |
| `<id>.pid` | `{pid, create_time}` 一次写 | 启动时 |
| `<id>.cancel` | 仅*检测*存在(PR 6 写) | — |
| `<id>.visited.txt` | append + `fsync`,每行 `(canonical, status, ts)` | 每条立即,不缓冲 |
| `<id>.frontier.jsonl` | append push / tombstone pop;1000 行 compaction | 每次 push/pop |
| `<id>.results.jsonl` | append + `fsync`,每页一行 | 每条立即 |

job JSON 瘦身:`visited` / `frontier` / `errors_full` 不放进 json;`errors_tail`
仅保留最近 50 条,完整错误日志在 `results.jsonl` 的 `ok=false` 行。10k 页 crawl 的
job JSON 始终 ~10KB 量级。

## 4. 状态机与关键方法

```
created → running → completed
                  ├→ interrupted   (进程消失 → reconcile 改写)
                  └→ cancelled      (.cancel 文件)
   interrupted ──crawl-resume──> running   (仅 interrupted 可 resume)
```

- `Job.create(type, params)` → 建目录、写 pid、status=running、flush
- `Job.load(job_id)` → 读 json;不存在抛 `FetchError(JOB_NOT_FOUND)`
- `Job.resume(job_id)` → load;若 `status != interrupted` 抛
  `FetchError(JOB_NOT_RESUMABLE)`;扫 `visited.txt` 把 `claimed - completed` 的 URL
  重新入 frontier,给瞬时失败第二次机会
- `mark_claimed(url)` / `mark_completed(url)` → 双 set + append visited.txt
- `record(result: dict)` → 成功 mark_completed + append results.jsonl;失败 append
  results.jsonl + push errors_tail(截 50)+ progress 计数
- `request_shutdown(reason)` → 置内存 flag(信号回调用,PR 6 装)
- `should_stop()` → `_shutdown_reason is not None` **or** `.cancel` 文件存在
- `finalize()` → 据 should_stop 原因定终态(completed / interrupted / cancelled)、
  flush、删 `.pid`

## 5. Reconcile / PID 判活(模块级函数)

用 psutil(跨平台一致,避开 fcntl/flock 与防病毒、OneDrive 同步目录的边角冲突):

```python
def write_pid_file(path) -> None              # {pid, create_time} JSON
def is_owner_alive(path) -> bool              # psutil.Process(pid).create_time 比对
def reconcile_jobs(jobs_dir=~/.lightcrawl/jobs) -> list[str]
   # 任何 lightcrawl CLI 启动时扫;status=running 但 is_owner_alive(.pid)==False 的,
   # 改写 status=interrupted。create_time 不匹配=原主已死(PID 复用免疫):即使新进程
   # 占用同一 PID 也不会误判。返回被改写的 job_id 列表。
```

## 6. 错误处理

- 数据层错误走既有 errors-as-values 边界:`Job.load/resume` 抛
  `FetchError(JOB_NOT_FOUND / JOB_NOT_RESUMABLE)`,由 PR 6 子命令的 `_safe_run` 转
  `ok:false`。
- 两个新错误码加进 `errors.py`(design §7),紧挨 `SITEMAP_PARSE_ERROR`。
- 文件读写损坏(json decode 失败、半截 visited 行)按 cache.py 的容错风格:跳过坏行
  而非崩溃,reconcile 对读不出的 pid 当作"主已死"。

## 7. 测试(`tests/test_jobs.py`,全离线)

`tmp_path` 作 jobs 目录 + monkeypatch `jobs.time_ms`(确定性时钟)+ mock
`psutil.Process`。覆盖:

- 状态机合法迁移 + 非法迁移拒绝
- flush 节奏:5s / 10 页两条触发线各自生效,中途崩溃后 json 仍可读
- `claimed` / `completed` 双 set 拆分;`record` 成功/失败分别落 visited + results
- resume:`claimed - completed` 重新入 frontier;`completed` 的不重抓;非 interrupted
  状态 → `JOB_NOT_RESUMABLE`;不存在 → `JOB_NOT_FOUND`
- frontier:push/pop 顺序、tombstone、1000 行 compaction、resume 后队列恢复
- PID+create_time:owner 活 / 死 / PID 复用(create_time 不匹配)三态;
  `reconcile_jobs` 把死 owner 的 running 改 interrupted
- `should_stop`:shutdown flag 与 `.cancel` 文件两条路径
- `finalize`:三种终态正确 + 删 `.pid`

## 8. 验证

- `pytest tests/test_jobs.py -q` 绿
- 全套零回归(482 → 约 500)
- `ruff check src/lightcrawl/jobs.py tests/test_jobs.py`
- psutil 进 `pyproject.toml` dependencies,`pip install -e ".[dev,bench]"` 重装确认
  导入可用

## 9. 下游(本 PR 不做)

- PR 6 `crawl.py`:BFS 主循环、`install_signal_handlers`、`.cancel` 写入、
  `crawl` / `crawl-status` / `crawl-resume` / `crawl-cancel` / `jobs` 子命令、
  per-host robots cache。
