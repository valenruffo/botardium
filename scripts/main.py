import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_IMPORT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_IMPORT_ROOT))

if len(sys.argv) >= 2 and sys.argv[1] == "--run-warmer":
    sys.argv.pop(1)
    from scripts.core_warmer import main as warmer_main
    sys.exit(warmer_main())

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import os
import re
import sqlite3
import time
import subprocess
from dotenv import load_dotenv
import openai
import json
import asyncio
import sys
import traceback
import shutil
import zipfile
import urllib.request
from packaging.version import Version, InvalidVersion
from uuid import uuid4
from datetime import datetime
from scripts.runtime_paths import (
    AGENTS_DIR,
    DB_DIR,
    ENV_EXAMPLE_PATH,
    ENV_PATH,
    PROFILE_PATH,
    SKILLS_DIR,
    TMP_DIR,
    SESSIONS_DIR,
    WRITABLE_ROOT,
)

try:
    from google import genai as google_genai
    from google.genai import types as google_genai_types
except Exception:
    google_genai = None
    google_genai_types = None

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

PROJECT_ROOT = WRITABLE_ROOT
sys.path.append(str(SKILLS_DIR))
from stealth_engine import create_stealth_browser, close_stealth_browser

app = FastAPI(
    title="Botardium Core API",
    description="Backend motor SaaS para Patchright, ADB y extracción de leads.",
    version="2.0.0"
)


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LEGACY_DB_PATH = DB_DIR / "primebot.db"
DB_PATH = DB_DIR / "botardium.db"

if LEGACY_DB_PATH.exists() and not DB_PATH.exists():
    LEGACY_DB_PATH.replace(DB_PATH)


def _connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _slugify_workspace_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or f"workspace-{int(time.time())}"


def _workspace_slug(workspace_id: int) -> str:
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT workspace_slug FROM users WHERE id = ?", (workspace_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Workspace no encontrado.")
    return str(row["workspace_slug"] or f"workspace-{workspace_id}")


def _workspace_name(workspace_id: int) -> str:
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT workspace_name, full_name, email FROM users WHERE id = ?", (workspace_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Workspace no encontrado.")
    return str(row["workspace_name"] or row["full_name"] or row["email"] or f"Workspace {workspace_id}")


def _set_workspace_env(workspace_id: int) -> tuple[str | None, str | None]:
    prev_id = os.environ.get("BOTARDIUM_WORKSPACE_ID")
    prev_slug = os.environ.get("BOTARDIUM_WORKSPACE_SLUG")
    os.environ["BOTARDIUM_WORKSPACE_ID"] = str(workspace_id)
    os.environ["BOTARDIUM_WORKSPACE_SLUG"] = _workspace_slug(workspace_id)
    return prev_id, prev_slug


def _restore_workspace_env(previous: tuple[str | None, str | None]) -> None:
    prev_id, prev_slug = previous
    if prev_id is None:
        os.environ.pop("BOTARDIUM_WORKSPACE_ID", None)
    else:
        os.environ["BOTARDIUM_WORKSPACE_ID"] = prev_id
    if prev_slug is None:
        os.environ.pop("BOTARDIUM_WORKSPACE_SLUG", None)
    else:
        os.environ["BOTARDIUM_WORKSPACE_SLUG"] = prev_slug


def _workspace_ai_config(workspace_id: Optional[int]) -> Dict[str, str]:
    google_key = GOOGLE_API_KEY
    openai_key = os.getenv("OPENAI_API_KEY", "") or ""
    if not workspace_id:
        return {
            "google_api_key": google_key.strip(),
            "openai_api_key": openai_key.strip(),
        }

    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT google_api_key, openai_api_key FROM users WHERE id = ?",
        (int(workspace_id),),
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        google_key = str(row["google_api_key"] or google_key or "").strip()
        openai_key = str(row["openai_api_key"] or openai_key or "").strip()
    return {
        "google_api_key": google_key,
        "openai_api_key": openai_key,
    }


def _workspace_ai_status(workspace_id: Optional[int]) -> Dict[str, Any]:
    config = _workspace_ai_config(workspace_id)
    has_google = bool(config["google_api_key"])
    has_openai = bool(config["openai_api_key"])
    return {
        "google_configured": has_google,
        "openai_configured": has_openai,
        "magic_box_enabled": has_google or has_openai,
        "message_studio_enabled": has_google or has_openai,
        "lead_drafts_enabled": has_google or has_openai,
        "recommended_provider": "google" if has_google else ("openai" if has_openai else None),
        "google_label": "Google AI Studio (gratis para empezar)",
        "openai_label": "OpenAI",
    }


def _mask_key(value: str) -> str:
    key = str(value or "").strip()
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def _downloads_dir() -> Path:
    return Path.home() / "Downloads"


def _workspace_session_dir(workspace_slug: str) -> Path:
    return SESSIONS_DIR / workspace_slug


def _version_tuple(value: str) -> Version:
    normalized = str(value or "0.0.0").strip().lstrip("v")
    try:
        return Version(normalized)
    except InvalidVersion:
        return Version("0.0.0")


def _current_app_version() -> str:
    version_file = PROJECT_ROOT / "botardium-panel" / "web" / "src-tauri" / "tauri.conf.json"
    if version_file.exists():
        try:
            return str(json.loads(version_file.read_text(encoding="utf-8")).get("version") or "1.0.0")
        except Exception:
            pass
    return "1.0.0"


def _table_columns(cursor: sqlite3.Cursor, table_name: str) -> List[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [str(row[1]) for row in cursor.fetchall()]


def _copy_workspace_sessions(workspace_slug: str, destination: Path) -> None:
    source = _workspace_session_dir(workspace_slug)
    if source.exists():
        shutil.copytree(source, destination, dirs_exist_ok=True)


def _build_workspace_export(workspace_id: int) -> Path:
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (workspace_id,))
    workspace = cursor.fetchone()
    if not workspace:
        conn.close()
        raise HTTPException(status_code=404, detail="Workspace no encontrado.")

    workspace_slug = str(workspace["workspace_slug"] or f"workspace-{workspace_id}")
    workspace_name = str(workspace["workspace_name"] or workspace["full_name"] or workspace["email"] or workspace_slug)
    export_root = TMP_DIR / "workspace_exports" / f"{workspace_slug}-{int(time.time())}"
    if export_root.exists():
        shutil.rmtree(export_root, ignore_errors=True)
    export_root.mkdir(parents=True, exist_ok=True)

    cursor.execute("SELECT * FROM ig_accounts WHERE user_id = ? ORDER BY id ASC", (workspace_id,))
    accounts = [dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT * FROM leads WHERE workspace_id = ? ORDER BY id ASC", (workspace_id,))
    leads = [dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT * FROM campaigns_cache WHERE workspace_id = ? ORDER BY updated_at DESC", (workspace_id,))
    campaigns = [dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT * FROM message_jobs_cache WHERE workspace_id = ? ORDER BY updated_at DESC", (workspace_id,))
    jobs = [dict(row) for row in cursor.fetchall()]
    conn.close()

    payload = {
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "workspace": dict(workspace),
        "ig_accounts": accounts,
        "leads": leads,
        "campaigns_cache": campaigns,
        "message_jobs_cache": jobs,
    }
    (export_root / "workspace.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _copy_workspace_sessions(workspace_slug, export_root / "sessions")

    downloads_dir = _downloads_dir()
    downloads_dir.mkdir(parents=True, exist_ok=True)
    archive_path = downloads_dir / f"botardium-workspace-{workspace_slug}.zip"
    if archive_path.exists():
        archive_path.unlink()
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in export_root.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(export_root))
    return archive_path


def _import_workspace_archive(zip_path: str) -> Dict[str, Any]:
    source = Path(zip_path)
    if not source.exists() or source.suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="Selecciona un ZIP de workspace válido.")

    import_root = TMP_DIR / "workspace_imports" / f"import-{int(time.time())}"
    if import_root.exists():
        shutil.rmtree(import_root, ignore_errors=True)
    import_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source, "r") as archive:
        archive.extractall(import_root)

    payload_path = import_root / "workspace.json"
    if not payload_path.exists():
        raise HTTPException(status_code=400, detail="El archivo no contiene un workspace exportado por Botardium.")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    workspace_payload = payload.get("workspace") or {}
    requested_name = str(workspace_payload.get("workspace_name") or workspace_payload.get("full_name") or "Workspace importado").strip()

    conn = _connect_db()
    cursor = conn.cursor()
    base_slug = _slugify_workspace_name(requested_name)
    cursor.execute("SELECT workspace_slug FROM users WHERE workspace_slug LIKE ?", (f"{base_slug}%",))
    existing = {str(row[0]) for row in cursor.fetchall()}
    slug = base_slug
    suffix = 2
    while slug in existing:
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    synthetic_email = f"{slug}@botardium.local"
    cursor.execute(
        "INSERT INTO users (email, password_hash, full_name, workspace_name, workspace_slug, is_workspace, google_api_key, openai_api_key) VALUES (?, '', ?, ?, ?, 1, ?, ?)",
        (
            synthetic_email,
            requested_name,
            requested_name,
            slug,
            str(workspace_payload.get("google_api_key") or ""),
            str(workspace_payload.get("openai_api_key") or ""),
        ),
    )
    new_workspace_id = int(cursor.lastrowid)

    account_id_map: Dict[int, int] = {}
    for account in payload.get("ig_accounts", []):
        record = dict(account)
        old_account_id = int(record.pop("id"))
        record["user_id"] = new_workspace_id
        columns = list(record.keys())
        placeholders = ", ".join("?" for _ in columns)
        cursor.execute(
            f"INSERT INTO ig_accounts ({', '.join(columns)}) VALUES ({placeholders})",
            [record[column] for column in columns],
        )
        account_id_map[old_account_id] = int(cursor.lastrowid)

    campaign_id_map: Dict[str, str] = {}
    for campaign in payload.get("campaigns_cache", []):
        old_campaign_id = str(campaign.get("id"))
        new_campaign_id = str(uuid4())
        campaign_id_map[old_campaign_id] = new_campaign_id
        campaign_payload = json.loads(str(campaign.get("payload") or "{}"))
        campaign_payload["id"] = new_campaign_id
        campaign_payload["workspace_id"] = new_workspace_id
        cursor.execute(
            "INSERT INTO campaigns_cache (id, workspace_id, payload, updated_at) VALUES (?, ?, ?, ?)",
            (new_campaign_id, new_workspace_id, json.dumps(campaign_payload, ensure_ascii=False), campaign.get("updated_at") or datetime.now().isoformat()),
        )

    for lead in payload.get("leads", []):
        record = dict(lead)
        record.pop("id", None)
        record["workspace_id"] = new_workspace_id
        if record.get("ig_account_id") is not None:
            record["ig_account_id"] = account_id_map.get(int(record["ig_account_id"]))
        if record.get("campaign_id"):
            record["campaign_id"] = campaign_id_map.get(str(record["campaign_id"]), record["campaign_id"])
        columns = list(record.keys())
        placeholders = ", ".join("?" for _ in columns)
        cursor.execute(
            f"INSERT INTO leads ({', '.join(columns)}) VALUES ({placeholders})",
            [record[column] for column in columns],
        )

    for job in payload.get("message_jobs_cache", []):
        new_job_id = str(uuid4())
        job_payload = json.loads(str(job.get("payload") or "{}"))
        job_payload["id"] = new_job_id
        job_payload["workspace_id"] = new_workspace_id
        if job_payload.get("campaign_id"):
            job_payload["campaign_id"] = campaign_id_map.get(str(job_payload["campaign_id"]), job_payload["campaign_id"])
        cursor.execute(
            "INSERT INTO message_jobs_cache (id, workspace_id, payload, updated_at) VALUES (?, ?, ?, ?)",
            (new_job_id, new_workspace_id, json.dumps(job_payload, ensure_ascii=False), job.get("updated_at") or datetime.now().isoformat()),
        )

    conn.commit()
    conn.close()

    session_source = import_root / "sessions"
    if session_source.exists():
        shutil.copytree(session_source, _workspace_session_dir(slug), dirs_exist_ok=True)

    return {"workspace_id": new_workspace_id, "name": requested_name, "slug": slug}


def _latest_release_status(current_version: str) -> Dict[str, Any]:
    current = _version_tuple(current_version)
    latest_url = "https://api.github.com/repos/valenruffo/botardium/releases/latest"
    try:
        request = urllib.request.Request(latest_url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Botardium-Updater"})
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "detail": f"No pude consultar GitHub Releases: {exc}", "current_version": current_version}

    latest_version = str(payload.get("tag_name") or payload.get("name") or current_version).lstrip("v")
    assets = payload.get("assets") or []
    installer = next((asset for asset in assets if str(asset.get("name") or "").lower().endswith("setup.exe")), None)
    return {
        "ok": True,
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": _version_tuple(latest_version) > current,
        "download_url": installer.get("browser_download_url") if installer else payload.get("html_url"),
        "release_url": payload.get("html_url"),
        "notes": str(payload.get("body") or "")[:1200],
    }

# Inicializar Base de Datos (Seguridad & Relaciones)
def init_db():
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout = 10000")
    # Tabla de Usuarios SaaS
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            workspace_name TEXT,
            workspace_slug TEXT,
            is_workspace INTEGER DEFAULT 1,
            google_api_key TEXT,
            openai_api_key TEXT
        )
    ''')
    cursor.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in cursor.fetchall()}
    if "workspace_name" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN workspace_name TEXT")
    if "workspace_slug" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN workspace_slug TEXT")
    if "is_workspace" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_workspace INTEGER DEFAULT 1")
    if "google_api_key" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN google_api_key TEXT")
    if "openai_api_key" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN openai_api_key TEXT")
    cursor.execute("SELECT id, full_name, email, workspace_name, workspace_slug FROM users")
    for row in cursor.fetchall():
        row_id = int(row[0])
        workspace_name = str(row[3] or row[1] or row[2] or f"Workspace {row_id}")
        workspace_slug = str(row[4] or _slugify_workspace_name(workspace_name))
        cursor.execute(
            "UPDATE users SET workspace_name = ?, workspace_slug = ?, is_workspace = 1 WHERE id = ?",
            (workspace_name, workspace_slug, row_id),
        )
    # Tabla de Cuentas de Instagram conectadas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ig_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ig_username TEXT NOT NULL,
            ig_password TEXT NOT NULL,
            session_status TEXT DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    # Tabla de Leads (si no existía)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ig_account_id INTEGER,
            username TEXT NOT NULL,
            status TEXT DEFAULT 'Pendiente',
            source TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute("PRAGMA table_info(leads)")
    lead_columns = {row[1] for row in cursor.fetchall()}
    if "ig_account_id" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN ig_account_id INTEGER")
    if "ig_username" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN ig_username TEXT")
        if "username" in lead_columns:
            cursor.execute("UPDATE leads SET ig_username = username WHERE ig_username IS NULL")
    if "created_at" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN created_at TEXT")
        if "timestamp" in lead_columns:
            cursor.execute("UPDATE leads SET created_at = timestamp WHERE created_at IS NULL")
    if "campaign_id" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN campaign_id TEXT")
    if "full_name" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN full_name TEXT")
    if "bio" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN bio TEXT")
    if "contacted_at" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN contacted_at TEXT")
    if "last_message_preview" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN last_message_preview TEXT")
    if "message_prompt" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN message_prompt TEXT")
    if "message_variant" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN message_variant TEXT")
    if "sent_at" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN sent_at TEXT")
    if "follow_up_due_at" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN follow_up_due_at TEXT")
    if "workspace_id" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN workspace_id INTEGER")
    cursor.execute("PRAGMA table_info(ig_accounts)")
    account_columns = {row[1] for row in cursor.fetchall()}
    if "warmup_status" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN warmup_status TEXT DEFAULT 'idle'")
    if "warmup_progress" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN warmup_progress INTEGER DEFAULT 0")
    if "warmup_last_run_at" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN warmup_last_run_at TEXT")
    if "warmup_last_duration_min" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN warmup_last_duration_min INTEGER DEFAULT 0")
    if "warmup_required" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN warmup_required INTEGER DEFAULT 1")
    if "health_score" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN health_score INTEGER DEFAULT 72")
    if "current_action" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN current_action TEXT DEFAULT ''")
    if "last_error" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN last_error TEXT DEFAULT ''")
    if "daily_dm_limit" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN daily_dm_limit INTEGER DEFAULT 35")
    if "daily_dm_sent" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN daily_dm_sent INTEGER DEFAULT 0")
    if "account_type" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN account_type TEXT DEFAULT 'mature'")
    if "account_warmup_status" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN account_warmup_status TEXT DEFAULT 'completed'")
    if "account_warmup_days_total" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN account_warmup_days_total INTEGER DEFAULT 0")
    if "account_warmup_days_completed" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN account_warmup_days_completed INTEGER DEFAULT 0")
    if "session_warmup_last_run_at" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN session_warmup_last_run_at TEXT")
    if "session_warmup_phase" not in account_columns:
        cursor.execute("ALTER TABLE ig_accounts ADD COLUMN session_warmup_phase TEXT DEFAULT ''")
    if "last_outreach_result" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN last_outreach_result TEXT")
    if "last_outreach_error" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN last_outreach_error TEXT")
    if "last_message_rationale" not in lead_columns:
        cursor.execute("ALTER TABLE leads ADD COLUMN last_message_rationale TEXT")
    cursor.execute(
        """
        UPDATE leads
        SET workspace_id = (
            SELECT user_id FROM ig_accounts WHERE ig_accounts.id = leads.ig_account_id
        )
        WHERE workspace_id IS NULL AND ig_account_id IS NOT NULL
        """
    )
    cursor.execute("SELECT COUNT(*) FROM users")
    workspace_count = int(cursor.fetchone()[0])
    if workspace_count == 1:
        cursor.execute("SELECT id FROM users LIMIT 1")
        only_workspace_id = int(cursor.fetchone()[0])
        cursor.execute("UPDATE leads SET workspace_id = ? WHERE workspace_id IS NULL", (only_workspace_id,))

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS campaigns_cache (
            id TEXT PRIMARY KEY,
            workspace_id INTEGER NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        '''
    )
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS message_jobs_cache (
            id TEXT PRIMARY KEY,
            workspace_id INTEGER NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        '''
    )
    cursor.execute("UPDATE leads SET status = 'Completado' WHERE status = 'Contactado'")
    conn.commit()
    conn.close()


def _ensure_leads_workspace_safe_schema() -> None:
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'leads'")
    row = cursor.fetchone()
    create_sql = str(row[0] or "") if row else ""
    if "UNIQUE" not in create_sql.upper():
        conn.close()
        return

    cursor.execute("PRAGMA table_info(leads)")
    existing_columns = {str(col[1]) for col in cursor.fetchall()}
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS leads_workspace_migration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ig_account_id INTEGER,
            username TEXT,
            status TEXT DEFAULT 'Pendiente',
            source TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            ig_username TEXT,
            created_at TEXT,
            campaign_id TEXT,
            full_name TEXT,
            bio TEXT,
            contacted_at TEXT,
            last_message_preview TEXT,
            message_prompt TEXT,
            message_variant TEXT,
            sent_at TEXT,
            follow_up_due_at TEXT,
            workspace_id INTEGER,
            last_outreach_result TEXT,
            last_outreach_error TEXT,
            last_message_rationale TEXT
        )
        '''
    )
    ordered_columns = [
        "id", "ig_account_id", "username", "status", "source", "timestamp", "ig_username", "created_at", "campaign_id",
        "full_name", "bio", "contacted_at", "last_message_preview", "message_prompt", "message_variant", "sent_at",
        "follow_up_due_at", "workspace_id", "last_outreach_result", "last_outreach_error", "last_message_rationale",
    ]
    insert_columns = [column for column in ordered_columns if column in existing_columns]
    select_columns = []
    for column in ordered_columns:
        if column in existing_columns:
            select_columns.append(column)
        elif column == "ig_username" and "username" in existing_columns:
            select_columns.append("username AS ig_username")
            insert_columns.append("ig_username") if "ig_username" not in insert_columns else None
        elif column == "created_at" and "timestamp" in existing_columns:
            select_columns.append("timestamp AS created_at")
            insert_columns.append("created_at") if "created_at" not in insert_columns else None
    cursor.execute(
        f"INSERT INTO leads_workspace_migration ({', '.join(insert_columns)}) SELECT {', '.join(select_columns)} FROM leads"
    )
    cursor.execute("DROP TABLE leads")
    cursor.execute("ALTER TABLE leads_workspace_migration RENAME TO leads")
    conn.commit()
    conn.close()


def cleanup_legacy_message_previews() -> int:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    legacy_patterns = [
        "%vi tu perfil desde%",
        "%Me dio contexto tu bio:%",
        "%seguidores%",
        "%publicaciones - Ver fotos y videos de Instagram%",
    ]
    where_clause = " OR ".join(["last_message_preview LIKE ?" for _ in legacy_patterns])
    cursor.execute(
        f"""
        UPDATE leads
        SET last_message_preview = NULL,
            message_prompt = NULL,
            message_variant = NULL,
            follow_up_due_at = NULL,
            status = CASE
                WHEN sent_at IS NULL AND status IN ('Listo para contactar', 'Primer contacto', 'Follow-up 1', 'Follow-up 2') THEN 'Pendiente'
                ELSE status
            END
        WHERE last_message_preview IS NOT NULL AND ({where_clause})
        """,
        legacy_patterns,
    )
    changed = cursor.rowcount if cursor.rowcount is not None else 0
    conn.commit()
    conn.close()
    return changed

@app.on_event("startup")
def startup_event():
    init_db()
    _ensure_leads_workspace_safe_schema()
    _load_persisted_runtime_state()
    cleanup_legacy_message_previews()

# Cargar variables de entorno locales
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv(ENV_EXAMPLE_PATH)

openai.api_key = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()

# ----------------------------------------------------- #
# Models
# ----------------------------------------------------- #
class MagicBoxRequest(BaseModel):
    workspace_id: Optional[int] = None
    prompt: str


class WorkspaceAiSettingsRequest(BaseModel):
    google_api_key: str = ""
    openai_api_key: str = ""


class WorkspaceImportRequest(BaseModel):
    zip_path: str

class StrategySourceResponse(BaseModel):
    type: str
    target: str


class StrategyFilterContext(BaseModel):
    intent_summary: str = ""
    include_terms: List[str] = []
    exclude_terms: List[str] = []

class MagicBoxResponse(BaseModel):
    sources: List[StrategySourceResponse]
    reasoning: str
    filter_context: StrategyFilterContext = StrategyFilterContext()

class BotConfig(BaseModel):
    username: str
    target_type: str
    query: str
    limit: int = 50


class TargetSource(BaseModel):
    type: str
    value: str


class CampaignStartRequest(BaseModel):
    workspace_id: int
    username: str
    campaign_name: Optional[str] = None
    strategy_context: Optional[StrategyFilterContext] = None
    sources: List[TargetSource]
    limit: int = 50
    warmup_mode: str = "auto"
    warmup_minutes: int = 5
    execution_mode: str = "real"
    filter_profile: str = "strict"
    min_followers: int = 50
    min_posts: int = 3
    require_identity: bool = True
    require_keyword_match: bool = True
    require_coherence: bool = True


class CampaignActionRequest(BaseModel):
    action: str
    campaign_name: Optional[str] = None


class LeadBulkRequest(BaseModel):
    ids: List[int] = []
    status: Optional[str] = None


class MessageStudioRequest(BaseModel):
    workspace_id: Optional[int] = None
    ids: List[int]
    prompt: str = ""
    prompt_first_contact: Optional[str] = None
    prompt_follow_up_1: Optional[str] = None
    prompt_follow_up_2: Optional[str] = None
    master_prompt_mode: str = "default"
    master_prompt: Optional[str] = None


class LeadDraftUpdateRequest(BaseModel):
    message: str


class LeadRegenerateDraftRequest(BaseModel):
    workspace_id: Optional[int] = None
    prompt_first_contact: Optional[str] = None
    prompt_follow_up_1: Optional[str] = None
    prompt_follow_up_2: Optional[str] = None
    master_prompt_mode: str = "default"
    master_prompt: Optional[str] = None


class MessageQueueRequest(BaseModel):
    workspace_id: int
    ids: List[int]
    prompt: str = ""
    prompt_first_contact: Optional[str] = None
    prompt_follow_up_1: Optional[str] = None
    prompt_follow_up_2: Optional[str] = None
    master_prompt_mode: str = "default"
    master_prompt: Optional[str] = None
    campaign_id: Optional[str] = None
    follow_up_days: int = 3


class MessageRunRequest(BaseModel):
    workspace_id: int
    ids: List[int] = []
    dry_run: bool = False
    campaign_id: Optional[str] = None
    account_id: Optional[int] = None
    override_cold_session: bool = False


class AccountWarmupRequest(BaseModel):
    duration_min: int = 10


class AccountProfileUpdateRequest(BaseModel):
    account_type: str


class AccountBulkWarmupRequest(BaseModel):
    workspace_id: int
    duration_min: int = 10
    account_ids: List[int] = []

class WorkspaceCreateReq(BaseModel):
    name: str

class AccountAddReq(BaseModel):
    workspace_id: int
    ig_username: str
    ig_password: str


ALLOWED_STRATEGY_TYPES = {"hashtag", "followers", "location"}
ALLOWED_WARMUP_MODES = {"auto", "skip", "custom"}
ALLOWED_EXECUTION_MODES = {"real", "test"}
ALLOWED_FILTER_PROFILES = {"strict", "balanced", "expansive"}
CAMPAIGN_STORE: Dict[str, Dict[str, Any]] = {}
CAMPAIGN_TASKS: Dict[str, asyncio.Task] = {}
ACCOUNT_WARMUP_TASKS: Dict[int, asyncio.Task] = {}
MESSAGE_JOB_STORE: Dict[str, Dict[str, Any]] = {}


def _persist_campaign(campaign: Dict[str, Any]) -> None:
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO campaigns_cache (id, workspace_id, payload, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET workspace_id = excluded.workspace_id, payload = excluded.payload, updated_at = excluded.updated_at
        """,
        (
            campaign["id"],
            int(campaign.get("workspace_id") or 0),
            json.dumps(campaign, ensure_ascii=False),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def _delete_campaign(campaign_id: str) -> None:
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM campaigns_cache WHERE id = ?", (campaign_id,))
    conn.commit()
    conn.close()


def _persist_message_job(job: Dict[str, Any]) -> None:
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO message_jobs_cache (id, workspace_id, payload, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET workspace_id = excluded.workspace_id, payload = excluded.payload, updated_at = excluded.updated_at
        """,
        (
            job["id"],
            int(job.get("workspace_id") or 0),
            json.dumps(job, ensure_ascii=False),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def _load_persisted_runtime_state() -> None:
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT payload FROM campaigns_cache ORDER BY updated_at DESC")
    for row in cursor.fetchall():
        try:
            campaign = json.loads(str(row["payload"] or "{}"))
            if not campaign.get("id"):
                continue
            if campaign.get("status") in {"running", "warmup"}:
                campaign["status"] = "paused"
                campaign["current_action"] = "Botardium se reinicio. Revisa esta campaña antes de continuar."
            CAMPAIGN_STORE[str(campaign["id"])] = campaign
        except Exception:
            continue
    cursor.execute("SELECT payload FROM message_jobs_cache ORDER BY updated_at DESC")
    for row in cursor.fetchall():
        try:
            job = json.loads(str(row["payload"] or "{}"))
            if not job.get("id"):
                continue
            if job.get("status") in {"queued", "running"}:
                job["status"] = "error"
                job["current_action"] = "Botardium se reinicio antes de terminar este job."
            MESSAGE_JOB_STORE[str(job["id"])] = job
        except Exception:
            continue
    conn.close()


def _append_campaign_log(campaign: Dict[str, Any], message: str) -> None:
    campaign.setdefault("logs", []).insert(0, {
        "message": message,
        "timestamp": int(time.time()),
    })
    campaign["logs"] = campaign["logs"][:12]
    if campaign.get("id"):
        _persist_campaign(campaign)


def _workspace_campaigns(workspace_id: int) -> List[Dict[str, Any]]:
    return [campaign for campaign in CAMPAIGN_STORE.values() if int(campaign.get("workspace_id") or 0) == int(workspace_id)]


def _workspace_jobs(workspace_id: int) -> List[Dict[str, Any]]:
    return [job for job in MESSAGE_JOB_STORE.values() if int(job.get("workspace_id") or 0) == int(workspace_id)]


def _count_leads() -> int:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM leads")
    count = int(cursor.fetchone()[0])
    conn.close()
    return count


def _count_leads_for_campaign(campaign_id: str) -> int:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM leads WHERE campaign_id = ?", (campaign_id,))
    count = int(cursor.fetchone()[0])
    conn.close()
    return count


def _compute_health_score(row: Dict[str, Any]) -> int:
    score = int(row.get("health_score") or 72)
    if row.get("warmup_status") == "running":
        score = max(score, 78)
    if row.get("warmup_required"):
        score = min(score, 68)
    if row.get("last_error"):
        score = min(score, 55)
    return max(20, min(99, score))


def _hours_since(timestamp_str: Optional[str]) -> Optional[float]:
    if not timestamp_str:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(timestamp_str)).total_seconds() / 3600
    except Exception:
        return None


def _requires_session_warmup(row: Dict[str, Any]) -> bool:
    hours = _hours_since(row.get("session_warmup_last_run_at"))
    if hours is None:
        return True
    return hours >= 12


def _requires_account_warmup(row: Dict[str, Any]) -> bool:
    account_type = str(row.get("account_type") or "mature")
    if account_type == "mature":
        return False
    total = int(row.get("account_warmup_days_total") or 0)
    completed = int(row.get("account_warmup_days_completed") or 0)
    return completed < max(total, 1)


def _serialize_account(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
    data = dict(row)
    runtime_profile = _build_runtime_account_profile(data)
    if data.get("id"):
        data["daily_dm_sent"] = _sent_last_24h(int(data["id"]))
    data["daily_dm_limit"] = int(runtime_profile.get("max_dms_per_day", data.get("daily_dm_limit") or 20))
    data["warmup_required"] = bool(data.get("warmup_required", 0))
    data["health_score"] = _compute_health_score(data)
    data["is_busy"] = data.get("warmup_status") == "running"
    data["requires_session_warmup"] = _requires_session_warmup(data)
    data["requires_account_warmup"] = _requires_account_warmup(data)
    return data


def _profile_key_from_account_type(account_type: str) -> str:
    normalized = (account_type or "mature").strip().lower()
    if normalized == "new":
        return "prospector"
    if normalized == "rehab":
        return "rehab"
    return "personal"


def _build_runtime_account_profile(account: Dict[str, Any]) -> Dict[str, Any]:
    from scripts.account_check import PROFILES, calculate_scaled_limits

    profile_key = _profile_key_from_account_type(str(account.get("account_type") or "mature"))
    base = dict(PROFILES[profile_key])
    existing = {
        "days_active": int(account.get("account_warmup_days_completed") or 0),
        "max_dms_per_day": int(base.get("max_dms_per_day", 20)),
    }
    profile = calculate_scaled_limits(base, existing)
    profile["ig_username"] = account.get("ig_username")
    stored_limit = int(account.get("daily_dm_limit") or 0)
    scaled_limit = int(profile.get("max_dms_per_day", 20))
    if str(account.get("account_type") or "mature") == "mature" and stored_limit == 35:
        profile["max_dms_per_day"] = scaled_limit
    elif stored_limit > 0:
        profile["max_dms_per_day"] = min(stored_limit, int(profile.get("max_dms_cap", 50)))
    else:
        profile["max_dms_per_day"] = scaled_limit
    return profile


def _write_runtime_account_profile(account: Dict[str, Any]) -> None:
    profile = _build_runtime_account_profile(account)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_account(account_id: int) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ig_accounts WHERE id = ?", (account_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def _get_account_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ig_accounts WHERE lower(ig_username) = lower(?) ORDER BY id DESC LIMIT 1", (username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def _sent_last_24h(account_id: int) -> int:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    window_start = datetime.fromtimestamp(time.time() - 86400).isoformat()
    cursor.execute("SELECT COUNT(*) FROM leads WHERE ig_account_id = ? AND sent_at IS NOT NULL AND sent_at >= ?", (account_id, window_start))
    count = int(cursor.fetchone()[0])
    conn.close()
    return count


def _estimate_account_send_window(account_id: int, lead_count: int) -> tuple[int, int]:
    if lead_count <= 0:
        return (0, 0)

    fallback_min_per_lead = 120 + 35
    fallback_max_per_lead = 480 + 70
    min_per_lead = fallback_min_per_lead
    max_per_lead = fallback_max_per_lead

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT sent_at FROM leads WHERE ig_account_id = ? AND sent_at IS NOT NULL ORDER BY sent_at DESC LIMIT 120",
        (account_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    timestamps: List[datetime] = []
    for row in rows:
        raw = row[0]
        if not raw:
            continue
        try:
            timestamps.append(datetime.fromisoformat(str(raw)))
        except Exception:
            continue

    timestamps.sort()
    gaps: List[int] = []
    for idx in range(1, len(timestamps)):
        diff = int((timestamps[idx] - timestamps[idx - 1]).total_seconds())
        if 20 <= diff <= 1800:
            gaps.append(diff)

    if len(gaps) >= 4:
        ordered = sorted(gaps)
        p25 = ordered[int((len(ordered) - 1) * 0.25)]
        p75 = ordered[int((len(ordered) - 1) * 0.75)]
        min_per_lead = max(60, min(int(fallback_max_per_lead * 1.2), p25))
        max_per_lead = max(min_per_lead + 15, min(int(fallback_max_per_lead * 1.4), p75))

    return (lead_count * min_per_lead, lead_count * max_per_lead)


def _update_account_runtime(account_id: int, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [account_id]
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(f"UPDATE ig_accounts SET {assignments} WHERE id = ?", values)
    conn.commit()
    conn.close()


async def _run_account_warmup(account_id: int, username: str, duration_min: int, linked_campaign_id: Optional[str] = None) -> None:
    duration_min = max(1, min(duration_min, 30))
    started_at = time.time()
    _update_account_runtime(
        account_id,
        warmup_status="running",
        warmup_progress=3,
        session_warmup_phase="abriendo_instagram",
        current_action=f"Preparando warmeo real para @{username}",
        last_error="",
    )

    if linked_campaign_id and linked_campaign_id in CAMPAIGN_STORE:
        campaign = CAMPAIGN_STORE[linked_campaign_id]
        campaign["status"] = "warmup"
        campaign["progress"] = 5
        campaign["current_action"] = f"Warmup real en curso para @{username}"
        _append_campaign_log(campaign, campaign["current_action"])

    warmup_log_path = TMP_DIR / "logs" / f"warmup_account_{account_id}.log"
    warmup_log_path.parent.mkdir(parents=True, exist_ok=True)
    warmup_log_handle = open(warmup_log_path, "a", encoding="utf-8")
    worker: Optional[subprocess.Popen] = None

    worker = subprocess.Popen(
        [
            sys.executable,
            "--run-warmer",
            "--duration",
            str(duration_min),
            "--username",
            username,
        ],
        cwd=str(PROJECT_ROOT),
        stdout=warmup_log_handle,
        stderr=warmup_log_handle,
        stdin=subprocess.DEVNULL,
    )

    try:
        while worker.poll() is None:
            elapsed = time.time() - started_at
            progress = min(94, max(5, int((elapsed / max(duration_min * 60, 1)) * 100)))
            if progress < 18:
                phase = "Abriendo Instagram y recuperando sesion"
                phase_key = "abriendo_instagram"
            elif progress < 45:
                phase = "Leyendo feed y scroll organico"
                phase_key = "scroll_feed"
            elif progress < 68:
                phase = "Viendo stories y simulando actividad natural"
                phase_key = "stories"
            elif progress < 86:
                phase = "Interacciones ligeras: likes y perfiles cercanos"
                phase_key = "interacciones_ligeras"
            else:
                phase = "Cierre suave y enfriamiento de sesion"
                phase_key = "cooldown"
            _update_account_runtime(
                account_id,
                warmup_status="running",
                warmup_progress=progress,
                session_warmup_phase=phase_key,
                current_action=phase,
            )
            if linked_campaign_id and linked_campaign_id in CAMPAIGN_STORE:
                campaign = CAMPAIGN_STORE[linked_campaign_id]
                campaign["status"] = "warmup"
                campaign["progress"] = progress
                campaign["current_action"] = f"Warmup real · {phase}"
            await asyncio.sleep(2)

        return_code = worker.wait()
        if return_code != 0:
            raise RuntimeError(f"Warmup terminó con error (code {return_code}). Revisa {warmup_log_path}.")

        finished_at = datetime.now().isoformat()
        account = _get_account(account_id) or {}
        next_score = min(99, max(80, int(account.get("health_score") or 72) + 8))
        _update_account_runtime(
            account_id,
            warmup_status="ready",
            warmup_progress=100,
            session_warmup_phase="completed",
            current_action="Warmup completado. Cuenta lista para scraping y outreach.",
            warmup_last_run_at=finished_at,
            warmup_last_duration_min=duration_min,
            session_warmup_last_run_at=finished_at,
            warmup_required=0,
            health_score=next_score,
            last_error="",
        )
        if linked_campaign_id and linked_campaign_id in CAMPAIGN_STORE:
            campaign = CAMPAIGN_STORE[linked_campaign_id]
            campaign["status"] = "ready"
            campaign["progress"] = 35
            campaign["current_action"] = "Warmup completo. Lista para comenzar scraping."
            _append_campaign_log(campaign, campaign["current_action"])
    except asyncio.CancelledError:
        if worker and worker.poll() is None:
            worker.terminate()
        _update_account_runtime(
            account_id,
            warmup_status="idle",
            warmup_progress=0,
            session_warmup_phase="idle",
            current_action="Warmup cancelado por operador.",
            last_error="",
        )
        if linked_campaign_id and linked_campaign_id in CAMPAIGN_STORE:
            campaign = CAMPAIGN_STORE[linked_campaign_id]
            campaign["status"] = "draft"
            campaign["progress"] = 0
            campaign["current_action"] = "Warmup cancelado. Puedes relanzarlo cuando quieras."
            _append_campaign_log(campaign, campaign["current_action"])
        raise
    except Exception as exc:
        detail_msg = str(exc).strip() or f"{exc.__class__.__name__} sin detalle"
        print(f"[WARMUP_ERROR] account_id={account_id} detail={detail_msg}")
        print(traceback.format_exc())
        _update_account_runtime(
            account_id,
            warmup_status="error",
            warmup_progress=0,
            session_warmup_phase="error",
            current_action="Error durante warmup.",
            last_error=detail_msg,
            warmup_required=1,
        )
        if linked_campaign_id and linked_campaign_id in CAMPAIGN_STORE:
            campaign = CAMPAIGN_STORE[linked_campaign_id]
            campaign["status"] = "draft"
            campaign["progress"] = 0
            campaign["current_action"] = f"Warmup fallo: {detail_msg}"
            _append_campaign_log(campaign, campaign["current_action"])
    finally:
        try:
            warmup_log_handle.close()
        except Exception:
            pass
        ACCOUNT_WARMUP_TASKS.pop(account_id, None)


async def _run_campaign_warmup(campaign_id: str) -> None:
    campaign = CAMPAIGN_STORE.get(campaign_id)
    if not campaign:
        return

    account = _get_account_by_username(campaign["username"])
    if not account:
        campaign["status"] = "draft"
        campaign["progress"] = 0
        campaign["current_action"] = "No se encontro la cuenta IG vinculada para ejecutar warmup."
        _append_campaign_log(campaign, campaign["current_action"])
        return

    existing_task = ACCOUNT_WARMUP_TASKS.get(int(account["id"]))
    if existing_task and not existing_task.done():
        raise RuntimeError(f"La cuenta @{campaign['username']} ya tiene un warmup corriendo.")

    await _run_account_warmup(int(account["id"]), campaign["username"], int(campaign["warmup_minutes"]), linked_campaign_id=campaign_id)


async def _save_instagram_session(username: str, context, workspace_slug: Optional[str] = None) -> None:
    from scripts.session_manager import _get_session_dir, _get_storage_path

    storage_path = _get_storage_path(username, workspace_slug)
    await context.storage_state(path=str(storage_path))
    cookies = await context.cookies("https://www.instagram.com")
    session_cookies = [c["name"] for c in cookies if c.get("name") in ("sessionid", "ds_user_id")]
    meta_path = _get_session_dir(username, workspace_slug) / "session_meta.json"
    meta_path.write_text(json.dumps({
        "username": username,
        "created_at": datetime.now().isoformat(),
        "last_used": datetime.now().isoformat(),
        "login_method": "dashboard_manual",
        "cookies_count": len(cookies),
        "session_cookies": session_cookies,
    }, indent=2), encoding="utf-8")


async def _run_campaign_simulation(campaign_id: str) -> None:
    campaign = CAMPAIGN_STORE.get(campaign_id)
    if not campaign:
        return

    campaign["status"] = "running"
    campaign["progress"] = 5
    campaign["current_action"] = "Inicializando pipeline de prueba"
    _append_campaign_log(campaign, "Modo test: no se extraeran leads reales.")
    await asyncio.sleep(2)

    sources = campaign.get("sources", [])
    total_steps = max(1, len(sources) * 3)
    completed_steps = 0

    for source in sources:
        campaign = CAMPAIGN_STORE.get(campaign_id)
        if not campaign or campaign.get("status") != "running":
            return

        source_label = f"{source['type']}:{source['value']}"
        for step_message in [
            f"Abriendo fuente {source_label}",
            f"Analizando perfiles desde {source_label}",
            f"Validando candidatos de {source_label}",
        ]:
            campaign = CAMPAIGN_STORE.get(campaign_id)
            if not campaign or campaign.get("status") != "running":
                return

            campaign["current_action"] = step_message
            completed_steps += 1
            campaign["progress"] = min(95, int((completed_steps / total_steps) * 100))
            _append_campaign_log(campaign, step_message)
            await asyncio.sleep(2)

    campaign = CAMPAIGN_STORE.get(campaign_id)
    if not campaign:
        return

    campaign["status"] = "completed"
    campaign["progress"] = 100
    campaign["current_action"] = "Modo test finalizado. No se ejecutaron extracciones reales."
    _append_campaign_log(campaign, "Pipeline de prueba completado sin tocar el CRM.")


async def _run_campaign_scraping(campaign_id: str) -> None:
    from scripts.lead_scraper import STATUS_FILE, run_scraper

    def _humanize_campaign_error(raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return "No se pudo completar esta fuente."
        text = re.sub(r"\b[A-Za-z_]*Error:\s*", "", text)
        text = text.replace("|", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if text.lower().startswith("timeout iniciando"):
            return "La fuente tardó demasiado en responder."
        if "No se pudo cargar una sesion valida" in text:
            return "No hay una sesión activa válida para hacer scraping."
        if "ERR_HTTP_RESPONSE_CODE_FAILURE" in text or "Page.goto" in text or "chrome-error://chromewebdata/" in text:
            return "Instagram mostró posts, pero bloqueó la apertura de varios posts individuales en esta sesión. Seguimos con los demás candidatos cuando es posible."
        return text

    campaign = CAMPAIGN_STORE.get(campaign_id)
    if not campaign:
        return

    try:
        was_paused = campaign.get("status") == "paused"
        campaign["status"] = "running"
        campaign["progress"] = max(int(campaign.get("progress") or 0), 5)
        campaign["current_action"] = "Reanudando extractor real de Instagram" if was_paused else "Inicializando extractor real de Instagram"
        _append_campaign_log(campaign, "Motor de scraping real reanudado." if was_paused else "Motor de scraping real inicializado.")

        sources = campaign.get("sources", [])
        executable_sources = [source for source in sources if source["type"] in {"hashtag", "followers", "location"}]
        skipped_sources = [source for source in sources if source["type"] not in {"hashtag", "followers", "location"}]

        for skipped in skipped_sources:
            _append_campaign_log(campaign, f"Source omitido por ahora: {skipped['type']}:{skipped['value']} (aun no implementado en scraper real).")

        if not executable_sources:
            campaign["status"] = "completed"
            campaign["progress"] = 100
            campaign["current_action"] = "No habia sources ejecutables en el extractor real."
            _append_campaign_log(campaign, "Campana completada sin ejecucion real porque solo habia sources no soportados.")
            return

        leads_before = _count_leads_for_campaign(campaign_id)
        limit_per_source = max(1, campaign["limit"] // len(executable_sources) or 1)

        sources_done = 0
        for index, source in enumerate(executable_sources, start=1):
            campaign = CAMPAIGN_STORE.get(campaign_id)
            if not campaign or campaign.get("status") != "running":
                return

            source_label = f"{source['type']}:{source['value']}"
            campaign_username = str(campaign["username"])
            source_filters = _filters_for_source(campaign.get("filters", {}), source["type"])
            existing_stats = campaign.setdefault("source_stats", {}).get(source_label)
            if isinstance(existing_stats, dict) and campaign.get("status") == "running":
                accepted_base = int(existing_stats.get("accepted") or 0)
                rejected_base = existing_stats.get("rejected") if isinstance(existing_stats.get("rejected"), dict) else {}
            else:
                accepted_base = 0
                rejected_base = {}
            campaign.setdefault("source_stats", {})[source_label] = {
                "accepted": accepted_base,
                "rejected": rejected_base,
                "status": "running",
            }
            _append_campaign_log(campaign, f"Ejecutando extractor real sobre {source_label}.")
            if STATUS_FILE.exists():
                STATUS_FILE.unlink()

            def _run_scraper_isolated() -> Any:
                if sys.platform == "win32":
                    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                previous_env = _set_workspace_env(int(campaign.get("workspace_id") or 0))
                try:
                    return loop.run_until_complete(
                        run_scraper(
                            source["type"],
                            source["value"],
                            limit_per_source,
                            username=campaign_username,
                            filters=source_filters,
                            campaign_id=campaign_id,
                        )
                    )
                finally:
                    _restore_workspace_env(previous_env)
                    loop.close()

            scraper_task = asyncio.create_task(asyncio.to_thread(_run_scraper_isolated))
            source_started_at = time.time()

            try:
                while not scraper_task.done():
                    campaign = CAMPAIGN_STORE.get(campaign_id)
                    if not campaign:
                        scraper_task.cancel()
                        return
                    if campaign.get("status") != "running":
                        scraper_task.cancel()
                        return

                    if time.time() - source_started_at > 90 and not STATUS_FILE.exists():
                        scraper_task.cancel()
                        raise RuntimeError(f"Timeout iniciando {source_label}. El extractor no emitio progreso en 90s.")

                    if STATUS_FILE.exists():
                        try:
                            status_data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
                            source_progress = int(status_data.get("progress", 0))
                            source_total = int(status_data.get("total", limit_per_source)) or limit_per_source
                            source_percent = int((source_progress / source_total) * 100) if source_total else 0
                            overall = int(((index - 1) + (source_percent / 100)) / len(executable_sources) * 100)
                            campaign["progress"] = min(99, max(campaign["progress"], overall))
                            campaign["current_action"] = f"{source_label} · {status_data.get('message', 'Extrayendo leads...')}"
                            meta = status_data.get("meta") or {}
                            campaign["source_stats"][source_label] = {
                                "accepted": int(meta.get("accepted_count", 0)),
                                "rejected": meta.get("rejected", {}),
                                "status": status_data.get("status", "running"),
                                "posts_seen": int(meta.get("posts_seen", 0)),
                                "authors_seen": int(meta.get("authors_seen", 0)),
                                "profile_errors": int(meta.get("profile_errors", 0)),
                            }
                        except Exception:
                            pass

                    await asyncio.sleep(1)

                await scraper_task
                campaign = CAMPAIGN_STORE.get(campaign_id)
                if not campaign:
                    return
                sources_done += 1
                campaign["progress"] = min(99, int(index / len(executable_sources) * 100))
                campaign["source_stats"][source_label]["status"] = "done"
                _append_campaign_log(campaign, f"Fuente completada: {source_label}.")
            except Exception as source_exc:
                campaign = CAMPAIGN_STORE.get(campaign_id)
                if not campaign:
                    return
                source_detail = str(source_exc).strip()
                status_detail = ""
                if STATUS_FILE.exists():
                    try:
                        status_data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
                        status_msg = str(status_data.get("message") or "").strip()
                        if status_msg:
                            status_detail = status_msg
                    except Exception:
                        pass
                if status_detail and status_detail not in source_detail:
                    source_detail = f"{source_detail} | {status_detail}" if source_detail else status_detail

                operator_detail = _humanize_campaign_error(source_detail)

                campaign["source_stats"][source_label]["status"] = "invalid"
                campaign["source_stats"][source_label]["error"] = operator_detail[:220]
                _append_campaign_log(campaign, f"Fuente descartada: {source_label} · {operator_detail[:180]}")
                continue

        campaign = CAMPAIGN_STORE.get(campaign_id)
        if not campaign:
            return

        leads_after = _count_leads_for_campaign(campaign_id)
        leads_delta = max(0, leads_after - leads_before)
        campaign["leads_found"] = leads_delta
        if leads_delta <= 0 and sources_done <= 0:
            campaign["status"] = "needs_review"
            campaign["progress"] = 0
            campaign["current_action"] = "No se encontraron fuentes válidas. Revisá los hashtags sugeridos y probá variantes singular/plural."
            _append_campaign_log(campaign, campaign["current_action"])
            return

        campaign["status"] = "completed"
        campaign["progress"] = 100
        has_warnings = any(
            isinstance(stats, dict) and stats.get("status") in {"invalid", "error"}
            for stats in (campaign.get("source_stats") or {}).values()
        )
        if has_warnings:
            campaign["current_action"] = f"Extraccion finalizada con avisos. {leads_delta} lead(s) nuevos enviados al CRM."
            _append_campaign_log(campaign, f"Campana completada con avisos. {leads_delta} lead(s) nuevos en CRM.")
        else:
            campaign["current_action"] = f"Extraccion finalizada. {leads_delta} lead(s) nuevos enviados al CRM."
            _append_campaign_log(campaign, f"Campana completada. {leads_delta} lead(s) nuevos en CRM.")
    except Exception as exc:
        campaign = CAMPAIGN_STORE.get(campaign_id)
        if campaign:
            detail = str(exc).strip()
            status_detail = ""
            if STATUS_FILE.exists():
                try:
                    status_data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
                    status_msg = str(status_data.get("message") or "").strip()
                    if status_msg:
                        status_detail = status_msg
                except Exception:
                    pass
            final_detail = detail
            if status_detail and status_detail not in final_detail:
                final_detail = f"{detail} | {status_detail}" if detail else status_detail
            operator_detail = _humanize_campaign_error(final_detail)
            campaign["status"] = "needs_review"
            campaign["current_action"] = f"No se pudo iniciar la extracción: {operator_detail}"[:220]
            campaign["progress"] = 0
            for source_label, stats in (campaign.get("source_stats") or {}).items():
                if isinstance(stats, dict) and stats.get("status") == "running":
                    stats["status"] = "invalid"
                    stats["error"] = operator_detail
            _append_campaign_log(campaign, campaign["current_action"])


def _serialize_campaign(campaign: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": campaign["id"],
        "campaign_name": campaign.get("campaign_name") or "",
        "username": campaign["username"],
        "limit": campaign["limit"],
        "execution_mode": campaign["execution_mode"],
        "filters": campaign.get("filters", {}),
        "filter_profile": campaign.get("filter_profile", "strict"),
        "sources": campaign["sources"],
        "source_stats": campaign.get("source_stats", {}),
        "warmup_mode": campaign["warmup_mode"],
        "warmup_minutes": campaign["warmup_minutes"],
        "status": campaign["status"],
        "current_action": campaign["current_action"],
        "progress": campaign["progress"],
        "created_at": campaign["created_at"],
        "logs": campaign.get("logs", []),
    }


def _filters_for_source(base_filters: Dict[str, Any], source_type: str) -> Dict[str, Any]:
    filters = dict(base_filters)
    profile = str(filters.get("filter_profile") or "strict").strip().lower()
    if profile not in ALLOWED_FILTER_PROFILES:
        profile = "strict"

    if source_type in {"hashtag", "location"}:
        filters["require_keyword_match"] = False
        return filters

    if source_type != "followers":
        return filters

    min_followers = int(filters.get("min_followers") or 0)
    min_posts = int(filters.get("min_posts") or 0)

    if profile == "balanced":
        filters["min_followers"] = max(15, min_followers // 2 if min_followers else 25)
        filters["min_posts"] = max(1, min_posts - 1)
        filters["require_keyword_match"] = False
        filters["followers_mode"] = "balanced"
    elif profile == "expansive":
        filters["min_followers"] = max(5, min_followers // 3 if min_followers else 10)
        filters["min_posts"] = 0 if min_posts <= 1 else max(1, min_posts - 2)
        filters["require_keyword_match"] = False
        filters["require_identity"] = False
        filters["followers_mode"] = "expansive"
    else:
        filters["followers_mode"] = "strict"

    return filters


def _tone_from_prompt(prompt: str) -> str:
    normalized = prompt.lower()
    if any(term in normalized for term in ["lujo", "premium", "high ticket"]):
        return "premium"
    if any(term in normalized for term in ["amigable", "cercano", "humano"]):
        return "friendly"
    return "direct"


BUSINESS_NAME_HINTS = {
    "inmobiliaria", "inmobiliario", "propiedades", "realty", "real", "estate", "homes",
    "group", "studio", "media", "capital", "broker", "bienes", "raices", "official",
    "class", "realestate", "prop", "developers", "desarrollos", "constructora", "realtors",
}


def _safe_greeting_name(lead: Dict[str, Any]) -> str:
    full_name = re.sub(r"\s+", " ", str(lead.get("full_name") or "").strip())
    username = str(lead.get("username") or lead.get("ig_username") or "").strip().lower()
    if not full_name:
      return ""

    lowered = full_name.lower()
    tokens = [re.sub(r"[^A-Za-zÁÉÍÓÚáéíóúÑñÜü]", "", token) for token in full_name.split()]
    tokens = [token for token in tokens if token]
    if not tokens:
      return ""

    if any(keyword in lowered or keyword in username for keyword in BUSINESS_NAME_HINTS):
        if len(tokens) >= 3:
            first_two = tokens[:2]
            if all(len(token) >= 2 for token in first_two) and all(token.lower() not in BUSINESS_NAME_HINTS for token in first_two):
                return " ".join(first_two)
        return ""

    if full_name.isupper() or len(tokens) > 2:
        return ""

    candidate = tokens[0] if len(tokens[0]) >= 3 else (" ".join(tokens[:2]) if len(tokens) >= 2 else "")
    if candidate and candidate.lower() not in BUSINESS_NAME_HINTS:
        return candidate
    return ""


def _generate_personalized_message(lead: Dict[str, Any], prompt: str) -> str:
    username = str(lead.get("username") or lead.get("ig_username") or "").strip()
    name_fragment = _safe_greeting_name(lead)
    tone = _tone_from_prompt(prompt)
    lead_status = str(lead.get("status") or "Pendiente")

    if name_fragment:
        greeting = f"Hola {name_fragment},"
    else:
        greeting = "Hola,"

    if lead_status == "Follow-up 1":
        opener = f"{greeting} retomo este mensaje por si te quedó colgado." if tone != "premium" else f"{greeting} vuelvo por aquí porque creo que puede interesarte esto."
    elif lead_status == "Follow-up 2":
        opener = f"{greeting} te dejo este último mensaje y no molesto más." if tone != "premium" else f"{greeting} cierro con este último mensaje por si ahora sí tiene sentido hablar."
    elif tone == "premium":
        opener = f"{greeting} creo que puede haber una forma elegante de ayudarte con esto."
    elif tone == "friendly":
        opener = f"{greeting} te escribo corto porque creo que esto podría servirte."
    else:
        opener = f"{greeting} te escribo porque creo que vale la pena abrir una conversación breve."

    close = prompt.strip()
    return f"{opener} {close}".strip()


def _sanitize_message_output(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    forbidden_patterns = [
        r"vi tu perfil desde",
        r"me dio contexto tu bio",
        r"hay fit",
        r"seguidores",
        r"publicaciones",
        r"hashtag[:#]",
    ]
    for pattern in forbidden_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _validate_message_quality(message: str) -> List[str]:
    issues: List[str] = []
    normalized = (message or "").strip()
    lowered = normalized.lower()
    if len(normalized) < 45:
        issues.append("too_short")
    if len(normalized) > 420:
        issues.append("too_long")
    forbidden_checks = {
        "mentions_source": ["hashtag", "source", "desde hashtag", "vi tu perfil desde"],
        "mentions_bio_literal": ["vi tu bio", "me dio contexto tu bio"],
        "robotic_phrase": ["hay fit", "te contacto porque", "sinergia", "encaje perfecto"],
        "hard_pitch": ["agenda una llamada", "compra ahora", "te vendo"],
    }
    for issue, tokens in forbidden_checks.items():
        if any(token in lowered for token in tokens):
            issues.append(issue)
    return issues


def _status_variant(status: str) -> str:
    normalized = (status or "Pendiente").strip()
    if normalized == "Follow-up 1":
        return "follow_up_1"
    if normalized == "Follow-up 2":
        return "follow_up_2"
    return "first_contact"


def _prompt_for_variant(payload: MessageStudioRequest | LeadRegenerateDraftRequest, variant: str) -> str:
    if variant == "follow_up_1":
        return (getattr(payload, "prompt_follow_up_1", None) or getattr(payload, "prompt", "") or "").strip()
    if variant == "follow_up_2":
        return (getattr(payload, "prompt_follow_up_2", None) or getattr(payload, "prompt", "") or "").strip()
    return (getattr(payload, "prompt_first_contact", None) or getattr(payload, "prompt", "") or "").strip()


DEFAULT_MASTER_PROMPT = (
    "Mantén un tono profesional y humano para Instagram DM B2B. "
    "Prioriza claridad, cercanía y una CTA suave; evita frases agresivas o robóticas."
)


def _resolve_master_prompt(payload: MessageStudioRequest | LeadRegenerateDraftRequest) -> str:
    mode = str(getattr(payload, "master_prompt_mode", "default") or "default").strip().lower()
    custom_prompt = str(getattr(payload, "master_prompt", "") or "").strip()
    if mode == "custom" and custom_prompt:
        return custom_prompt
    return DEFAULT_MASTER_PROMPT


def _build_lead_context_for_llm(lead: Dict[str, Any]) -> Dict[str, Any]:
    bio = str(lead.get("bio") or "").strip()
    bio_clean = re.sub(r"\s+", " ", bio)
    if len(bio_clean) > 180:
        bio_clean = bio_clean[:180] + "..."
    return {
        "username": str(lead.get("username") or lead.get("ig_username") or "").strip(),
        "first_name": _safe_greeting_name(lead),
        "full_name": str(lead.get("full_name") or "").strip(),
        "bio_summary": bio_clean,
        "source": str(lead.get("source") or "").strip(),
        "status": str(lead.get("status") or "Pendiente").strip(),
        "variant": _status_variant(str(lead.get("status") or "Pendiente")),
    }


def _extract_json_from_text(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _generate_gemini_message_bundle(system_prompt: str, user_payload: Dict[str, Any], google_api_key: str) -> Optional[Dict[str, Any]]:
    if not google_api_key or google_genai is None or google_genai_types is None:
        return None

    try:
        client = google_genai.Client(api_key=google_api_key)
        response = client.models.generate_content(
            model=os.getenv("GOOGLE_FLASH_MODEL", "gemini-3-flash"),
            contents=json.dumps(user_payload, ensure_ascii=False),
            config=google_genai_types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.8,
                response_mime_type="application/json",
            ),
        )
        return _extract_json_from_text(getattr(response, "text", "") or "")
    except Exception:
        return None


def _generate_ai_message_bundle(lead: Dict[str, Any], stage_prompt: str, master_prompt: str, workspace_id: Optional[int] = None) -> Dict[str, Any]:
    ai_config = _workspace_ai_config(workspace_id)
    google_api_key = ai_config["google_api_key"]
    openai_api_key = ai_config["openai_api_key"]
    context = _build_lead_context_for_llm(lead)
    fallback_message = _generate_personalized_message(lead, stage_prompt)
    fallback_bundle = {
        "message": _sanitize_message_output(fallback_message),
        "rationale": "Fallback local: mensaje breve basado en prompt maestro + etapa.",
        "variant": context["variant"],
        "provider": "local_fallback",
    }

    system_prompt = """
    Eres un copywriter senior de outreach para Instagram en español rioplatense/neutro.
    Tu tarea es escribir UN solo mensaje de DM corto, humano y natural.

    Reglas duras:
    - No pegues el prompt del operador literalmente.
    - No menciones hashtags, source interno, followers, publicaciones ni que viste la bio.
    - No uses frases roboticas como 'hay fit', 'te contacto porque', 'vi tu perfil desde'.
    - Si el nombre del lead no parece claramente humano, no lo uses en el saludo. Usa un saludo amigable generico.
    - No inventes datos.
    - Debe sonar como una persona real, no como un pitch automatizado.
    - CTA suave, sin presion.
    - Longitud objetivo: 220 a 360 caracteres.
    - Si es follow-up, debe sentirse como continuidad natural, no como un template viejo.

    Devuelve JSON exacto:
    {
      "message": "mensaje final listo para enviar",
      "rationale": "explicacion muy corta de 1 linea sobre el enfoque",
      "variant": "first_contact | follow_up_1 | follow_up_2"
    }
    """

    user_payload = {
        "master_prompt": master_prompt.strip(),
        "operator_prompt": stage_prompt.strip(),
        "lead_context": context,
    }

    gemini_data = _generate_gemini_message_bundle(system_prompt, user_payload, google_api_key)
    if isinstance(gemini_data, dict) and gemini_data:
        message = _sanitize_message_output(str(gemini_data.get("message") or "").strip())
        rationale = str(gemini_data.get("rationale") or "").strip()
        variant = str(gemini_data.get("variant") or context["variant"]).strip()
        if message and len(message) >= 35:
            issues = _validate_message_quality(message)
            if not issues:
                if variant not in {"first_contact", "follow_up_1", "follow_up_2"}:
                    variant = context["variant"]
                return {
                    "message": message,
                    "rationale": rationale or "Mensaje generado por Gemini con tono humano y CTA suave.",
                    "variant": variant,
                    "provider": os.getenv("GOOGLE_FLASH_MODEL", "gemini-3-flash"),
                }

    if not openai_api_key:
        return fallback_bundle

    try:
        client = openai.OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MESSAGE_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            temperature=0.8,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        message = _sanitize_message_output(str(data.get("message") or "").strip())
        rationale = str(data.get("rationale") or "").strip()
        variant = str(data.get("variant") or context["variant"]).strip()
        if not message or len(message) < 35:
            return fallback_bundle
        issues = _validate_message_quality(message)
        if issues:
            fallback_bundle["rationale"] = f"Fallback seguro por calidad: {', '.join(issues)}"
            return fallback_bundle
        if variant not in {"first_contact", "follow_up_1", "follow_up_2"}:
            variant = context["variant"]
        return {
            "message": message,
            "rationale": rationale or "Mensaje generado por IA con tono humano y CTA suave.",
            "variant": variant,
            "provider": os.getenv("OPENAI_MESSAGE_MODEL", "gpt-4o-mini"),
        }
    except Exception:
        return fallback_bundle


def _bundle_for_lead_with_payload(lead: Dict[str, Any], payload: MessageStudioRequest | LeadRegenerateDraftRequest) -> Dict[str, Any]:
    variant = _status_variant(str(lead.get("status") or "Pendiente"))
    prompt_for_variant = _prompt_for_variant(payload, variant)
    if not prompt_for_variant:
        raise HTTPException(status_code=400, detail=f"Falta prompt para {variant}.")
    master_prompt = _resolve_master_prompt(payload)
    bundle = _generate_ai_message_bundle(lead, prompt_for_variant, master_prompt, getattr(payload, "workspace_id", None))
    issues = _validate_message_quality(bundle["message"])
    bundle["quality_flags"] = issues
    bundle["variant"] = bundle.get("variant") or variant
    return bundle


def _serialize_message_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": job["id"],
        "kind": job.get("kind", "prepare"),
        "status": job["status"],
        "progress": job["progress"],
        "campaign_id": job.get("campaign_id"),
        "prompt": job["prompt"],
        "created_at": job["created_at"],
        "current_action": job["current_action"],
        "total": job["total"],
        "processed": job["processed"],
        "current_lead": job.get("current_lead"),
        "eta_seconds": job.get("eta_seconds"),
        "eta_min_seconds": job.get("eta_min_seconds"),
        "eta_max_seconds": job.get("eta_max_seconds"),
        "metrics": job.get("metrics", {}),
        "logs": job.get("logs", []),
    }


async def _run_message_outreach_job(job_id: str, lead_ids: List[int], dry_run: bool, campaign_id: Optional[str]) -> None:
    from scripts.outreach_manager import run_outreach

    job = MESSAGE_JOB_STORE.get(job_id)
    if not job:
        return

    main_loop = asyncio.get_running_loop()

    async def progress_hook(update: Dict[str, Any]) -> None:
        job["status"] = str(update.get("status") or job["status"])
        job["progress"] = int(update.get("progress") or job["progress"])
        job["current_action"] = str(update.get("current_action") or job["current_action"])
        if "processed" in update:
            job["processed"] = int(update.get("processed") or 0)
        if "total" in update:
            job["total"] = int(update.get("total") or 0)
        if "current_lead" in update:
            job["current_lead"] = str(update.get("current_lead") or "")
        if "eta_seconds" in update:
            try:
                job["eta_seconds"] = max(0, int(update.get("eta_seconds") or 0))
            except Exception:
                job["eta_seconds"] = None
        if "eta_min_seconds" in update:
            try:
                job["eta_min_seconds"] = max(0, int(update.get("eta_min_seconds") or 0))
            except Exception:
                job["eta_min_seconds"] = None
        if "eta_max_seconds" in update:
            try:
                job["eta_max_seconds"] = max(0, int(update.get("eta_max_seconds") or 0))
            except Exception:
                job["eta_max_seconds"] = None
        if isinstance(update.get("metrics"), dict):
            merged = dict(job.get("metrics") or {})
            merged.update(update.get("metrics") or {})
            job["metrics"] = merged
        if update.get("current_action"):
            job.setdefault("logs", []).insert(0, {
                "message": job["current_action"],
                "timestamp": int(time.time()),
            })
            job["logs"] = job["logs"][:12]
        _persist_message_job(job)

    try:
        job["status"] = "running"
        job["current_action"] = "Calentando sesion y preparando envio real."

        # Uvicorn runs on a SelectorEventLoop on Windows, breaking Patchright's subprocess requirement.
        # We must isolate the run_outreach call to a separate thread with a clean ProactorEventLoop.
        def _run_isolated_outreach():
            import sys
            import asyncio
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            previous_env = _set_workspace_env(int(job.get("workspace_id") or 0))

            async def sync_progress_hook(update: Dict[str, Any]):
                if main_loop and not main_loop.is_closed():
                    asyncio.run_coroutine_threadsafe(progress_hook(update), main_loop)

            try:
                return loop.run_until_complete(
                    run_outreach(
                        dry_run=dry_run,
                        lead_ids=lead_ids,
                        limit_override=len(lead_ids) if lead_ids else None,
                        progress_hook=sync_progress_hook,
                    )
                )
            finally:
                _restore_workspace_env(previous_env)
                loop.close()

        result = await asyncio.to_thread(_run_isolated_outreach)

        job["status"] = "completed"
        job["progress"] = 100
        job["processed"] = int(result.get("processed") or 0)
        job["total"] = max(int(result.get("processed") or 0), int(job.get("total") or 0))
        job["current_lead"] = None
        job["eta_seconds"] = 0
        job["eta_min_seconds"] = 0
        job["eta_max_seconds"] = 0
        sent = int(result.get("sent") or 0)
        job["metrics"] = {
            "sent": sent,
            "errors": int(result.get("errors") or 0),
            "blocked": int(result.get("blocked") or 0),
            "no_dm_button": int(result.get("no_dm_button") or 0),
        }
        job["current_action"] = f"Outreach completado. {sent} DM(s) enviados{' en dry run' if dry_run else ''}."
        job.setdefault("logs", []).insert(0, {"message": job["current_action"], "timestamp": int(time.time())})
        _persist_message_job(job)
    except Exception as exc:
        import traceback
        err_str = traceback.format_exc()
        print("Outreach job failed:", err_str)
        job["status"] = "error"
        job["progress"] = 0
        job["current_lead"] = None
        job["current_action"] = f"Error en outreach: {exc}"[:150]
        job.setdefault("logs", []).insert(0, {"message": job["current_action"], "timestamp": int(time.time()), "details": err_str})
        _persist_message_job(job)


def _infer_strategy_fallback(prompt: str) -> MagicBoxResponse:
    normalized = prompt.lower()

    if any(term in normalized for term in ["broker", "inmobili", "real estate", "realtor"]):
        return MagicBoxResponse(
            sources=[
                StrategySourceResponse(type="hashtag", target="brokersinmobiliarios"),
                StrategySourceResponse(type="hashtag", target="inmobiliariasmexico"),
            ],
            reasoning="Para brokers inmobiliarios en Mexico conviene usar hashtags compuestos y de nicho que ya integren profesion + mercado, en vez de separar location por otro carril. Asi el scraping entra por una sola via semantica mas cercana a como Instagram agrupa contenido del sector."
        )

    if any(term in normalized for term in ["agencia", "marketing", "ads", "publicidad"]):
        return MagicBoxResponse(
            sources=[
                StrategySourceResponse(type="followers", target="hubspotlatam"),
                StrategySourceResponse(type="hashtag", target="agenciademarketing"),
            ],
            reasoning="Para agencias, mezclo una cuenta semilla del sector con un hashtag vertical para no depender de una sola puerta de entrada. Eso mejora cobertura manteniendo relevancia de nicho."
        )

    return MagicBoxResponse(
        sources=[
            StrategySourceResponse(type="hashtag", target="negociosb2b"),
        ],
        reasoning="Fallback conservador: empiezo por un hashtag de negocio relativamente acotado para evitar ruido extremo mientras se afina el nicho con una instruccion mas especifica."
    )


def _normalize_hashtag_target(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "", str(value or "").replace("#", "").strip().lower())


def _normalize_intent_text(value: str) -> str:
    lowered = str(value or "").lower()
    return lowered.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")


GEO_ALIAS_MAP: Dict[str, List[str]] = {
    "buenosaires": ["bsas", "caba", "baires"],
    "ciudaddebuenosaires": ["caba", "bsas", "baires"],
    "ciudaddemexico": ["cdmx", "mx"],
}

INTENT_STOPWORDS = {
    "busco", "buscar", "quiero", "necesito", "gente", "personas", "cuentas", "leads", "prospectos",
    "de", "del", "la", "las", "el", "los", "en", "para", "con", "sin", "por", "que", "y", "o",
    "una", "un", "unos", "unas", "mi", "tu", "su", "sus", "al", "a", "desde", "hasta",
}


def _normalize_filter_terms(values: Any) -> List[str]:
    normalized: List[str] = []
    seen: set[str] = set()
    if not isinstance(values, list):
        return normalized
    for raw in values:
        term = _normalize_intent_text(str(raw or "").strip())
        if not term or term in seen or len(term) < 3:
            continue
        seen.add(term)
        normalized.append(term)
    return normalized[:12]


def _infer_filter_context_from_prompt(prompt: str) -> StrategyFilterContext:
    normalized = _normalize_intent_text(prompt)
    raw_tokens = re.findall(r"[a-z0-9]+", normalized)
    include_terms: List[str] = []
    seen: set[str] = set()
    for token in raw_tokens:
        if len(token) < 4 or token in INTENT_STOPWORDS or token in seen:
            continue
        seen.add(token)
        include_terms.append(token)
    return StrategyFilterContext(intent_summary=prompt.strip()[:120], include_terms=include_terms[:10], exclude_terms=[])

TRUNCATED_HASHTAG_PATTERNS = (
    "buenosaire",
    "buenosair",
    "argentin",
    "mexic",
    "ciudaddemexic",
)


def _is_suspicious_variant(value: str) -> bool:
    normalized = _normalize_hashtag_target(value)
    if len(normalized) < 5:
        return True
    return any(normalized.endswith(fragment) for fragment in TRUNCATED_HASHTAG_PATTERNS)


def _strategy_hashtag_variants(value: str) -> List[str]:
    base = _normalize_hashtag_target(value)
    if not base:
        return []

    variants: List[str] = [base]

    for geo_token, aliases in GEO_ALIAS_MAP.items():
        if geo_token in base:
            for alias in aliases:
                variants.append(base.replace(geo_token, alias))

    deduped: List[str] = []
    seen: set[str] = set()
    for candidate in variants:
        normalized = _normalize_hashtag_target(candidate)
        if normalized and normalized not in seen and not _is_suspicious_variant(normalized):
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _normalize_strategy_payload(data: Dict[str, Any], prompt: str) -> MagicBoxResponse:
    raw_sources = data.get("sources") or []
    reasoning = str(data.get("reasoning") or "").strip()
    raw_filter_context = data.get("filter_context") or {}

    normalized_sources: List[StrategySourceResponse] = []
    if isinstance(raw_sources, list):
        for source in raw_sources:
            if not isinstance(source, dict):
                continue
            raw_type = str(source.get("type") or "").strip().lower()
            raw_target = str(source.get("target") or source.get("value") or "").replace("@", "").replace("#", "").strip()
            if raw_type in ALLOWED_STRATEGY_TYPES and raw_target and raw_target.lower() not in {"undefined", "null", "none", "n/a"}:
                normalized_sources.append(StrategySourceResponse(type=raw_type, target=raw_target))

    if not normalized_sources:
        raw_type = str(data.get("type") or "hashtag").strip().lower()
        raw_target = str(data.get("target") or data.get("query") or data.get("seed") or "").replace("@", "").replace("#", "").strip()
        if raw_type in ALLOWED_STRATEGY_TYPES and raw_target and raw_target.lower() not in {"undefined", "null", "none", "n/a"}:
            normalized_sources.append(StrategySourceResponse(type=raw_type, target=raw_target))

    normalized_sources = [source for source in normalized_sources if source.type == "hashtag"]

    expanded_sources: List[StrategySourceResponse] = []
    seen_targets: set[str] = set()
    for source in normalized_sources:
        for variant in _strategy_hashtag_variants(source.target):
            if variant not in seen_targets:
                seen_targets.add(variant)
                expanded_sources.append(StrategySourceResponse(type="hashtag", target=variant))
    normalized_sources = expanded_sources

    if not normalized_sources:
        return _infer_strategy_fallback(prompt)

    if not reasoning:
        reasoning = "Este objetivo fue elegido por afinidad de nicho, senales de compra y menor ruido que un hashtag generico. Se incluyen variantes morfologicas para reducir falsos no-encontrados."

    filter_context = _infer_filter_context_from_prompt(prompt)
    if isinstance(raw_filter_context, dict):
        ai_summary = str(raw_filter_context.get("intent_summary") or "").strip()
        ai_include = _normalize_filter_terms(raw_filter_context.get("include_terms"))
        ai_exclude = _normalize_filter_terms(raw_filter_context.get("exclude_terms"))
        filter_context = StrategyFilterContext(
            intent_summary=ai_summary or filter_context.intent_summary,
            include_terms=ai_include or filter_context.include_terms,
            exclude_terms=ai_exclude,
        )

    return MagicBoxResponse(sources=normalized_sources[:3], reasoning=reasoning, filter_context=filter_context)


# ----------------------------------------------------- #
# Workspaces locales (modelo desktop local-first)
# ----------------------------------------------------- #
@app.get("/api/workspaces")
async def list_workspaces():
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, workspace_name, workspace_slug, full_name, email FROM users WHERE is_workspace = 1 ORDER BY id DESC"
    )
    rows = cursor.fetchall()
    conn.close()
    return {
        "workspaces": [
            {
                "id": int(row["id"]),
                "name": str(row["workspace_name"] or row["full_name"] or row["email"] or f"Workspace {row['id']}"),
                "slug": str(row["workspace_slug"] or _slugify_workspace_name(str(row["workspace_name"] or row["full_name"] or row["email"] or row["id"]))),
            }
            for row in rows
        ]
    }


@app.post("/api/workspaces")
async def create_workspace(req: WorkspaceCreateReq):
    workspace_name = str(req.name or "").strip()
    if len(workspace_name) < 2:
        raise HTTPException(status_code=400, detail="El nombre del workspace debe tener al menos 2 caracteres.")

    base_slug = _slugify_workspace_name(workspace_name)
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT workspace_slug FROM users WHERE workspace_slug LIKE ?", (f"{base_slug}%",))
    existing = {str(row[0]) for row in cursor.fetchall()}
    slug = base_slug
    suffix = 2
    while slug in existing:
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    synthetic_email = f"{slug}@botardium.local"
    cursor.execute(
        "INSERT INTO users (email, password_hash, full_name, workspace_name, workspace_slug, is_workspace) VALUES (?, '', ?, ?, ?, 1)",
        (synthetic_email, workspace_name, workspace_name, slug),
    )
    workspace_id = int(cursor.lastrowid)
    conn.commit()
    conn.close()
    return {"workspace_id": workspace_id, "name": workspace_name, "slug": slug}


@app.post("/api/workspaces/{workspace_id}/export")
async def export_workspace(workspace_id: int):
    archive_path = _build_workspace_export(workspace_id)
    return {
        "status": "exported",
        "path": str(archive_path),
        "filename": archive_path.name,
    }


@app.post("/api/workspaces/import")
async def import_workspace(payload: WorkspaceImportRequest):
    return _import_workspace_archive(payload.zip_path)


@app.get("/api/app/update-status")
async def get_app_update_status(current_version: Optional[str] = None):
    return _latest_release_status(current_version or _current_app_version())

@app.get("/api/accounts")
async def get_accounts(workspace_id: int):
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            id,
            ig_username,
            session_status,
            warmup_status,
            warmup_progress,
            warmup_last_run_at,
            warmup_last_duration_min,
            warmup_required,
            health_score,
            current_action,
            last_error,
            daily_dm_limit,
            daily_dm_sent,
            account_type,
            account_warmup_status,
            account_warmup_days_total,
            account_warmup_days_completed,
            session_warmup_last_run_at,
            session_warmup_phase
        FROM ig_accounts
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (workspace_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [_serialize_account(row) for row in rows]

class LoginBrowserReq(BaseModel):
    workspace_id: int


async def _wait_for_instagram_login(context, page, timeout_seconds: int = 180) -> None:
    start_time = asyncio.get_event_loop().time()

    while asyncio.get_event_loop().time() - start_time < timeout_seconds:
        if page.is_closed():
            raise HTTPException(
                status_code=400,
                detail="Se cerro la ventana de Instagram antes de que Botardium confirmara el login."
            )

        cookies = await context.cookies("https://www.instagram.com")
        session_cookies = {cookie.get("name") for cookie in cookies}
        if {"sessionid", "ds_user_id"}.intersection(session_cookies):
            return

        current_url = page.url
        if "/accounts/login" not in current_url and "/challenge/" not in current_url:
            return

        await asyncio.sleep(2)

    raise HTTPException(
        status_code=408,
        detail="Tiempo de espera agotado. El usuario no completo el login en Instagram."
    )


async def _extract_instagram_username(page) -> str:
    try:
        await page.goto("https://www.instagram.com/accounts/edit/", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        username_input = await page.query_selector('input[name="username"]')
        if username_input:
            value = await username_input.get_attribute("value")
            if value:
                return value.strip().lstrip("@")
    except Exception:
        pass

    try:
        await page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        profile_links = await page.query_selector_all('a[href*="/"][role="link"]')
        for link in profile_links:
            href = await link.get_attribute("href") or ""
            if href.count("/") == 2 and not any(x in href for x in ["/explore", "/direct", "/reels", "/accounts"]):
                return href.strip("/").lstrip("@")
    except Exception:
        pass

    raise HTTPException(status_code=400, detail="Login detectado pero no se pudo extraer el nombre de usuario.")

@app.post("/api/ig/login")
async def login_browser(req: LoginBrowserReq):
    """
    Abre un browser Chromium visible para que el usuario se loguee en Instagram.
    Detecta automáticamente el usuario logueado y lo registra en la base de datos.
    """
    session = None
    try:
        session = await create_stealth_browser(headless=False)
        browser = session.browser
        context = session.context
        page = session.page
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al iniciar navegador: {str(e)}")
    
    ig_username = None
    try:
        workspace_slug = _workspace_slug(req.workspace_id)
        await page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        await _wait_for_instagram_login(context, page)
        ig_username = await _extract_instagram_username(page)
        await _save_instagram_session(ig_username, context, workspace_slug)
        print(f"Usuario extraido: {ig_username}")

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el browser: {str(e)}")
    finally:
        await close_stealth_browser(session)

    # Guardar en la base de datos
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM ig_accounts WHERE user_id = ? AND ig_username = ?",
            (req.workspace_id, ig_username)
        )
        if cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail=f"La cuenta @{ig_username} ya está vinculada.")
        cursor.execute(
            """
            INSERT INTO ig_accounts (
                user_id, ig_username, ig_password, session_status,
                account_type, account_warmup_status, account_warmup_days_total, account_warmup_days_completed, daily_dm_limit
            ) VALUES (?, ?, '', 'verified', 'mature', 'completed', 0, 0, 20)
            """,
            (req.workspace_id, ig_username)
        )
        acc_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {"account_id": acc_id, "ig_username": ig_username, "status": "verified"}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/accounts")
async def add_account_legacy(req: AccountAddReq):
    """Endpoint legacy — redirige al flow del browser."""
    raise HTTPException(status_code=410, detail="Este endpoint fue reemplazado. Usa /api/ig/login")


@app.post("/api/accounts/warmup-bulk")
async def bulk_account_warmup(payload: AccountBulkWarmupRequest):
    from scripts.session_manager import session_exists

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if payload.account_ids:
        placeholders = ",".join("?" for _ in payload.account_ids)
        cursor.execute(
            f"SELECT * FROM ig_accounts WHERE user_id = ? AND id IN ({placeholders}) ORDER BY id DESC",
            [payload.workspace_id, *payload.account_ids],
        )
    else:
        cursor.execute(
            "SELECT * FROM ig_accounts WHERE user_id = ? AND (warmup_required = 1 OR warmup_status IN ('idle', 'error')) ORDER BY id DESC",
            (payload.workspace_id,),
        )
    rows = cursor.fetchall()
    conn.close()

    queued = 0
    for row in rows:
        account = dict(row)
        account_id = int(account["id"])
        task = ACCOUNT_WARMUP_TASKS.get(account_id)
        if task and not task.done():
            continue
        if not session_exists(account["ig_username"], _workspace_slug(int(account["user_id"]))):
            _update_account_runtime(
                account_id,
                warmup_status="error",
                warmup_progress=0,
                session_warmup_phase="error",
                current_action="No hay sesion guardada para iniciar warmup.",
                last_error="Sesion ausente. Re-loguea la cuenta desde Cuentas.",
            )
            continue
        _update_account_runtime(
            account_id,
            warmup_status="running",
            warmup_progress=1,
            session_warmup_phase="queued",
            current_action="Warmup en cola. Inicializando navegador...",
            last_error="",
        )
        ACCOUNT_WARMUP_TASKS[account_id] = asyncio.create_task(
            _run_account_warmup(account_id, account["ig_username"], payload.duration_min)
        )
        queued += 1

    return {"status": "queued", "queued": queued}


@app.post("/api/accounts/{account_id}/profile")
async def update_account_profile(account_id: int, payload: AccountProfileUpdateRequest):
    account_type = payload.account_type.strip().lower()
    if account_type not in {"mature", "new", "rehab"}:
        raise HTTPException(status_code=400, detail="Tipo de cuenta invalido.")
    total_days = 0 if account_type == "mature" else (7 if account_type == "new" else 5)
    status = "completed" if account_type == "mature" else "pending"
    completed = 0 if account_type != "mature" else 0
    daily_limit = 20 if account_type == "mature" else (10 if account_type == "new" else 8)
    _update_account_runtime(
        account_id,
        account_type=account_type,
        account_warmup_status=status,
        account_warmup_days_total=total_days,
        account_warmup_days_completed=completed,
        daily_dm_limit=daily_limit,
    )
    account = _get_account(account_id)
    return {"status": "updated", "account": _serialize_account(account or {"id": account_id, "account_type": account_type})}


@app.post("/api/accounts/{account_id}/account-warmup-day")
async def complete_account_warmup_day(account_id: int):
    account = _get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada.")
    total = max(int(account.get("account_warmup_days_total") or 0), 1)
    completed = min(total, int(account.get("account_warmup_days_completed") or 0) + 1)
    status = "completed" if completed >= total else "in_progress"
    _update_account_runtime(
        account_id,
        account_warmup_days_completed=completed,
        account_warmup_status=status,
        current_action=("Calentamiento de cuenta completado." if status == "completed" else f"Calentamiento de cuenta dia {completed}/{total}."),
    )
    return {"status": "updated", "completed_days": completed, "total_days": total}


@app.post("/api/accounts/{account_id}/warmup")
async def warmup_account(account_id: int, payload: AccountWarmupRequest):
    from scripts.session_manager import session_exists

    account = _get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada.")

    if not session_exists(account["ig_username"], _workspace_slug(int(account["user_id"]))):
        _update_account_runtime(
            account_id,
            warmup_status="error",
            warmup_progress=0,
            session_warmup_phase="error",
            current_action="No hay sesion guardada para iniciar warmup.",
            last_error="Sesion ausente. Re-loguea la cuenta desde Cuentas.",
        )
        raise HTTPException(status_code=409, detail=f"No hay sesion valida para @{account['ig_username']}. Re-loguea la cuenta desde Cuentas.")

    task = ACCOUNT_WARMUP_TASKS.get(account_id)
    if task and not task.done():
        raise HTTPException(status_code=400, detail="La cuenta ya tiene un warmup corriendo.")

    _update_account_runtime(
        account_id,
        warmup_status="running",
        warmup_progress=1,
        session_warmup_phase="queued",
        current_action="Warmup en cola. Inicializando navegador...",
        last_error="",
    )

    ACCOUNT_WARMUP_TASKS[account_id] = asyncio.create_task(
        _run_account_warmup(account_id, account["ig_username"], payload.duration_min)
    )
    return {"status": "queued", "account_id": account_id}


@app.post("/api/accounts/{account_id}/warmup-cancel")
async def cancel_account_warmup(account_id: int):
    task = ACCOUNT_WARMUP_TASKS.get(account_id)
    if task and not task.done():
        task.cancel()
    _update_account_runtime(
        account_id,
        warmup_status="idle",
        warmup_progress=0,
        current_action="Warmup cancelado por operador.",
    )
    return {"status": "cancelled", "account_id": account_id}


@app.post("/api/accounts/{account_id}/relogin")
async def relogin_account(account_id: int):
    account = _get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada.")

    session = None
    expected_username = str(account.get("ig_username") or "").strip().lstrip("@").lower()
    if not expected_username:
        raise HTTPException(status_code=400, detail="La cuenta no tiene username valido para re-login.")

    try:
        _update_account_runtime(
            account_id,
            current_action=f"Re-login manual en curso para @{expected_username}.",
            warmup_status="idle",
            warmup_progress=0,
            session_warmup_phase="idle",
            last_error="",
        )

        session = await create_stealth_browser(headless=False)
        context = session.context
        page = session.page

        await page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        await _wait_for_instagram_login(context, page)
        logged_username = (await _extract_instagram_username(page)).strip().lstrip("@").lower()

        if logged_username != expected_username:
            raise HTTPException(
                status_code=409,
                detail=f"Logueaste @{logged_username}, pero esta cuenta es @{expected_username}. Reintenta con la cuenta correcta.",
            )

        await _save_instagram_session(expected_username, context)
        _update_account_runtime(
            account_id,
            session_status="verified",
            last_error="",
            current_action="Sesion revalidada. Cuenta lista para warmup de sesion.",
            warmup_status="idle",
            warmup_progress=0,
            session_warmup_phase="idle",
        )
        return {"status": "ok", "account_id": account_id, "ig_username": expected_username}
    except HTTPException as exc:
        detail_msg = exc.detail if isinstance(exc.detail, str) and exc.detail.strip() else "Re-login abortado por una validacion de cuenta."
        _update_account_runtime(
            account_id,
            warmup_status="error",
            session_warmup_phase="error",
            current_action="Re-login fallido.",
            last_error=detail_msg,
        )
        raise
    except Exception as exc:
        detail_msg = str(exc).strip() or f"{exc.__class__.__name__} sin detalle"
        _update_account_runtime(
            account_id,
            warmup_status="error",
            session_warmup_phase="error",
            current_action="Re-login fallido.",
            last_error=detail_msg,
        )
        raise HTTPException(status_code=500, detail=f"Error en el re-login: {detail_msg}")
    finally:
        if session:
            await close_stealth_browser(session)

@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: int):
    task = ACCOUNT_WARMUP_TASKS.pop(account_id, None)
    if task and not task.done():
        task.cancel()
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ig_accounts WHERE id = ?", (account_id,))
    conn.commit()
    conn.close()
    return {"message": "Cuenta eliminada correctamente"}

# ----------------------------------------------------- #
# Endpoints de IA (Magic Box)
# ----------------------------------------------------- #
@app.post("/api/ai/strategy", response_model=MagicBoxResponse)
async def generate_strategy(payload: MagicBoxRequest):
    """
    Magic Box Brain: Procesa un input de lenguaje natural 
    y utiliza OpenAI para determinar la estrategia de scraping óptima.
    """
    ai_config = _workspace_ai_config(payload.workspace_id)
    openai_api_key = ai_config["openai_api_key"]
    google_api_key = ai_config["google_api_key"]
    if not openai_api_key and not google_api_key:
        raise HTTPException(status_code=412, detail="Necesitas API keys para usar Magic Box. Configúralas en API Keys.")

    system_prompt = '''
    Eres Botardium AI, el cerebro estrategico de MoveUp para prospeccion en Instagram.
    Tu trabajo es elegir hashtags de entrada de alto valor para scraping, no responder de forma generica.

    Debes priorizar precision de nicho:
    - Evita hashtags masivos o vagos como emprendedores, negocios, marketing, ventas, success.
    - Devuelve SOLO hashtags, no followers ni locations separadas.
    - Si la geografia importa, integrala dentro del hashtag cuando tenga sentido (ej. inmobiliariasmexico, realtormiami).
    - Prioriza hashtags compuestos y especificos del nicho, no aspiracionales.
    - Cuando sea natural, incluye variantes morfologicas del mismo hashtag (ej. singular/plural como esteticaargentina y esteticasargentina).
    - Si hay geografia, usa alias reales de uso comun (ej. buenosaires -> caba/bsas/baires) en vez de recortes invalidos.
    - NUNCA devuelvas hashtags truncados o mutilados (ej. buenosair, buenosaire, mexic).
    - Evita devolver 3 hashtags casi identicos; mezcla exacto + variante morfologica + variante cercana de alto volumen.
    - La explicacion debe decir por que ese objetivo tiene alta densidad de prospectos y menos ruido.

    Devuelve JSON exacto:
    {
      "sources": [
        {"type": "hashtag", "target": "valor sin @ ni #"}
      ],
      "reasoning": "maximo 2 frases, concretas y estrategicas",
      "filter_context": {
        "intent_summary": "resumen corto del nicho buscado",
        "include_terms": ["terminos positivos del nicho"],
        "exclude_terms": ["terminos claros de rubro incorrecto"]
      }
    }

    Reglas duras:
    - Devuelve entre 1 y 3 sources.
    - Cada target nunca puede ser vacio.
    - Todos los sources deben ser type=hashtag.
    - hashtag = hashtag sin #.
    - `include_terms` y `exclude_terms` deben ser utiles para filtrar perfiles reales del nicho pedido por el usuario.
    - `include_terms` debe incluir sinonimos y formas naturales del nicho, no solo el hashtag literal.
    - No inventes placeholders como undefined, null, none o n/a.
    - Si el usuario menciona ciudad o pais, intenta devolver un hashtag unico que combine nicho + geografia cuando sea natural.
    '''

    try:
        if openai_api_key:
            client = openai.OpenAI(api_key=openai_api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": payload.prompt}
                ],
                response_format={ "type": "json_object" },
                temperature=0.2
            )
            content = response.choices[0].message.content or "{}"
            data = json.loads(content)
            return _normalize_strategy_payload(data, payload.prompt)

        if google_api_key and google_genai is not None and google_genai_types is not None:
            client = google_genai.Client(api_key=google_api_key)
            response = client.models.generate_content(
                model=os.getenv("GOOGLE_FLASH_MODEL", "gemini-3-flash"),
                contents=payload.prompt,
                config=google_genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )
            return _normalize_strategy_payload(_extract_json_from_text(getattr(response, "text", "") or "{}"), payload.prompt)

    except Exception as e:
        print(f"Error AI: {e}")
        return _infer_strategy_fallback(payload.prompt)


@app.get("/api/workspaces/{workspace_id}/ai-settings")
async def get_workspace_ai_settings(workspace_id: int):
    config = _workspace_ai_config(workspace_id)
    status = _workspace_ai_status(workspace_id)
    return {
        "google_api_key": _mask_key(config["google_api_key"]),
        "openai_api_key": _mask_key(config["openai_api_key"]),
        **status,
    }


@app.post("/api/workspaces/{workspace_id}/ai-settings")
async def update_workspace_ai_settings(workspace_id: int, payload: WorkspaceAiSettingsRequest):
    conn = _connect_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET google_api_key = ?, openai_api_key = ? WHERE id = ?",
        ((payload.google_api_key or "").strip(), (payload.openai_api_key or "").strip(), workspace_id),
    )
    conn.commit()
    changed = cursor.rowcount
    conn.close()
    if not changed:
        raise HTTPException(status_code=404, detail="Workspace no encontrado.")
    return {"status": "saved", **_workspace_ai_status(workspace_id)}

# ----------------------------------------------------- #
# Endpoints de Bot Engine Core
# ----------------------------------------------------- #
@app.post("/api/bot/start")
async def start_bot(config: CampaignStartRequest):
    """
    Lanza la tarea asíncrona de Patchright Scraper/Outreach.
    """
    normalized_sources = []
    warmup_mode = config.warmup_mode.strip().lower()
    if warmup_mode not in ALLOWED_WARMUP_MODES:
        raise HTTPException(status_code=400, detail="Modo de warmup invalido.")

    execution_mode = config.execution_mode.strip().lower()
    if execution_mode not in ALLOWED_EXECUTION_MODES:
        raise HTTPException(status_code=400, detail="Modo de ejecucion invalido.")

    filter_profile = config.filter_profile.strip().lower()
    if filter_profile not in ALLOWED_FILTER_PROFILES:
        raise HTTPException(status_code=400, detail="Perfil de filtro invalido.")

    warmup_minutes = max(0, min(config.warmup_minutes, 30))

    for source in config.sources:
        source_type = source.type.strip().lower()
        source_value = source.value.replace("@", "").replace("#", "").strip()

        if source_type not in ALLOWED_STRATEGY_TYPES:
            raise HTTPException(status_code=400, detail=f"Tipo de targeting invalido: {source.type}")

        if not source_value:
            raise HTTPException(status_code=400, detail="Todos los sources deben tener un valor valido.")

        if source_value.lower() == config.username.lower():
            raise HTTPException(status_code=403, detail="🚨 ALERTA ROJA: Intento de Self-Scraping detectado. Prohibido apuntar a la cuenta propia.")

        normalized_sources.append({"type": source_type, "value": source_value})

    if not normalized_sources:
        raise HTTPException(status_code=400, detail="Debes enviar al menos un source para lanzar la campana.")

    campaign_id = str(uuid4())
    normalized_limit = max(5, int(config.limit or 0))
    normalized_name = str(config.campaign_name or "").strip()
    if not normalized_name:
        primary = normalized_sources[0]
        normalized_name = f"@{config.username} · {primary['type']}:{primary['value']}"
    initial_status = "ready" if warmup_mode == "skip" else "draft"
    initial_action = (
        "Lista para arrancar scraping sin warmup."
        if warmup_mode == "skip"
        else "Campana creada. Define warmup antes de iniciar scraping."
    )

    campaign = {
        "id": campaign_id,
        "workspace_id": int(config.workspace_id),
        "workspace_name": _workspace_name(int(config.workspace_id)),
        "campaign_name": normalized_name[:80],
        "username": config.username,
        "limit": normalized_limit,
        "sources": normalized_sources,
        "execution_mode": execution_mode,
        "filters": {
            "filter_profile": filter_profile,
            "min_followers": max(0, config.min_followers),
            "min_posts": max(0, config.min_posts),
            "require_identity": bool(config.require_identity),
            "require_keyword_match": bool(config.require_keyword_match),
            "require_coherence": bool(config.require_coherence),
            "strategy_context": (config.strategy_context.model_dump() if config.strategy_context else StrategyFilterContext().model_dump()),
        },
        "filter_profile": filter_profile,
        "warmup_mode": warmup_mode,
        "warmup_minutes": warmup_minutes,
        "status": initial_status,
        "current_action": initial_action,
        "progress": 0,
        "created_at": int(time.time()),
        "logs": [],
        "source_stats": {},
    }
    _append_campaign_log(campaign, initial_action)
    CAMPAIGN_STORE[campaign_id] = campaign
    _persist_campaign(campaign)

    return {
        "status": "started",
        "campaign": _serialize_campaign(campaign),
    }

@app.get("/api/bot/status")
async def get_bot_status(workspace_id: int):
    """Retorna el progreso en tiempo real (Polling)."""
    campaigns = _workspace_campaigns(workspace_id)
    return {
        "is_running": any(campaign.get("status") == "running" for campaign in campaigns),
        "campaigns": [_serialize_campaign(campaign) for campaign in campaigns],
    }


@app.post("/api/bot/{campaign_id}/action")
async def bot_campaign_action(campaign_id: str, payload: CampaignActionRequest):
    campaign = CAMPAIGN_STORE.get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campana no encontrada.")

    action = payload.action.strip().lower()

    if action == "delete":
        task = CAMPAIGN_TASKS.pop(campaign_id, None)
        if task and not task.done():
            task.cancel()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("UPDATE leads SET campaign_id = NULL WHERE campaign_id = ?", (campaign_id,))
        conn.commit()
        conn.close()
        del CAMPAIGN_STORE[campaign_id]
        _delete_campaign(campaign_id)
        return {"status": "deleted", "campaign_id": campaign_id}

    if action == "rename":
        normalized_name = str(payload.campaign_name or "").strip()
        if not normalized_name:
            raise HTTPException(status_code=400, detail="Debes escribir un nombre de campaña.")
        campaign["campaign_name"] = normalized_name[:80]
        _append_campaign_log(campaign, f"Nombre de campaña actualizado a: {campaign['campaign_name']}")
        _persist_campaign(campaign)
        return {"status": "updated", "campaign": _serialize_campaign(campaign)}

    if action == "start_warmup":
        task = CAMPAIGN_TASKS.get(campaign_id)
        if task and not task.done():
            raise HTTPException(status_code=400, detail="La campana ya esta ejecutandose.")
        CAMPAIGN_TASKS[campaign_id] = asyncio.create_task(_run_campaign_warmup(campaign_id))
        campaign["status"] = "warmup"
        campaign["progress"] = 5
        campaign["current_action"] = f"Warmup real en cola ({campaign['warmup_minutes']} min)"
        _append_campaign_log(campaign, campaign["current_action"])
        _persist_campaign(campaign)
        return {"status": "updated", "campaign": _serialize_campaign(campaign)}

    if action == "finish_warmup":
        campaign["status"] = "ready"
        campaign["progress"] = 35
        campaign["current_action"] = "Warmup completo. Lista para comenzar scraping."
        _append_campaign_log(campaign, campaign["current_action"])
        _persist_campaign(campaign)
        return {"status": "updated", "campaign": _serialize_campaign(campaign)}

    if action == "start_scraping":
        task = CAMPAIGN_TASKS.get(campaign_id)
        if task and not task.done():
            raise HTTPException(status_code=400, detail="La campana ya esta ejecutandose.")
        runner = _run_campaign_scraping if campaign.get("execution_mode") == "real" else _run_campaign_simulation
        CAMPAIGN_TASKS[campaign_id] = asyncio.create_task(runner(campaign_id))
        return {"status": "updated", "campaign": _serialize_campaign(campaign)}

    if action == "pause":
        task = CAMPAIGN_TASKS.get(campaign_id)
        if task and not task.done():
            task.cancel()
        campaign["status"] = "paused"
        campaign["current_action"] = f"Scraping pausado en {int(campaign.get('progress') or 0)}%. Puedes reanudar cuando quieras."
        _append_campaign_log(campaign, campaign["current_action"])
        _persist_campaign(campaign)
        return {"status": "updated", "campaign": _serialize_campaign(campaign)}

    raise HTTPException(status_code=400, detail="Accion no soportada.")

@app.get("/api/leads")
async def get_leads(workspace_id: int, campaign_id: Optional[str] = None):
    """Retorna los datos del CRM desde SQLite/Postgres."""
    try:
        conn = _connect_db()
        cursor = conn.cursor()
        base_query = """
            SELECT
                id,
                ig_username AS username,
                full_name,
                bio,
                campaign_id,
                status,
                source,
                created_at AS timestamp,
                contacted_at,
                last_message_preview,
                message_prompt,
                message_variant,
                last_message_rationale,
                sent_at,
                follow_up_due_at,
                last_outreach_result,
                last_outreach_error
            FROM leads
        """
        params: List[Any] = []
        if campaign_id:
            base_query += " WHERE workspace_id = ? AND campaign_id = ?"
            params.extend([workspace_id, campaign_id])
        else:
            base_query += " WHERE workspace_id = ?"
            params.append(workspace_id)
        base_query += " ORDER BY created_at DESC LIMIT 200"
        cursor.execute(base_query, params)
        rows = cursor.fetchall()
        
        leads = [dict(row) for row in rows]
        conn.close()
        return leads
    except Exception as e:
        return {"error": str(e), "leads": []}


@app.delete("/api/leads/{lead_id}")
async def delete_lead(lead_id: int):
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted", "lead_id": lead_id}


@app.post("/api/leads/bulk-delete")
async def bulk_delete_leads(payload: LeadBulkRequest):
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    if payload.ids:
        placeholders = ",".join("?" for _ in payload.ids)
        cursor.execute(f"DELETE FROM leads WHERE id IN ({placeholders})", payload.ids)
    else:
        cursor.execute("DELETE FROM leads")
    conn.commit()
    conn.close()
    return {"status": "deleted", "count": len(payload.ids) if payload.ids else "all"}


@app.post("/api/leads/bulk-status")
async def bulk_update_leads_status(payload: LeadBulkRequest):
    if not payload.ids:
        raise HTTPException(status_code=400, detail="Debes enviar ids para actualizar estado.")
    if not payload.status:
        raise HTTPException(status_code=400, detail="Debes enviar un status valido.")

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in payload.ids)
    cursor.execute(f"UPDATE leads SET status = ? WHERE id IN ({placeholders})", [payload.status, *payload.ids])
    conn.commit()
    conn.close()
    return {"status": "updated", "count": len(payload.ids), "new_status": payload.status}


@app.post("/api/leads/{lead_id}/draft")
async def update_lead_draft(lead_id: int, payload: LeadDraftUpdateRequest):
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="El borrador no puede quedar vacio.")
    quality_flags = _validate_message_quality(message)
    if quality_flags:
        raise HTTPException(status_code=400, detail=f"El borrador no pasa calidad minima: {', '.join(quality_flags)}")

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE leads SET last_message_preview = ?, message_variant = COALESCE(message_variant, 'v1-editado-manual') WHERE id = ?",
        (message, lead_id),
    )
    conn.commit()
    changed = cursor.rowcount
    conn.close()
    if not changed:
        raise HTTPException(status_code=404, detail="Lead no encontrado.")
    return {"status": "updated", "lead_id": lead_id}


@app.post("/api/leads/{lead_id}/regenerate-draft")
async def regenerate_lead_draft(lead_id: int, payload: LeadRegenerateDraftRequest):
    if not _workspace_ai_status(payload.workspace_id).get("lead_drafts_enabled"):
        raise HTTPException(status_code=412, detail="Necesitas API keys para regenerar borradores con IA. Configúralas en API Keys.")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, ig_username AS username, full_name, bio, source, campaign_id, status FROM leads WHERE id = ?",
        (lead_id,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Lead no encontrado.")
    lead = dict(row)
    bundle = _bundle_for_lead_with_payload(lead, payload)
    cursor.execute(
        "UPDATE leads SET last_message_preview = ?, message_variant = ?, last_message_rationale = ? WHERE id = ?",
        (bundle["message"], bundle["variant"], bundle["rationale"], lead_id),
    )
    conn.commit()
    conn.close()
    return {
        "status": "updated",
        "lead_id": lead_id,
        "message": bundle["message"],
        "rationale": bundle["rationale"],
        "variant": bundle["variant"],
        "provider": bundle.get("provider", "unknown"),
        "quality_flags": bundle.get("quality_flags", []),
    }


@app.post("/api/messages/preview")
async def preview_messages(payload: MessageStudioRequest):
    if not _workspace_ai_status(payload.workspace_id).get("message_studio_enabled"):
        raise HTTPException(status_code=412, detail="Necesitas API keys para generar mensajes con IA. Configúralas en API Keys.")
    if not payload.ids:
        raise HTTPException(status_code=400, detail="Debes seleccionar al menos un lead.")
    if not any([
        (payload.prompt or "").strip(),
        (payload.prompt_first_contact or "").strip(),
        (payload.prompt_follow_up_1 or "").strip(),
        (payload.prompt_follow_up_2 or "").strip(),
    ]):
        raise HTTPException(status_code=400, detail="Debes escribir al menos un prompt para generar mensajes.")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in payload.ids)
    cursor.execute(
        f"SELECT id, ig_username AS username, full_name, bio, source, campaign_id, status FROM leads WHERE workspace_id = ? AND id IN ({placeholders}) ORDER BY created_at DESC",
        [payload.workspace_id, *payload.ids],
    )
    rows = [dict(row) for row in cursor.fetchall()]

    previews = []
    for lead in rows:
        bundle = _bundle_for_lead_with_payload(lead, payload)
        message = bundle["message"]
        previews.append({
            "id": lead["id"],
            "username": lead["username"],
            "message": message,
            "status": lead.get("status"),
            "rationale": bundle["rationale"],
            "variant": bundle["variant"],
            "provider": bundle.get("provider", "unknown"),
            "quality_flags": bundle.get("quality_flags", []),
        })
        cursor.execute(
            "UPDATE leads SET last_message_preview = ?, message_prompt = ?, message_variant = ?, last_message_rationale = ? WHERE id = ?",
            (_sanitize_message_output(message), _prompt_for_variant(payload, bundle["variant"]), bundle["variant"], bundle["rationale"], lead["id"]),
        )

    conn.commit()
    conn.close()
    return {"count": len(previews), "previews": previews}


@app.post("/api/messages/queue")
async def queue_messages(payload: MessageQueueRequest):
    if not _workspace_ai_status(payload.workspace_id).get("message_studio_enabled"):
        raise HTTPException(status_code=412, detail="Necesitas API keys para actualizar borradores con IA. Configúralas en API Keys.")
    if not payload.ids:
        raise HTTPException(status_code=400, detail="Debes seleccionar al menos un lead.")
    if not any([
        (payload.prompt or "").strip(),
        (payload.prompt_first_contact or "").strip(),
        (payload.prompt_follow_up_1 or "").strip(),
        (payload.prompt_follow_up_2 or "").strip(),
    ]):
        raise HTTPException(status_code=400, detail="Debes escribir al menos un prompt para guardar borradores.")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in payload.ids)
    cursor.execute(
        f"SELECT id, ig_username AS username, full_name, bio, source, campaign_id, status FROM leads WHERE workspace_id = ? AND id IN ({placeholders}) ORDER BY created_at DESC",
        [payload.workspace_id, *payload.ids],
    )
    rows = [dict(row) for row in cursor.fetchall()]
    if not rows:
        conn.close()
        raise HTTPException(status_code=404, detail="No se encontraron leads para encolar.")

    job_id = str(uuid4())
    job = {
        "id": job_id,
        "workspace_id": int(payload.workspace_id),
        "status": "queued",
        "progress": 0,
        "campaign_id": payload.campaign_id,
        "prompt": payload.prompt.strip(),
        "created_at": int(time.time()),
        "current_action": "Preparando cola de mensajeria personalizada.",
        "total": len(rows),
        "processed": 0,
        "metrics": {"generated": 0, "errors": 0},
        "logs": [],
    }
    MESSAGE_JOB_STORE[job_id] = job
    _persist_message_job(job)

    now = datetime.now()
    follow_up_due = now.timestamp() + max(1, payload.follow_up_days) * 86400
    for idx, lead in enumerate(rows, start=1):
        studio_payload = MessageStudioRequest(
            workspace_id=payload.workspace_id,
            ids=[lead["id"]],
            prompt=payload.prompt,
            prompt_first_contact=payload.prompt_first_contact,
            prompt_follow_up_1=payload.prompt_follow_up_1,
            prompt_follow_up_2=payload.prompt_follow_up_2,
        )
        bundle = _bundle_for_lead_with_payload(lead, studio_payload)
        message = bundle["message"]
        cursor.execute(
            """
            UPDATE leads
            SET status = ?,
                last_message_preview = ?,
                message_prompt = ?,
                message_variant = ?,
                last_message_rationale = ?,
                sent_at = ?,
                follow_up_due_at = ?,
                contacted_at = ?
            WHERE id = ?
            """,
            (
                "Listo para contactar",
                message,
                payload.prompt.strip(),
                bundle["variant"],
                bundle["rationale"],
                None,
                datetime.fromtimestamp(follow_up_due).isoformat(),
                None,
                lead["id"],
            ),
        )
        job["processed"] = idx
        job["progress"] = int((idx / len(rows)) * 100)
        job["status"] = "running" if idx < len(rows) else "completed"
        job["metrics"]["generated"] = idx
        job["current_action"] = f"Lead @{lead['username']} agregado a la cola personalizada."
        job.setdefault("logs", []).insert(0, {"message": job["current_action"], "timestamp": int(time.time())})
        job["logs"] = job["logs"][:12]
        _persist_message_job(job)

    conn.commit()
    conn.close()
    job["status"] = "completed"
    job["current_action"] = f"Cola lista. {len(rows)} lead(s) quedaron listos para contactar."
    _persist_message_job(job)
    return {"status": "queued", "job": _serialize_message_job(job)}


@app.post("/api/messages/run")
async def run_message_queue(payload: MessageRunRequest):
    if not payload.account_id:
        raise HTTPException(status_code=400, detail="Selecciona una cuenta emisora antes de enviar mensajes.")
    account = _get_account(payload.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Cuenta emisora no encontrada.")
    if _requires_account_warmup(account):
        raise HTTPException(status_code=409, detail="La cuenta aun necesita calentamiento de cuenta antes de hacer outreach.")
    if _requires_session_warmup(account) and not payload.override_cold_session:
        raise HTTPException(status_code=409, detail="Haz un calentamiento corto de sesion antes de enviar mensajes.")
    _write_runtime_account_profile(account)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    params: List[Any] = []
    query = "SELECT id FROM leads WHERE workspace_id = ? AND status IN ('Listo para contactar', 'Primer contacto', 'Follow-up 1')"
    params.append(payload.workspace_id)
    if payload.ids:
        placeholders = ",".join("?" for _ in payload.ids)
        query += f" AND id IN ({placeholders})"
        params.extend(payload.ids)
    if payload.campaign_id:
        query += " AND campaign_id = ?"
        params.append(payload.campaign_id)
    query += " ORDER BY created_at ASC LIMIT 50"
    cursor.execute(query, params)
    lead_ids = [int(row["id"]) for row in cursor.fetchall()]
    window_start = datetime.fromtimestamp(time.time() - 86400).isoformat()
    cursor.execute(
        "SELECT COUNT(*) FROM leads WHERE ig_account_id = ? AND sent_at IS NOT NULL AND sent_at >= ?",
        (payload.account_id, window_start),
    )
    sent_last_24h = int(cursor.fetchone()[0])
    daily_limit = int(account.get("daily_dm_limit") or 35)
    remaining = max(0, daily_limit - sent_last_24h)
    if remaining <= 0:
        conn.close()
        raise HTTPException(status_code=409, detail="Ya alcanzaste el limite diario configurado. Espera unas horas antes de seguir.")
    if len(lead_ids) > remaining:
        lead_ids = lead_ids[:remaining]
    if lead_ids:
        placeholders = ",".join("?" for _ in lead_ids)
        cursor.execute(f"UPDATE leads SET ig_account_id = ? WHERE id IN ({placeholders})", [payload.account_id, *lead_ids])
        cursor.execute("UPDATE ig_accounts SET daily_dm_sent = ? WHERE id = ?", (sent_last_24h, payload.account_id))
        conn.commit()
    conn.close()

    if not lead_ids:
        raise HTTPException(status_code=400, detail="No hay leads listos para ejecutar outreach.")

    job_id = str(uuid4())
    eta_min_seconds, eta_max_seconds = _estimate_account_send_window(payload.account_id, len(lead_ids))
    eta_seconds = max(60, int((eta_min_seconds + eta_max_seconds) / 2))
    job = {
        "id": job_id,
        "workspace_id": int(payload.workspace_id),
        "kind": "outreach",
        "status": "queued",
        "progress": 0,
        "campaign_id": payload.campaign_id,
        "prompt": "outreach-run",
        "created_at": int(time.time()),
        "current_action": ("Cola de envio creada. " + ("Se limitara al cupo diario restante." if remaining < len(payload.ids or lead_ids) else "" )).strip(),
        "total": len(lead_ids),
        "processed": 0,
        "current_lead": None,
        "eta_seconds": eta_seconds,
        "eta_min_seconds": eta_min_seconds,
        "eta_max_seconds": eta_max_seconds,
        "metrics": {"sent": 0, "errors": 0, "blocked": 0, "no_dm_button": 0},
        "logs": [],
    }
    MESSAGE_JOB_STORE[job_id] = job
    _persist_message_job(job)
    asyncio.create_task(_run_message_outreach_job(job_id, lead_ids, payload.dry_run, payload.campaign_id))
    return {"status": "started", "job": _serialize_message_job(job)}


@app.get("/api/messages/jobs")
async def get_message_jobs(workspace_id: int):
    jobs = sorted(_workspace_jobs(workspace_id), key=lambda job: job["created_at"], reverse=True)
    return {"jobs": [_serialize_message_job(job) for job in jobs[:20]]}

if __name__ == "__main__":
    import uvicorn
    # Inicializa el servidor dev
    uvicorn.run(app, host="0.0.0.0", port=8000)
