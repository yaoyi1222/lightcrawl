from pathlib import Path

ROOT = Path.home() / ".lightcrawl"
DUMPS = ROOT / "dumps"
PROFILES = ROOT / "profiles"
LOGS = ROOT / "logs"
SCREENSHOTS = ROOT / "screenshots"
CONFIG = ROOT / "config.toml"

# v0.3 PR 2.2 — local fetch cache. See docs/v0.3/design.md §5.2 and §8.
# Co-located under ROOT so a single ~/.lightcrawl/ directory keeps all
# user-visible state. ``DUMPS`` above is the legacy v0.2 path; v0.3
# writes dumps under ``CACHE_DUMPS`` instead. cache.legacy_dumps_usage()
# reports the old directory's size so users can ``rm`` it.
CACHE_ROOT = ROOT / "cache"
CACHE_INDEX_DB = CACHE_ROOT / "index.sqlite"
CACHE_PAYLOADS = CACHE_ROOT / "payloads"
CACHE_DUMPS = CACHE_ROOT / "dumps"
CACHE_SCREENSHOTS = CACHE_ROOT / "screenshots"

# v0.3 PR 5 — crawl job state. One file-set per job under jobs/<job_id>.*
# (json/pid/cancel/visited.txt/frontier.jsonl/results.jsonl). See design §5.4.
JOBS = ROOT / "jobs"


def ensure_dirs() -> None:
    for d in (
        ROOT, DUMPS, PROFILES, LOGS, SCREENSHOTS,
        CACHE_ROOT, CACHE_PAYLOADS, CACHE_DUMPS, CACHE_SCREENSHOTS,
        JOBS,
    ):
        d.mkdir(parents=True, exist_ok=True)
        d.chmod(0o700)
