from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from dotenv import load_dotenv

from scripts.runtime_paths import ENV_EXAMPLE_PATH, ENV_PATH, RUNTIME_SECRETS_PATH

AI_SECRET_FIELDS = ("google_api_key", "openai_api_key")
SENSITIVE_FIELD_CLASSES = {
    "google_api_key": "ai_keys",
    "openai_api_key": "ai_keys",
    "anthropic_api_key": "ai_keys",
    "browser_use_api_key": "ai_keys",
    "context7_api_key": "tokens",
    "github_token": "tokens",
    "testsprite_api_key": "tokens",
    "ig_password": "credentials",
    "password": "credentials",
    "password_hash": "credentials",
    "cookies": "session_material",
    "session_cookies": "session_material",
    "storage_state": "session_material",
}
SESSION_PATH_MARKERS = (
    "sessions/",
    "storage_state.json",
    "session_meta.json",
    "cookies.json",
)


def load_bootstrap_env() -> Path:
    env_path = ENV_PATH if ENV_PATH.exists() else ENV_EXAMPLE_PATH
    load_dotenv(env_path)
    return env_path


def get_bootstrap_ai_config() -> Dict[str, str]:
    return {
        "google_api_key": str(os.getenv("GOOGLE_API_KEY", "") or "").strip(),
        "openai_api_key": str(os.getenv("OPENAI_API_KEY", "") or "").strip(),
    }


def redact_secret(value: str) -> str:
    secret = str(value or "").strip()
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"


def redact_mapping(payload: Mapping[str, Any], fields: Iterable[str] = AI_SECRET_FIELDS) -> Dict[str, Any]:
    redacted = dict(payload)
    for field in fields:
        if field in redacted:
            redacted[field] = redact_secret(str(redacted.get(field) or ""))
    return redacted


def _runtime_secret_store() -> Dict[str, Any]:
    if not RUNTIME_SECRETS_PATH.exists():
        return {"version": 1, "workspaces": {}}
    try:
        data = json.loads(RUNTIME_SECRETS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "workspaces": {}}
    if not isinstance(data, dict):
        return {"version": 1, "workspaces": {}}
    data.setdefault("version", 1)
    workspaces = data.get("workspaces")
    if not isinstance(workspaces, dict):
        data["workspaces"] = {}
    return data


def _write_runtime_secret_store(data: Mapping[str, Any]) -> None:
    RUNTIME_SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_SECRETS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(RUNTIME_SECRETS_PATH, 0o600)
    except OSError:
        pass


def get_workspace_ai_config(workspace_id: int | None, legacy_fallback: Mapping[str, Any] | None = None) -> Dict[str, str]:
    bootstrap = get_bootstrap_ai_config()
    if not workspace_id:
        return bootstrap

    store = _runtime_secret_store()
    workspace_config = store.get("workspaces", {}).get(str(int(workspace_id)), {})
    legacy = legacy_fallback or {}
    return {
        "google_api_key": str(
            workspace_config.get("google_api_key")
            or legacy.get("google_api_key")
            or bootstrap["google_api_key"]
            or ""
        ).strip(),
        "openai_api_key": str(
            workspace_config.get("openai_api_key")
            or legacy.get("openai_api_key")
            or bootstrap["openai_api_key"]
            or ""
        ).strip(),
    }


def save_workspace_ai_config(workspace_id: int, google_api_key: str = "", openai_api_key: str = "") -> Dict[str, str]:
    store = _runtime_secret_store()
    workspaces = store.setdefault("workspaces", {})
    payload = {
        "google_api_key": str(google_api_key or "").strip(),
        "openai_api_key": str(openai_api_key or "").strip(),
    }
    if payload["google_api_key"] or payload["openai_api_key"]:
        workspaces[str(int(workspace_id))] = payload
    else:
        workspaces.pop(str(int(workspace_id)), None)
    _write_runtime_secret_store(store)
    return payload


def clear_legacy_workspace_ai_secrets(conn: Any, workspace_id: int) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET google_api_key = '', openai_api_key = '' WHERE id = ?",
        (int(workspace_id),),
    )


def migrate_legacy_workspace_ai_secrets(conn: Any) -> int:
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(users)")
    columns = {str(row[1]) for row in cursor.fetchall()}
    if not {"google_api_key", "openai_api_key"}.issubset(columns):
        return 0

    cursor.execute(
        """
        SELECT id, google_api_key, openai_api_key
        FROM users
        WHERE COALESCE(google_api_key, '') != '' OR COALESCE(openai_api_key, '') != ''
        """
    )
    rows = cursor.fetchall()
    if not rows:
        return 0

    store = _runtime_secret_store()
    workspaces = store.setdefault("workspaces", {})
    migrated = 0
    for row in rows:
        workspace_id = str(int(row[0]))
        existing = dict(workspaces.get(workspace_id) or {})
        google_api_key = str(row[1] or "").strip()
        openai_api_key = str(row[2] or "").strip()
        if google_api_key and not existing.get("google_api_key"):
            existing["google_api_key"] = google_api_key
        if openai_api_key and not existing.get("openai_api_key"):
            existing["openai_api_key"] = openai_api_key
        if existing:
            workspaces[workspace_id] = existing
        cursor.execute(
            "UPDATE users SET google_api_key = '', openai_api_key = '' WHERE id = ?",
            (int(workspace_id),),
        )
        migrated += 1

    _write_runtime_secret_store(store)
    return migrated


def sanitize_workspace_export_payload(payload: Mapping[str, Any]) -> tuple[Dict[str, Any], list[str]]:
    omitted: set[str] = set()
    sanitized = _sanitize_value(payload, omitted)
    sanitized["omitted_data_classes"] = sorted(omitted)
    return sanitized, sorted(omitted)


def detect_sensitive_import_content(payload: Mapping[str, Any], archive_names: Sequence[str] | None = None) -> list[str]:
    violations: set[str] = set()
    _collect_sensitive_fields(payload, violations)
    for archive_name in archive_names or []:
        normalized = str(archive_name or "").replace("\\", "/").lower()
        if any(marker in normalized for marker in SESSION_PATH_MARKERS):
            violations.add("session_material")
    return sorted(violations)


def _sanitize_value(value: Any, omitted: set[str]) -> Any:
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            content_class = SENSITIVE_FIELD_CLASSES.get(str(key).lower())
            if content_class and _has_sensitive_value(item):
                omitted.add(content_class)
                continue
            sanitized[key] = _sanitize_value(item, omitted)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item, omitted) for item in value]
    return value


def _collect_sensitive_fields(value: Any, violations: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            content_class = SENSITIVE_FIELD_CLASSES.get(str(key).lower())
            if content_class and _has_sensitive_value(item):
                violations.add(content_class)
            _collect_sensitive_fields(item, violations)
        return
    if isinstance(value, list):
        for item in value:
            _collect_sensitive_fields(item, violations)


def _has_sensitive_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True
