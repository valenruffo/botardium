import os
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent.parent
IS_FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)) if IS_FROZEN else SOURCE_ROOT
APP_DATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "Botardium"
WRITABLE_ROOT = APP_DATA_DIR if IS_FROZEN else SOURCE_ROOT

DB_DIR = WRITABLE_ROOT / "database"
TMP_DIR = WRITABLE_ROOT / ".tmp"
SESSIONS_DIR = (WRITABLE_ROOT / "sessions") if IS_FROZEN else (SOURCE_ROOT / ".agents" / "sessions")
PROFILE_PATH = TMP_DIR / "account_profile.json"
ENV_PATH = WRITABLE_ROOT / ".env"
ENV_EXAMPLE_PATH = BUNDLE_ROOT / ".env.example"
DIRECTIVAS_DIR = BUNDLE_ROOT / "directivas"
MEMORIA_PATH = DIRECTIVAS_DIR / "memoria_maestra.md"
SKILLS_DIR = BUNDLE_ROOT / ".agents" / "skills"
AGENTS_DIR = BUNDLE_ROOT / ".agents"


def ensure_runtime_dirs() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


ensure_runtime_dirs()
