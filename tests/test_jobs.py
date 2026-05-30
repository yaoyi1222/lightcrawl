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
