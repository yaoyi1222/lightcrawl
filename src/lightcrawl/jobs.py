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
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import psutil


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
