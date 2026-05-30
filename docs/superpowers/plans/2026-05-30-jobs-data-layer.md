# `jobs.py` Crawl Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `src/lightcrawl/jobs.py` — the persistent data layer for crawl jobs (state machine, six on-disk files, flush cadence, PID/create_time reconcile, cancel detection, resume), with zero crawl business logic.

**Architecture:** A `Job` class owns `~/.lightcrawl/jobs/<job_id>.*`. Job JSON is flushed atomically (tmp→`os.replace`) on a 5s/10-page throttle; `visited.txt` / `results.jsonl` append+fsync per record; `frontier.jsonl` is an append-only op log (push/pop) with 1000-line compaction. Module-level `write_pid_file` / `is_owner_alive` / `reconcile_jobs` use psutil for cross-platform liveness. Signal handlers, the BFS loop, `.cancel` *writing*, and CLI subcommands are out of scope (PR 6).

**Tech Stack:** Python 3.10+, psutil (new hard dep), stdlib `json`/`os`/`uuid`/`datetime`. Mirrors `cache.py` conventions (`time_ms()` fake-clock, atomic writes, skip-bad-lines fault tolerance). Tests: pytest, `tmp_path`, monkeypatched `jobs.time_ms`.

Spec: `docs/superpowers/specs/2026-05-30-jobs-data-layer-design.md` · design.md §5.4.

---

### Task 1: Foundation — psutil dep, `paths.JOBS`, error codes

**Files:**
- Modify: `pyproject.toml` (dependencies list, ~line 6-18)
- Modify: `src/lightcrawl/paths.py`
- Modify: `src/lightcrawl/errors.py:29` (after `SITEMAP_PARSE_ERROR`)
- Test: `tests/test_jobs.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_jobs.py`:

```python
"""Crawl job data-layer tests (v0.3 PR 5). Fully offline: tmp_path job dir,
monkeypatched ``jobs.time_ms`` fake clock, real psutil against the test process."""

from __future__ import annotations

import json

import pytest

from lightcrawl import paths
from lightcrawl.errors import ErrorCode


def test_job_error_codes_exist():
    assert ErrorCode.JOB_NOT_FOUND.value == "JOB_NOT_FOUND"
    assert ErrorCode.JOB_NOT_RESUMABLE.value == "JOB_NOT_RESUMABLE"


def test_paths_has_jobs_dir():
    assert paths.JOBS == paths.ROOT / "jobs"
    assert paths.JOBS in [paths.JOBS]  # referenced by ensure_dirs (see source)


def test_psutil_importable():
    import psutil  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_jobs.py -q`
Expected: FAIL — `AttributeError: JOB_NOT_FOUND` / `psutil` import error.

- [ ] **Step 3: Add psutil dependency**

In `pyproject.toml`, add to the `dependencies` list (after `"pypdf>=4.0",`):

```toml
    "psutil>=5.9",
```

Then install: `.venv/bin/pip install -e ".[dev,bench]"`

- [ ] **Step 4: Add `JOBS` path**

In `src/lightcrawl/paths.py`, add after the `CACHE_*` block:

```python
# v0.3 PR 5 — crawl job state. One file-set per job under jobs/<job_id>.*
# (json/pid/cancel/visited.txt/frontier.jsonl/results.jsonl). See design §5.4.
JOBS = ROOT / "jobs"
```

And add `JOBS` to the `ensure_dirs()` tuple:

```python
    for d in (
        ROOT, DUMPS, PROFILES, LOGS, SCREENSHOTS,
        CACHE_ROOT, CACHE_PAYLOADS, CACHE_DUMPS, CACHE_SCREENSHOTS,
        JOBS,
    ):
```

- [ ] **Step 5: Add error codes**

In `src/lightcrawl/errors.py`, after the `SITEMAP_PARSE_ERROR` line (`errors.py:29`):

```python
    # PR 5 — crawl jobs. Raised by the jobs data layer's load/resume
    # validation; PR 6's crawl-status/resume/cancel subcommands consume them.
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    JOB_NOT_RESUMABLE = "JOB_NOT_RESUMABLE"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_jobs.py -q`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/lightcrawl/paths.py src/lightcrawl/errors.py tests/test_jobs.py
git commit -m "feat(jobs): psutil dep + paths.JOBS + JOB_NOT_FOUND/RESUMABLE codes (PR 5)"
```

---

### Task 2: Module skeleton — clock, enums, dataclasses, `new_job_id`

**Files:**
- Create: `src/lightcrawl/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
import re

from lightcrawl import jobs
from lightcrawl.jobs import FrontierItem, JobStatus, Progress


def test_new_job_id_format_and_no_colon():
    jid = jobs.new_job_id()
    assert re.fullmatch(r"crawl-\d{8}T\d{6}-[0-9a-f]{12}", jid)
    assert ":" not in jid  # Windows NTFS safe


def test_progress_defaults_zero():
    p = Progress()
    assert (p.pages_fetched, p.pages_failed, p.pages_pending) == (0, 0, 0)
    assert (p.pages_skipped_cache, p.pages_skipped_robots, p.pages_skipped_filter) == (0, 0, 0)


def test_frontier_item_is_url_depth():
    it = FrontierItem("https://ex.com/a", 2)
    assert it.url == "https://ex.com/a" and it.depth == 2


def test_job_status_values():
    assert {s.value for s in JobStatus} == {
        "created", "running", "completed", "interrupted", "cancelled",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_jobs.py -q`
Expected: FAIL — `ModuleNotFoundError: lightcrawl.jobs`.

- [ ] **Step 3: Create the module skeleton**

Create `src/lightcrawl/jobs.py`:

```python
"""Crawl job persistence (v0.3 PR 5) — the data layer behind ``lightcrawl
crawl``. Owns ``~/.lightcrawl/jobs/<job_id>.*``; no crawl business logic.

Six files per job (design §5.4):
- ``<id>.json``        status + progress + errors_tail; 5s/10-page atomic flush
- ``<id>.pid``         {pid, create_time} for reconcile
- ``<id>.cancel``      existence = cancel request (written by PR 6, detected here)
- ``<id>.visited.txt`` append-only ``canonical\\tstatus\\tts`` (claimed/completed)
- ``<id>.frontier.jsonl`` append-only push/pop op log, 1000-line compaction
- ``<id>.results.jsonl``  one line per fetched page

Time reads go through ``time_ms()`` so tests can monkeypatch a fake clock,
mirroring ``cache.time_ms``. Signal handlers / BFS / ``.cancel`` writing /
CLI subcommands live in ``crawl.py`` (PR 6)."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import NamedTuple


def time_ms() -> int:
    """Unix time in milliseconds. All job time reads go through this so a
    monkeypatched ``jobs.time_ms`` drives a deterministic clock in tests."""
    return int(time.time() * 1000)


_FLUSH_INTERVAL_MS = 5_000
_FLUSH_EVERY_PAGES = 10
_ERRORS_TAIL_MAX = 50
_FRONTIER_COMPACT_THRESHOLD = 1000


class JobStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class FrontierItem(NamedTuple):
    url: str
    depth: int


@dataclass
class Progress:
    pages_fetched: int = 0
    pages_failed: int = 0
    pages_pending: int = 0
    pages_skipped_cache: int = 0
    pages_skipped_robots: int = 0
    pages_skipped_filter: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def new_job_id(prefix: str = "crawl") -> str:
    """``crawl-<utc_basic>-<uuid4hex12>`` — readable, time-sortable, no ``:``
    (Windows NTFS). 12 hex chars → ~1/2⁴⁸ collision (design B4)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{ts}-{uuid.uuid4().hex[:12]}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_jobs.py -q`
Expected: PASS (7 tests total).

- [ ] **Step 5: Commit**

```bash
git add src/lightcrawl/jobs.py tests/test_jobs.py
git commit -m "feat(jobs): module skeleton — clock, enums, Progress, new_job_id"
```

---

### Task 3: PID file helpers — `write_pid_file` / `is_owner_alive`

**Files:**
- Modify: `src/lightcrawl/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
def test_pid_file_roundtrip_alive(tmp_path):
    p = tmp_path / "x.pid"
    jobs.write_pid_file(p)
    assert jobs.is_owner_alive(p) is True  # written by this live process


def test_pid_missing_is_dead(tmp_path):
    assert jobs.is_owner_alive(tmp_path / "nope.pid") is False


def test_pid_corrupt_is_dead(tmp_path):
    p = tmp_path / "bad.pid"
    p.write_text("{not json")
    assert jobs.is_owner_alive(p) is False


def test_pid_create_time_mismatch_is_dead(tmp_path):
    # PID-reuse immunity: same pid, different create_time → original owner dead.
    import json as _json
    import psutil
    p = tmp_path / "reuse.pid"
    me = psutil.Process()
    p.write_text(_json.dumps({"pid": me.pid, "create_time": me.create_time() + 5.0}))
    assert jobs.is_owner_alive(p) is False


def test_pid_unknown_process_is_dead(tmp_path):
    import json as _json
    p = tmp_path / "ghost.pid"
    p.write_text(_json.dumps({"pid": 2_147_483_646, "create_time": 1.0}))
    assert jobs.is_owner_alive(p) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k pid`
Expected: FAIL — `AttributeError: write_pid_file`.

- [ ] **Step 3: Implement PID helpers**

Add to `src/lightcrawl/jobs.py` — extend the imports and append the helpers:

```python
import json
from pathlib import Path

import psutil
```

```python
def write_pid_file(path: Path) -> None:
    """Write ``{pid, create_time}`` for the current process. create_time is a
    cross-platform float (psutil), used to defeat PID reuse on reconcile."""
    me = psutil.Process()
    path.write_text(json.dumps({"pid": me.pid, "create_time": me.create_time()}))


def is_owner_alive(path: Path) -> bool:
    """True only if the pid in ``path`` is running AND its create_time matches
    (within 0.01s). Missing/corrupt file or NoSuchProcess → dead owner."""
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    try:
        proc = psutil.Process(int(data["pid"]))
        return abs(proc.create_time() - float(data["create_time"])) < 0.01
    except (psutil.NoSuchProcess, KeyError, ValueError, TypeError):
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k pid`
Expected: PASS (5 pid tests).

- [ ] **Step 5: Commit**

```bash
git add src/lightcrawl/jobs.py tests/test_jobs.py
git commit -m "feat(jobs): psutil PID+create_time liveness helpers"
```

---

### Task 4: `Job.create` + atomic JSON flush + `Job.load` + `JOB_NOT_FOUND`

**Files:**
- Modify: `src/lightcrawl/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
from lightcrawl.errors import FetchError


def test_create_writes_json_and_pid_running(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 1_000)
    job = jobs.Job.create("crawl", {"seed": "https://ex.com/"}, jobs_dir=tmp_path)
    assert job.status == JobStatus.RUNNING
    data = json.loads((tmp_path / f"{job.job_id}.json").read_text())
    assert data["status"] == "running"
    assert data["type"] == "crawl"
    assert data["params"] == {"seed": "https://ex.com/"}
    assert data["started_at"] == 1_000
    assert (tmp_path / f"{job.job_id}.pid").exists()


def test_load_roundtrips_progress_and_params(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 2_000)
    job = jobs.Job.create("crawl", {"seed": "https://ex.com/"}, jobs_dir=tmp_path)
    job.progress.pages_fetched = 7
    job.flush(force=True)
    loaded = jobs.Job.load(job.job_id, jobs_dir=tmp_path)
    assert loaded.progress.pages_fetched == 7
    assert loaded.params == {"seed": "https://ex.com/"}
    assert loaded.status == JobStatus.RUNNING


def test_load_missing_raises_job_not_found(tmp_path):
    with pytest.raises(FetchError) as ei:
        jobs.Job.load("crawl-nope", jobs_dir=tmp_path)
    assert ei.value.code == ErrorCode.JOB_NOT_FOUND


def test_flush_is_atomic_leaves_no_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 3_000)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.flush(force=True)
    assert not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k "create or load or flush"`
Expected: FAIL — `AttributeError: type object 'Job' has no attribute 'create'`.

- [ ] **Step 3: Implement `Job` create/flush/load**

Add to `src/lightcrawl/jobs.py` — extend imports and append the class:

```python
import os

from . import paths
from .errors import ErrorCode, FetchError
```

```python
class Job:
    def __init__(self, job_id: str, type: str, params: dict, *, jobs_dir: Path):
        self.job_id = job_id
        self.type = type
        self.params = params
        self.jobs_dir = jobs_dir
        self.status = JobStatus.CREATED
        self.started_at = time_ms()
        self.updated_at = self.started_at
        self.completed_at: int | None = None
        self.progress = Progress()
        self.errors_tail: list[dict] = []
        # In-memory state, hydrated from side files on load/resume.
        self.claimed: set[str] = set()
        self.completed: set[str] = set()
        self._frontier: list[FrontierItem] = []
        self._frontier_lines = 0
        self._shutdown_reason: str | None = None
        self._last_flush_ms = 0
        self._pages_since_flush = 0

    # -- file paths --------------------------------------------------------
    @property
    def json_path(self) -> Path:
        return self.jobs_dir / f"{self.job_id}.json"

    @property
    def pid_path(self) -> Path:
        return self.jobs_dir / f"{self.job_id}.pid"

    @property
    def cancel_path(self) -> Path:
        return self.jobs_dir / f"{self.job_id}.cancel"

    @property
    def visited_path(self) -> Path:
        return self.jobs_dir / f"{self.job_id}.visited.txt"

    @property
    def frontier_path(self) -> Path:
        return self.jobs_dir / f"{self.job_id}.frontier.jsonl"

    @property
    def results_path(self) -> Path:
        return self.jobs_dir / f"{self.job_id}.results.jsonl"

    # -- lifecycle ---------------------------------------------------------
    @classmethod
    def create(cls, type: str, params: dict, *, jobs_dir: Path | None = None) -> "Job":
        jobs_dir = jobs_dir or paths.JOBS
        jobs_dir.mkdir(parents=True, exist_ok=True)
        job = cls(new_job_id(), type, params, jobs_dir=jobs_dir)
        job.status = JobStatus.RUNNING
        write_pid_file(job.pid_path)
        job.flush(force=True)
        return job

    @classmethod
    def load(cls, job_id: str, *, jobs_dir: Path | None = None) -> "Job":
        jobs_dir = jobs_dir or paths.JOBS
        json_path = jobs_dir / f"{job_id}.json"
        try:
            data = json.loads(json_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise FetchError(ErrorCode.JOB_NOT_FOUND, f"{job_id}: {e}") from e
        job = cls(data["job_id"], data["type"], data.get("params", {}), jobs_dir=jobs_dir)
        job.status = JobStatus(data["status"])
        job.started_at = data.get("started_at", job.started_at)
        job.updated_at = data.get("updated_at", job.updated_at)
        job.completed_at = data.get("completed_at")
        job.progress = Progress(**data.get("progress", {}))
        job.errors_tail = data.get("errors_tail", [])
        return job

    # -- flush -------------------------------------------------------------
    def _to_json(self) -> dict:
        return {
            "job_id": self.job_id,
            "type": self.type,
            "params": self.params,
            "status": self.status.value,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "progress": self.progress.to_dict(),
            "errors_tail": self.errors_tail,
        }

    def flush(self, *, force: bool = False) -> None:
        """Atomic ``os.replace`` write of the job JSON, throttled to 5s OR 10
        pages (whichever first) unless ``force``. ``pages_pending`` is derived
        from the live frontier so callers don't have to track it."""
        now = time_ms()
        if not force and (
            now - self._last_flush_ms < _FLUSH_INTERVAL_MS
            and self._pages_since_flush < _FLUSH_EVERY_PAGES
        ):
            return
        self.updated_at = now
        self.progress.pages_pending = len(self._frontier)
        encoded = json.dumps(self._to_json(), ensure_ascii=False).encode("utf-8")
        tmp = self.json_path.with_suffix(".json.tmp")
        tmp.write_bytes(encoded)
        os.replace(tmp, self.json_path)
        self._last_flush_ms = now
        self._pages_since_flush = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k "create or load or flush"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lightcrawl/jobs.py tests/test_jobs.py
git commit -m "feat(jobs): Job.create/load + atomic throttled JSON flush"
```

---

### Task 5: Flush cadence — 5s OR 10 pages

**Files:**
- Modify: `src/lightcrawl/jobs.py` (no change expected — verify Task 4 logic)
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
def test_flush_throttle_suppresses_until_due(tmp_path, monkeypatch):
    clock = {"t": 10_000}
    monkeypatch.setattr(jobs, "time_ms", lambda: clock["t"])
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)  # force flush at 10_000
    first = json.loads(job.json_path.read_text())["updated_at"]
    assert first == 10_000
    # 2s later, 0 pages → throttled, no rewrite
    clock["t"] = 12_000
    job.flush()
    assert json.loads(job.json_path.read_text())["updated_at"] == 10_000
    # 5s after last flush → time threshold fires
    clock["t"] = 15_000
    job.flush()
    assert json.loads(job.json_path.read_text())["updated_at"] == 15_000


def test_flush_pages_threshold_fires(tmp_path, monkeypatch):
    clock = {"t": 0}
    monkeypatch.setattr(jobs, "time_ms", lambda: clock["t"])
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    # 9 pages within the time window → still throttled
    job._pages_since_flush = 9
    clock["t"] = 1_000
    job.flush()
    assert json.loads(job.json_path.read_text())["updated_at"] == 0
    # 10th page → page threshold fires even though <5s elapsed
    job._pages_since_flush = 10
    job.flush()
    assert json.loads(job.json_path.read_text())["updated_at"] == 1_000
```

- [ ] **Step 2: Run test to verify it passes (logic already in Task 4)**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k "throttle or threshold"`
Expected: PASS. (If FAIL, the throttle condition in `flush()` is wrong — re-check the `and` in Task 4 Step 3.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_jobs.py
git commit -m "test(jobs): pin 5s/10-page flush cadence"
```

---

### Task 6: Visited two-set — `mark_claimed` / `mark_completed` + hydrate

**Files:**
- Modify: `src/lightcrawl/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
def test_mark_claimed_then_completed_sets_and_file(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.mark_claimed("https://ex.com/a")
    job.mark_completed("https://ex.com/a")
    assert "https://ex.com/a" in job.claimed
    assert "https://ex.com/a" in job.completed
    lines = job.visited_path.read_text().splitlines()
    assert lines[0].split("\t")[:2] == ["https://ex.com/a", "claimed"]
    assert lines[1].split("\t")[:2] == ["https://ex.com/a", "completed"]


def test_load_hydrates_visited_sets(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.mark_claimed("https://ex.com/a")
    job.mark_claimed("https://ex.com/b")
    job.mark_completed("https://ex.com/a")
    loaded = jobs.Job.load(job.job_id, jobs_dir=tmp_path)
    assert loaded.claimed == {"https://ex.com/a", "https://ex.com/b"}
    assert loaded.completed == {"https://ex.com/a"}


def test_load_skips_corrupt_visited_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.mark_claimed("https://ex.com/a")
    with job.visited_path.open("a") as f:
        f.write("garbage-no-tabs\n")
    loaded = jobs.Job.load(job.job_id, jobs_dir=tmp_path)
    assert loaded.claimed == {"https://ex.com/a"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k visited`
Expected: FAIL — `AttributeError: 'Job' object has no attribute 'mark_claimed'`.

- [ ] **Step 3: Implement visited helpers + hydration**

Add to `src/lightcrawl/jobs.py` inside `Job` (after `flush`):

```python
    # -- visited (append-only, claimed/completed two-state) ----------------
    def _append_visited(self, url: str, status: str) -> None:
        with self.visited_path.open("a", encoding="utf-8") as f:
            f.write(f"{url}\t{status}\t{time_ms()}\n")
            f.flush()
            os.fsync(f.fileno())

    def mark_claimed(self, url: str) -> None:
        self.claimed.add(url)
        self._append_visited(url, "claimed")

    def mark_completed(self, url: str) -> None:
        self.completed.add(url)
        self._append_visited(url, "completed")

    def _load_visited(self) -> None:
        if not self.visited_path.exists():
            return
        for line in self.visited_path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue  # skip half-written / corrupt line
            url, status = parts[0], parts[1]
            if status == "claimed":
                self.claimed.add(url)
            elif status == "completed":
                self.completed.add(url)
```

In `Job.load`, hydrate before returning. Change the end of `load` from `return job` to:

```python
        job._load_visited()
        return job
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k visited`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lightcrawl/jobs.py tests/test_jobs.py
git commit -m "feat(jobs): visited.txt claimed/completed two-set + hydration"
```

---

### Task 7: `record` — results.jsonl + progress + errors_tail

**Files:**
- Modify: `src/lightcrawl/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
def test_record_success_marks_completed_and_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.record({"ok": True, "url": "https://ex.com/a",
                "metadata": {"status_code": 200}, "cache_hit": True})
    assert job.progress.pages_fetched == 1
    assert "https://ex.com/a" in job.completed
    line = json.loads(job.results_path.read_text().splitlines()[0])
    assert line["ok"] is True and line["cache_hit"] is True and line["status"] == 200


def test_record_failure_counts_and_tails_error(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.record({"ok": False, "url": "https://ex.com/x", "error_code": "TIMEOUT"})
    assert job.progress.pages_failed == 1
    assert "https://ex.com/x" not in job.completed
    assert job.errors_tail[-1]["error_code"] == "TIMEOUT"
    line = json.loads(job.results_path.read_text().splitlines()[0])
    assert line["ok"] is False and line["error_code"] == "TIMEOUT"


def test_errors_tail_capped_at_50(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    for i in range(60):
        job.record({"ok": False, "url": f"https://ex.com/{i}", "error_code": "TIMEOUT"})
    assert len(job.errors_tail) == 50
    assert job.errors_tail[-1]["url"] == "https://ex.com/59"
    assert job.progress.pages_failed == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k record`
Expected: FAIL — `AttributeError: 'Job' object has no attribute 'record'`.

- [ ] **Step 3: Implement `record`**

Add to `src/lightcrawl/jobs.py` inside `Job` (after the visited block):

```python
    # -- results -----------------------------------------------------------
    def record(self, result: dict) -> None:
        """Persist one fetch outcome: append to results.jsonl, update the
        claimed/completed set + progress counters, and (on failure) push a
        capped errors_tail entry. Triggers a throttled flush."""
        url = result.get("final_url") or result.get("url") or ""
        ok = bool(result.get("ok"))
        now = time_ms()
        line = {
            "url": url,
            "ok": ok,
            "status": (result.get("metadata") or {}).get("status_code") if ok else None,
            "error_code": result.get("error_code"),
            "cache_hit": bool(result.get("cache_hit")),
            "fetched_at": now,
        }
        with self.results_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        if ok:
            self.mark_completed(url)
            self.progress.pages_fetched += 1
        else:
            self.progress.pages_failed += 1
            self.errors_tail.append(
                {"url": url, "error_code": result.get("error_code"), "at": now}
            )
            if len(self.errors_tail) > _ERRORS_TAIL_MAX:
                self.errors_tail = self.errors_tail[-_ERRORS_TAIL_MAX:]
        self._pages_since_flush += 1
        self.flush()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k record`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lightcrawl/jobs.py tests/test_jobs.py
git commit -m "feat(jobs): record() — results.jsonl + progress + capped errors_tail"
```

---

### Task 8: Frontier — push/pop op log + tombstone + compaction + hydrate

**Files:**
- Modify: `src/lightcrawl/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
def test_frontier_push_pop_fifo(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.push_frontier(FrontierItem("https://ex.com/a", 0))
    job.push_frontier(FrontierItem("https://ex.com/b", 1))
    assert job.pop_frontier() == FrontierItem("https://ex.com/a", 0)
    assert job.pop_frontier() == FrontierItem("https://ex.com/b", 1)
    assert job.pop_frontier() is None


def test_frontier_hydrates_after_load(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.push_frontier(FrontierItem("https://ex.com/a", 0))
    job.push_frontier(FrontierItem("https://ex.com/b", 1))
    job.pop_frontier()  # consume a → only b remains
    job.push_frontier(FrontierItem("https://ex.com/c", 2))
    loaded = jobs.Job.load(job.job_id, jobs_dir=tmp_path)
    assert [it.url for it in loaded._frontier] == ["https://ex.com/b", "https://ex.com/c"]


def test_frontier_compacts_past_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    monkeypatch.setattr(jobs, "_FRONTIER_COMPACT_THRESHOLD", 10)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    for i in range(8):
        job.push_frontier(FrontierItem(f"https://ex.com/{i}", 0))
    for _ in range(6):
        job.pop_frontier()  # 8 push + 6 pop = 14 ops > 10 → compaction triggered
    # After compaction the file holds only the 2 surviving items as push lines.
    lines = job.frontier_path.read_text().splitlines()
    assert len(lines) == 2
    assert all(json.loads(line)["op"] == "push" for line in lines)
    loaded = jobs.Job.load(job.job_id, jobs_dir=tmp_path)
    assert [it.url for it in loaded._frontier] == ["https://ex.com/6", "https://ex.com/7"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k frontier`
Expected: FAIL — `AttributeError: 'Job' object has no attribute 'push_frontier'`.

- [ ] **Step 3: Implement frontier**

Add to `src/lightcrawl/jobs.py` inside `Job` (after the results block):

```python
    # -- frontier (append-only push/pop op log, periodic compaction) -------
    def _append_frontier_op(self, op: dict) -> None:
        with self.frontier_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(op) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._frontier_lines += 1
        if self._frontier_lines > _FRONTIER_COMPACT_THRESHOLD:
            self._compact_frontier()

    def push_frontier(self, item: FrontierItem) -> None:
        self._frontier.append(item)
        self._append_frontier_op({"op": "push", "url": item.url, "depth": item.depth})

    def pop_frontier(self) -> FrontierItem | None:
        if not self._frontier:
            return None
        item = self._frontier.pop(0)
        self._append_frontier_op({"op": "pop"})
        return item

    def _compact_frontier(self) -> None:
        """Rewrite the op log as one push line per surviving item (atomic)."""
        tmp = self.frontier_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for it in self._frontier:
                f.write(json.dumps({"op": "push", "url": it.url, "depth": it.depth}) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.frontier_path)
        self._frontier_lines = len(self._frontier)

    def _load_frontier(self) -> None:
        if not self.frontier_path.exists():
            return
        for line in self.frontier_path.read_text(encoding="utf-8").splitlines():
            try:
                op = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip half-written line
            self._frontier_lines += 1
            if op.get("op") == "push":
                self._frontier.append(FrontierItem(op["url"], op.get("depth", 0)))
            elif op.get("op") == "pop" and self._frontier:
                self._frontier.pop(0)
```

In `Job.load`, hydrate the frontier too. Change the tail of `load` to:

```python
        job._load_visited()
        job._load_frontier()
        return job
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k frontier`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lightcrawl/jobs.py tests/test_jobs.py
git commit -m "feat(jobs): durable frontier — push/pop op log + compaction + hydrate"
```

---

### Task 9: `resume` — re-enqueue claimed-minus-completed + `JOB_NOT_RESUMABLE`

**Files:**
- Modify: `src/lightcrawl/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
def test_resume_requires_interrupted_status(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)  # status running
    with pytest.raises(FetchError) as ei:
        jobs.Job.resume(job.job_id, jobs_dir=tmp_path)
    assert ei.value.code == ErrorCode.JOB_NOT_RESUMABLE


def test_resume_missing_job_raises_not_found(tmp_path):
    with pytest.raises(FetchError) as ei:
        jobs.Job.resume("crawl-nope", jobs_dir=tmp_path)
    assert ei.value.code == ErrorCode.JOB_NOT_FOUND


def test_resume_reenqueues_claimed_not_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.mark_claimed("https://ex.com/a")
    job.mark_completed("https://ex.com/a")  # done
    job.mark_claimed("https://ex.com/b")     # claimed but never completed
    job.status = JobStatus.INTERRUPTED
    job.flush(force=True)
    resumed = jobs.Job.resume(job.job_id, jobs_dir=tmp_path)
    assert resumed.status == JobStatus.RUNNING
    urls = [it.url for it in resumed._frontier]
    assert "https://ex.com/b" in urls
    assert "https://ex.com/a" not in urls
    assert (tmp_path / f"{job.job_id}.pid").exists()  # fresh owner pid


def test_resume_does_not_double_enqueue_existing_frontier(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.push_frontier(FrontierItem("https://ex.com/b", 0))  # already pending
    job.mark_claimed("https://ex.com/b")
    job.status = JobStatus.INTERRUPTED
    job.flush(force=True)
    resumed = jobs.Job.resume(job.job_id, jobs_dir=tmp_path)
    assert [it.url for it in resumed._frontier].count("https://ex.com/b") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k resume`
Expected: FAIL — `AttributeError: type object 'Job' has no attribute 'resume'`.

- [ ] **Step 3: Implement `resume`**

Add to `src/lightcrawl/jobs.py` inside `Job` (after `load`):

```python
    @classmethod
    def resume(cls, job_id: str, *, jobs_dir: Path | None = None) -> "Job":
        """Reopen an ``interrupted`` job: re-enqueue every URL that was claimed
        but never completed (second chance for transient failures), claim a
        fresh owner pid, and set status running. Non-interrupted → not
        resumable; absent → not found (both via ``load``)."""
        job = cls.load(job_id, jobs_dir=jobs_dir)
        if job.status != JobStatus.INTERRUPTED:
            raise FetchError(
                ErrorCode.JOB_NOT_RESUMABLE,
                f"{job_id}: status is {job.status.value}, only 'interrupted' resumes",
            )
        pending = {it.url for it in job._frontier}
        for url in job.claimed - job.completed:
            if url not in pending:
                job.push_frontier(FrontierItem(url, 0))
        job.status = JobStatus.RUNNING
        write_pid_file(job.pid_path)
        job.flush(force=True)
        return job
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k resume`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lightcrawl/jobs.py tests/test_jobs.py
git commit -m "feat(jobs): resume — re-enqueue claimed-not-completed + status guards"
```

---

### Task 10: Control — `request_shutdown` / `should_stop` / `finalize`

**Files:**
- Modify: `src/lightcrawl/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
def test_should_stop_on_shutdown_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    assert job.should_stop() is False
    job.request_shutdown("interrupted")
    assert job.should_stop() is True


def test_should_stop_on_cancel_file(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.cancel_path.write_text("")
    assert job.should_stop() is True


def test_finalize_completed_removes_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 9)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.finalize()
    assert job.status == JobStatus.COMPLETED
    assert job.completed_at == 9
    assert not job.pid_path.exists()
    assert json.loads(job.json_path.read_text())["status"] == "completed"


def test_finalize_interrupted_on_shutdown(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 9)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.request_shutdown("interrupted")
    job.finalize()
    assert job.status == JobStatus.INTERRUPTED


def test_finalize_cancelled_when_cancel_file_present(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 9)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.cancel_path.write_text("")
    job.finalize()
    assert job.status == JobStatus.CANCELLED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k "should_stop or finalize"`
Expected: FAIL — `AttributeError: 'Job' object has no attribute 'request_shutdown'`.

- [ ] **Step 3: Implement control methods**

Add to `src/lightcrawl/jobs.py` inside `Job` (after `resume`):

```python
    # -- control -----------------------------------------------------------
    def request_shutdown(self, reason: str) -> None:
        """Set by a signal handler (PR 6) or cancel path. ``reason`` is one of
        'interrupted' / 'cancelled'; the main loop polls ``should_stop``."""
        self._shutdown_reason = reason

    def should_stop(self) -> bool:
        return self._shutdown_reason is not None or self.cancel_path.exists()

    def finalize(self) -> None:
        """Resolve the terminal status, flush, and drop the pid file. A present
        ``.cancel`` file (remote cancel) wins over a SIGINT shutdown reason."""
        if self.cancel_path.exists() or self._shutdown_reason == "cancelled":
            self.status = JobStatus.CANCELLED
        elif self._shutdown_reason == "interrupted":
            self.status = JobStatus.INTERRUPTED
        else:
            self.status = JobStatus.COMPLETED
        self.completed_at = time_ms()
        self.flush(force=True)
        try:
            self.pid_path.unlink()
        except FileNotFoundError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k "should_stop or finalize"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lightcrawl/jobs.py tests/test_jobs.py
git commit -m "feat(jobs): request_shutdown/should_stop/finalize terminal states"
```

---

### Task 11: `reconcile_jobs` — dead-owner running → interrupted

**Files:**
- Modify: `src/lightcrawl/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
def test_reconcile_flips_dead_owner_to_interrupted(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    # Simulate the owner having died: corrupt the create_time in its pid file.
    me = json.loads(job.pid_path.read_text())
    me["create_time"] = me["create_time"] + 999.0
    job.pid_path.write_text(json.dumps(me))
    flipped = jobs.reconcile_jobs(jobs_dir=tmp_path)
    assert job.job_id in flipped
    assert json.loads(job.json_path.read_text())["status"] == "interrupted"


def test_reconcile_leaves_live_owner_running(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)  # pid = live test process
    flipped = jobs.reconcile_jobs(jobs_dir=tmp_path)
    assert job.job_id not in flipped
    assert json.loads(job.json_path.read_text())["status"] == "running"


def test_reconcile_ignores_terminal_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "time_ms", lambda: 5)
    job = jobs.Job.create("crawl", {}, jobs_dir=tmp_path)
    job.finalize()  # completed, pid removed
    flipped = jobs.reconcile_jobs(jobs_dir=tmp_path)
    assert flipped == []
    assert json.loads(job.json_path.read_text())["status"] == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k reconcile`
Expected: FAIL — `AttributeError: module 'lightcrawl.jobs' has no attribute 'reconcile_jobs'`.

- [ ] **Step 3: Implement `reconcile_jobs`**

Add to `src/lightcrawl/jobs.py` at module level (after `is_owner_alive`):

```python
def reconcile_jobs(jobs_dir: Path | None = None) -> list[str]:
    """Scan ``jobs_dir`` at CLI startup: any job still marked ``running`` whose
    pid-file owner is no longer alive is rewritten to ``interrupted``. Returns
    the list of job_ids flipped. create_time matching makes this immune to PID
    reuse (a recycled pid is treated as a dead original owner)."""
    jobs_dir = jobs_dir or paths.JOBS
    if not jobs_dir.exists():
        return []
    flipped: list[str] = []
    for json_path in jobs_dir.glob("*.json"):
        try:
            data = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("status") != JobStatus.RUNNING.value:
            continue
        pid_path = json_path.with_suffix("").with_suffix(".pid")
        if is_owner_alive(pid_path):
            continue
        data["status"] = JobStatus.INTERRUPTED.value
        data["updated_at"] = time_ms()
        tmp = json_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        os.replace(tmp, json_path)
        flipped.append(data["job_id"])
    return flipped
```

> Note on the pid path: `<job_id>.json` → `<job_id>.pid`. `Path("crawl-x.json").with_suffix("")` yields `crawl-x`, then `.with_suffix(".pid")` → `crawl-x.pid`. job_ids contain no other dots, so this is exact.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_jobs.py -q -k reconcile`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lightcrawl/jobs.py tests/test_jobs.py
git commit -m "feat(jobs): reconcile_jobs — dead-owner running→interrupted"
```

---

### Task 12: Full-suite gate + lint + install verify

**Files:**
- None (verification only)

- [ ] **Step 1: Run the jobs suite**

Run: `.venv/bin/pytest tests/test_jobs.py -q`
Expected: PASS (all ~40 jobs tests).

- [ ] **Step 2: Run the full suite for regressions**

Run: `.venv/bin/pytest -q`
Expected: PASS, ~500 tests, zero failures. (482 pre-PR-5 + the new jobs tests.)

- [ ] **Step 3: Lint**

Run: `.venv/bin/ruff check src/lightcrawl/jobs.py src/lightcrawl/paths.py src/lightcrawl/errors.py tests/test_jobs.py`
Expected: `All checks passed!`

- [ ] **Step 4: Confirm psutil is a declared dep and importable**

Run: `.venv/bin/python -c "import psutil, lightcrawl.jobs; print('ok', psutil.__version__)"`
Expected: prints `ok <version>`.

- [ ] **Step 5: Final commit (if any cleanup) + ready for PR**

```bash
git status   # expect clean
```

No code changes expected here; PR creation happens only when the user asks.

---

## Self-Review

**Spec coverage:**
- §1 scope/boundary → Tasks 1-11 build only the data layer; signal handlers/BFS/.cancel-write/subcommands explicitly excluded (header + Task 9/10 notes). ✓
- §2 data model (`time_ms`, `JobStatus`, `FrontierItem`, `Progress`, `Job` fields) → Task 2 + Task 4. ✓
- §3 six files + write disciplines (atomic json, fsync append, frontier op-log+compaction) → Tasks 4/6/7/8. ✓
- §4 state machine + methods (create/load/resume/mark_*/record/request_shutdown/should_stop/finalize) → Tasks 4/6/7/9/10. ✓
- §5 reconcile + PID helpers → Tasks 3/11. ✓
- §6 error handling (JOB_NOT_FOUND/RESUMABLE, skip-bad-lines) → Tasks 1/4/6/8/9 + corrupt-line tests. ✓
- §7 tests (state machine, flush cadence, PID reconcile, cancel, claimed/completed, resume-no-refetch, frontier) → Tasks 5/6/8/9/10/11. ✓
- §8 verification → Task 12. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `FrontierItem(url, depth)`, `Progress` field names, `JobStatus` members, and method names (`mark_claimed`/`mark_completed`/`push_frontier`/`pop_frontier`/`record`/`should_stop`/`finalize`/`reconcile_jobs`) are used identically across tasks. `flush(*, force=False)` signature consistent. ✓

**Note:** `pages_skipped_*` counters are public mutable fields on `Progress`; PR 6's crawl loop bumps them directly (no setter added — YAGNI for the data layer). `pages_pending` is derived in `flush()` from the live frontier.
