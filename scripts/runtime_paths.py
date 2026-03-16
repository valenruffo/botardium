import os
import sys
import shutil
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("botardium.runtime_paths")

SOURCE_ROOT = Path(__file__).resolve().parent.parent
IS_FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)) if IS_FROZEN else SOURCE_ROOT
APP_DATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "Botardium"
WRITABLE_ROOT = APP_DATA_DIR if IS_FROZEN else SOURCE_ROOT

DB_DIR = WRITABLE_ROOT / "database"
LEGACY_DB_PATHS = [
    SOURCE_ROOT / "database" / "primebot.db",
    SOURCE_ROOT / "database" / "botardium.db",
    WRITABLE_ROOT / "database" / "primebot.db",
]
DB_PATH = DB_DIR / "botardium.db"
LEGACY_DB_PATH = DB_DIR / "primebot.db"

for legacy_path in LEGACY_DB_PATHS:
    if legacy_path.exists() and not DB_PATH.exists():
        DB_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_path), str(DB_PATH))
        logger.info(f"Migrated legacy database from {legacy_path} to {DB_PATH}")
        break

TMP_DIR = WRITABLE_ROOT / ".tmp"
CONFIG_DIR = WRITABLE_ROOT / "config"
EXPORTS_TMP_DIR = TMP_DIR / "workspace_exports"
IMPORTS_TMP_DIR = TMP_DIR / "workspace_imports"
SESSIONS_DIR = (WRITABLE_ROOT / "sessions") if IS_FROZEN else (SOURCE_ROOT / ".agents" / "sessions")
PROFILE_PATH = TMP_DIR / "account_profile.json"
ENV_PATH = WRITABLE_ROOT / ".env"
ENV_EXAMPLE_PATH = BUNDLE_ROOT / ".env.example"
RUNTIME_SECRETS_PATH = CONFIG_DIR / "runtime_secrets.json"
DIRECTIVAS_DIR = BUNDLE_ROOT / "directivas"
MEMORIA_PATH = DIRECTIVAS_DIR / "memoria_maestra.md"
SKILLS_DIR = BUNDLE_ROOT / ".agents" / "skills"
AGENTS_DIR = BUNDLE_ROOT / ".agents"
LOG_DIR = TMP_DIR / "logs"
SESSION_CREDENTIALS_DIR = WRITABLE_ROOT / "session_credentials"


def ensure_runtime_dirs() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_TMP_DIR.mkdir(parents=True, exist_ok=True)
    IMPORTS_TMP_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)


ensure_runtime_dirs()


def get_path_discovery_report() -> Dict[str, Any]:
    """Generate a one-time reconciliation report showing all discovered DB/session paths."""
    report = {
        "authoritative_db_path": str(DB_PATH),
        "authoritative_db_exists": DB_PATH.exists(),
        "authoritative_session_dir": str(SESSIONS_DIR),
        "legacy_db_paths_checked": [str(p) for p in LEGACY_DB_PATHS],
        "discovered_databases": [],
        "discovered_sessions": [],
        "path_divergence_detected": False,
    }

    for legacy_path in LEGACY_DB_PATHS:
        if legacy_path.exists() and legacy_path != DB_PATH:
            report["discovered_databases"].append({
                "path": str(legacy_path),
                "size_bytes": legacy_path.stat().st_size,
                "status": "migrated" if DB_PATH.exists() else "unprocessed",
            })
            report["path_divergence_detected"] = True

    session_search_roots = [WRITABLE_ROOT, SOURCE_ROOT / ".agents", SOURCE_ROOT]
    for search_root in session_search_roots:
        if search_root.exists():
            for candidate in search_root.rglob("*"):
                if candidate.is_dir() and "session" in candidate.name.lower():
                    if candidate != SESSIONS_DIR:
                        report["discovered_sessions"].append(str(candidate))
                        report["path_divergence_detected"] = True

    return report


def create_rollback_snapshot(snapshot_name: Optional[str] = None) -> Optional[Path]:
    """Create a rollback snapshot of the current DB for safety before migrations."""
    if not DB_PATH.exists():
        logger.warning("No DB found to snapshot")
        return None

    snapshot_dir = TMP_DIR / "db_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    if snapshot_name is None:
        from datetime import datetime
        snapshot_name = f"pre_migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    snapshot_path = snapshot_dir / f"{snapshot_name}.db"
    shutil.copy2(str(DB_PATH), str(snapshot_path))
    logger.info(f"Created DB snapshot at {snapshot_path}")

    metadata_path = snapshot_dir / f"{snapshot_name}_metadata.json"
    with open(metadata_path, "w") as f:
        json.dump({
            "snapshot_name": snapshot_name,
            "source_db_path": str(DB_PATH),
            "snapshot_path": str(snapshot_path),
            "source_size_bytes": DB_PATH.stat().st_size,
        }, f, indent=2)

    return snapshot_path


def verify_path_convergence() -> Dict[str, Any]:
    """Verify that all components would resolve to the same authoritative paths."""
    result = {
        "converged": True,
        "db_path_resolution": str(DB_PATH),
        "session_dir_resolution": str(SESSIONS_DIR),
        "tmp_dir_resolution": str(TMP_DIR),
        "config_dir_resolution": str(CONFIG_DIR),
        "logs_dir_resolution": str(LOG_DIR),
        "issues": [],
    }

    if DB_PATH.exists():
        result["db_exists"] = True
        result["db_size_bytes"] = DB_PATH.stat().st_size
    else:
        result["db_exists"] = False
        result["issues"].append("Authoritative DB does not exist")

    if not SESSIONS_DIR.exists():
        result["issues"].append("Sessions directory not created")
        result["converged"] = False

    return result
