from pathlib import Path

ROOT = Path.home() / ".refetch"
DUMPS = ROOT / "dumps"
PROFILES = ROOT / "profiles"
LOGS = ROOT / "logs"
SCREENSHOTS = ROOT / "screenshots"
CONFIG = ROOT / "config.toml"


def ensure_dirs() -> None:
    for d in (ROOT, DUMPS, PROFILES, LOGS, SCREENSHOTS):
        d.mkdir(parents=True, exist_ok=True)
        d.chmod(0o700)
