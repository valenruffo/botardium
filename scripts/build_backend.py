import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "botardium-panel" / "web" / "src-tauri" / "binaries"
DIRECTIVAS_DIR = ROOT / "directivas"
ENV_EXAMPLE = ROOT / ".env.example"
SKILLS_DIR = ROOT / ".agents" / "skills"
CORE_SKILLS = [
    ROOT / ".agents" / "skills" / "__init__.py",
    ROOT / ".agents" / "skills" / "stealth_engine.py",
    ROOT / ".agents" / "skills" / "stealth_mod.py",
    ROOT / ".agents" / "skills" / "adb_manager.py",
    ROOT / ".agents" / "skills" / "human_interactor.py",
    ROOT / ".agents" / "skills" / "db_manager.py",
]
EXCLUDED_MODULES = [
    "IPython",
    "jupyter_client",
    "jupyter_core",
    "ipykernel",
    "matplotlib",
    "pandas",
    "pyarrow",
    "scipy",
    "torch",
    "tensorflow",
    "sympy",
    "zmq",
    "sqlalchemy",
    "alembic",
    "notebook",
    "pytest",
    "PIL.ImageTk",
    "tkinter",
]

# Mapeo de la arquitectura de Tauri
# Tauri busca 'nombre-binary-[target-triple]' ej. botardium-api-x86_64-pc-windows-msvc.exe
TARGET = "x86_64-pc-windows-msvc"
BINARY_NAME = f"botardium-api-{TARGET}.exe"

DIST_DIR.mkdir(parents=True, exist_ok=True)

def main():
    print(f"Buidling for target: {BINARY_NAME}")
    separator = ";" if os.name == "nt" else ":"
    data_args = [
        (DIRECTIVAS_DIR, "directivas"),
        (ENV_EXAMPLE, "."),
    ]
    data_args.extend((skill_file, f".agents/skills/{skill_file.name}") for skill_file in CORE_SKILLS)

    cmd = [
        "pyinstaller",
        "--name", BINARY_NAME[:-4],
        "--onefile",
        "--noconfirm",
        "--clean",
        "--paths", str(ROOT),
        "--paths", str(SKILLS_DIR),
        "--specpath", str(ROOT),
        "--hidden-import", "scripts.runtime_paths",
        "--hidden-import", "stealth_engine",
        "--hidden-import", "stealth_mod",
        "--hidden-import", "adb_manager",
        "--hidden-import", "human_interactor",
        "--hidden-import", "db_manager",
        "--collect-data", "patchright",
        "--hidden-import", "uvicorn",
        "--hidden-import", "fastapi",
        "--hidden-import", "pydantic",
        "--hidden-import", "sqlite3",
        "--hidden-import", "scripts.core_warmer",
        "--hidden-import", "scripts.lead_scraper",
        "--hidden-import", "scripts.outreach_manager",
        "--hidden-import", "scripts.session_manager",
        "--hidden-import", "scripts.account_check",
        "--distpath", str(DIST_DIR),
        str(ROOT / "scripts" / "main.py")
    ]

    for source_path, dest in data_args:
        cmd.extend(["--add-data", f"{source_path}{separator}{dest}"])

    for module in EXCLUDED_MODULES:
        cmd.extend(["--exclude-module", module])
    
    subprocess.run(cmd, check=True, cwd=ROOT)
    print(f"Build done at {DIST_DIR / BINARY_NAME}")

if __name__ == "__main__":
    main()
