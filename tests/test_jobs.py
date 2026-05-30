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


import re  # noqa: E402

from lightcrawl import jobs  # noqa: E402
from lightcrawl.jobs import FrontierItem, JobStatus, Progress  # noqa: E402


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


from lightcrawl.errors import FetchError  # noqa: E402


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
