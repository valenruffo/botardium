import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

from scripts.runtime_paths import CONFIG_DIR


AUTH_SECRET_PATH = CONFIG_DIR / "auth_session_secret.txt"
DEFAULT_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class AuthActor:
    actor_id: str
    workspace_id: int
    workspace_slug: str
    workspace_name: str
    token_id: str
    issued_at: int
    expires_at: int


def _urlsafe_b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _resolve_signing_secret() -> str:
    env_secret = str(os.getenv("BOTARDIUM_AUTH_SECRET") or "").strip()
    if env_secret:
        return env_secret

    AUTH_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if AUTH_SECRET_PATH.exists():
        secret = AUTH_SECRET_PATH.read_text(encoding="utf-8").strip()
        if secret:
            return secret

    secret = secrets.token_hex(32)
    AUTH_SECRET_PATH.write_text(secret, encoding="utf-8")
    return secret


def _sign_payload(payload_segment: str) -> str:
    secret = _resolve_signing_secret().encode("utf-8")
    signature = hmac.new(secret, payload_segment.encode("utf-8"), hashlib.sha256).digest()
    return _urlsafe_b64encode(signature)


def issue_workspace_token(
    workspace_id: int,
    workspace_slug: str,
    workspace_name: str,
    ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
) -> str:
    now = int(time.time())
    payload = {
        "actor_id": f"local-workspace:{int(workspace_id)}",
        "workspace_id": int(workspace_id),
        "workspace_slug": str(workspace_slug or f"workspace-{workspace_id}"),
        "workspace_name": str(workspace_name or f"Workspace {workspace_id}"),
        "iat": now,
        "exp": now + max(60, int(ttl_seconds)),
        "jti": secrets.token_hex(16),
    }
    payload_segment = _urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature_segment = _sign_payload(payload_segment)
    return f"{payload_segment}.{signature_segment}"


def verify_workspace_token(token: str) -> AuthActor:
    raw_token = str(token or "").strip()
    if not raw_token or "." not in raw_token:
        raise HTTPException(status_code=401, detail="Sesión inválida o ausente.")

    payload_segment, signature_segment = raw_token.split(".", 1)
    expected_signature = _sign_payload(payload_segment)
    if not hmac.compare_digest(signature_segment, expected_signature):
        raise HTTPException(status_code=401, detail="La sesión local ya no es válida. Inicia sesión otra vez.")

    try:
        payload = json.loads(_urlsafe_b64decode(payload_segment).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="No pude validar la sesión local.") from exc

    expires_at = int(payload.get("exp") or 0)
    if expires_at <= int(time.time()):
        raise HTTPException(status_code=401, detail="La sesión local expiró. Vuelve a entrar al workspace.")

    workspace_id = int(payload.get("workspace_id") or 0)
    if workspace_id <= 0:
        raise HTTPException(status_code=401, detail="La sesión no incluye un workspace válido.")

    return AuthActor(
        actor_id=str(payload.get("actor_id") or f"local-workspace:{workspace_id}"),
        workspace_id=workspace_id,
        workspace_slug=str(payload.get("workspace_slug") or f"workspace-{workspace_id}"),
        workspace_name=str(payload.get("workspace_name") or f"Workspace {workspace_id}"),
        token_id=str(payload.get("jti") or ""),
        issued_at=int(payload.get("iat") or 0),
        expires_at=expires_at,
    )


def actor_from_request(request: Request) -> AuthActor:
    authorization = str(request.headers.get("authorization") or "").strip()
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Necesitas una sesión local activa para esta acción.")
    token = authorization.split(" ", 1)[1].strip()
    return verify_workspace_token(token)


def build_session_payload(workspace_id: int, workspace_slug: str, workspace_name: str) -> Dict[str, Any]:
    return {
        "token": issue_workspace_token(workspace_id, workspace_slug, workspace_name),
        "workspace_id": int(workspace_id),
        "workspace_slug": str(workspace_slug),
        "workspace_name": str(workspace_name),
    }


def optional_workspace_token(token: Optional[str]) -> Optional[AuthActor]:
    if not token:
        return None
    return verify_workspace_token(token)
