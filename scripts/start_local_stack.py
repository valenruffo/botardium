import os
import subprocess
import sys
import time
from pathlib import Path

from scripts.runtime_paths import LOG_DIR, SOURCE_ROOT, TMP_DIR

ROOT = SOURCE_ROOT
WEB_DIR = ROOT / "botardium-panel" / "web"


def _flags() -> int:
    if os.name != "nt":
        return 0
    return subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP


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
    subprocess.run(["cmd", "/c", str(ROOT / "scripts" / "stop_local_stack.cmd")], check=False)

    build_log = open(LOG_DIR / "web-build.log", "w", encoding="utf-8")
    build = subprocess.run(["npm.cmd", "run", "build"], cwd=str(WEB_DIR), stdout=build_log, stderr=build_log)
    build_log.close()
    if build.returncode != 0:
        print(f"ERROR: Fallo el build del frontend. Revisa {LOG_DIR / 'web-build.log'}")
        return build.returncode

    _spawn([sys.executable, "-m", "uvicorn", "scripts.main:app", "--host", "127.0.0.1", "--port", "8000"], ROOT, "api.log")
    _spawn(["cmd.exe", "/c", "npm run start"], WEB_DIR, "web.log")

    time.sleep(10)
    print("Stack estable iniciado.")
    print("Frontend: http://127.0.0.1:3000")
    print("Backend:  http://127.0.0.1:8000")
    print(f"Logs:     {LOG_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
