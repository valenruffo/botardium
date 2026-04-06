import json
import urllib.request
from pathlib import Path

from scripts.runtime_paths import LOG_DIR, SOURCE_ROOT

ROOT = SOURCE_ROOT
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/health"
FRONTEND_URL = "http://127.0.0.1:3000"


def check_url(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return {"ok": True, "status": response.status}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def check_json_url(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return {
                "ok": True,
                "status": response.status,
                "payload": payload,
                "ready": bool(payload.get("ready")),
            }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "ready": False}


def log_size(name: str) -> int:
    path = LOG_DIR / name
    if not path.exists():
        return 0
    return path.stat().st_size


def main() -> None:
    backend = check_json_url(BACKEND_HEALTH_URL)
    frontend = check_url(FRONTEND_URL)
    payload = {
        "backend": backend,
        "frontend": frontend,
        "stack_ready": bool(backend.get("ok") and backend.get("ready") and frontend.get("ok")),
        "logs": {
            "api": log_size("api.log"),
            "web": log_size("web.log"),
            "build": log_size("web-build.log"),
            "launcher": log_size("launcher.log"),
        },
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
