import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / ".tmp" / "logs"


def check_url(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return {"ok": True, "status": response.status}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def log_size(name: str) -> int:
    path = LOG_DIR / name
    if not path.exists():
        return 0
    return path.stat().st_size


def main() -> None:
    payload = {
        "backend": check_url("http://127.0.0.1:8000/api/leads"),
        "frontend": check_url("http://127.0.0.1:3000"),
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
