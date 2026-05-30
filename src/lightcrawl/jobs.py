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
CLI subcommands live in ``crawl.py`` (PR 6).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import psutil

from . import paths
from .errors import ErrorCode, FetchError


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
        job._load_visited()
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
