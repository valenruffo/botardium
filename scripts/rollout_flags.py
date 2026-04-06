import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

from scripts.runtime_paths import TMP_DIR

AUTH_MODE_ENV = "BOTARDIUM_AUTH_ROLLOUT_MODE"
PATH_MODE_ENV = "BOTARDIUM_PATH_CUTOVER_MODE"
DURABLE_JOBS_MODE_ENV = "BOTARDIUM_DURABLE_JOBS_MODE"
REQUIRE_BACKUP_ENV = "BOTARDIUM_REQUIRE_BACKUP_SNAPSHOT"

_VALID_MODES = {"shadow", "enforce"}
_TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RolloutFlags:
    auth_mode: str = "enforce"
    path_mode: str = "enforce"
    durable_jobs_mode: str = "enforce"
    require_backup_snapshot: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _parse_mode(raw_value: str | None, *, default: str) -> str:
    value = str(raw_value or "").strip().lower()
    if value in _VALID_MODES:
        return value
    return default


def _parse_bool(raw_value: str | None, *, default: bool) -> bool:
    value = str(raw_value or "").strip().lower()
    if not value:
        return default
    return value in _TRUE_VALUES


def get_rollout_flags() -> RolloutFlags:
    return RolloutFlags(
        auth_mode=_parse_mode(os.getenv(AUTH_MODE_ENV), default="enforce"),
        path_mode=_parse_mode(os.getenv(PATH_MODE_ENV), default="enforce"),
        durable_jobs_mode=_parse_mode(os.getenv(DURABLE_JOBS_MODE_ENV), default="enforce"),
        require_backup_snapshot=_parse_bool(os.getenv(REQUIRE_BACKUP_ENV), default=True),
    )


def latest_backup_snapshot(snapshot_root: Path | None = None) -> Path | None:
    root = snapshot_root or (TMP_DIR / "db_snapshots")
    if not root.exists():
        return None
    snapshots = [candidate for candidate in root.glob("*.db") if candidate.is_file()]
    if not snapshots:
        return None
    snapshots.sort(key=lambda candidate: candidate.stat().st_mtime, reverse=True)
    return snapshots[0]
