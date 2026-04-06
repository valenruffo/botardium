import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from scripts.runtime_paths import LOG_DIR, SOURCE_ROOT, TMP_DIR

ROOT = SOURCE_ROOT
WEB_DIR = ROOT / "botardium-panel" / "web"
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/health"
FRONTEND_URL = "http://127.0.0.1:3000"


def _flags() -> int:
    if os.name != "nt":
        return 0
    return subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP


def _npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _launcher_log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "launcher.log", "a", encoding="utf-8") as handle:
        handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")


def _check_backend_ready() -> bool:
    try:
        with urllib.request.urlopen(BACKEND_HEALTH_URL, timeout=2) as response:
            payload = response.read().decode("utf-8")
        return '"ready": true' in payload.lower()
    except Exception:
        return False


def _check_url(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def _wait_for(check, label: str, timeout_seconds: int = 30) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if check():
            _launcher_log(f"{label} ready")
            return True
        time.sleep(0.5)
    _launcher_log(f"timeout waiting for {label}")
    return False


def _spawn(command: list[str], cwd: Path, log_name: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = open(LOG_DIR / log_name, "w", encoding="utf-8")
    subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=log_file,
        stderr=log_file,
        stdin=subprocess.DEVNULL,
        creationflags=_flags(),
        close_fds=True,
    )


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _launcher_log("stopping previous local stack")
    if os.name == "nt":
        subprocess.run(["cmd", "/c", str(ROOT / "scripts" / "stop_local_stack.cmd")], check=False)

    _spawn([sys.executable, "-m", "uvicorn", "scripts.main:app", "--host", "127.0.0.1", "--port", "8000"], ROOT, "api.log")
    _launcher_log("backend process spawned")
    _spawn([_npm_command(), "run", "dev", "--", "--host", "127.0.0.1", "--port", "3000"], WEB_DIR, "web.log")
    _launcher_log("vite dev server spawned")

    backend_ready = _wait_for(_check_backend_ready, "backend /health readiness")
    frontend_ready = _wait_for(lambda: _check_url(FRONTEND_URL), "frontend vite server")
    if not backend_ready or not frontend_ready:
        print(f"ERROR: La stack no quedó lista. Revisá {LOG_DIR}")
        return 1

    print("Stack estable iniciado.")
    print("Frontend: http://127.0.0.1:3000")
    print("Backend:  http://127.0.0.1:8000")
    print(f"Logs:     {LOG_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
