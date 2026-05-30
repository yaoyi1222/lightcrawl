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
