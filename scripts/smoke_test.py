"""
Botardium Core - Smoke Test
===========================
Verifica dependencias core y el contrato operativo Vite + Tauri + Python.
Ejecutar: python scripts/smoke_test.py
"""

import importlib
import json
import sys
from pathlib import Path

DEPENDENCIES = {
    "dotenv": "python-dotenv",
    "fastapi": "fastapi",
    "patchright": "patchright",
    "ppadb": "pure-python-adb",
    "ddgs": "ddgs",
    "uvicorn": "uvicorn",
}
ROOT = Path(__file__).resolve().parent.parent
WEB_PACKAGE_JSON = ROOT / "botardium-panel" / "web" / "package.json"
TAURI_CONFIG_JSON = ROOT / "botardium-panel" / "web" / "src-tauri" / "tauri.conf.json"
PANEL_APP_TSX = ROOT / "botardium-panel" / "web" / "src" / "App.tsx"
PANEL_API_TS = ROOT / "botardium-panel" / "web" / "src" / "lib" / "api.ts"

def check_dependency(module_name: str, pip_name: str) -> bool:
    try:
        mod = importlib.import_module(module_name)
        version = getattr(mod, "__version__", "N/A")
        print(f"  OK {pip_name} ({module_name}) - v{version}")
        return True
    except ImportError:
        print(f"  FAIL {pip_name} ({module_name}) - NO INSTALADO")
        return False


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_runtime_contract() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    if not WEB_PACKAGE_JSON.exists():
        return [("package_json", False, f"Falta {WEB_PACKAGE_JSON}")]
    if not TAURI_CONFIG_JSON.exists():
        return [("tauri_config", False, f"Falta {TAURI_CONFIG_JSON}")]

    package_json = _load_json(WEB_PACKAGE_JSON)
    tauri_config = _load_json(TAURI_CONFIG_JSON)
    scripts = package_json.get("scripts", {})
    build_config = tauri_config.get("build", {})

    checks.append((
        "vite_dev_script",
        scripts.get("dev") == "vite",
        f"scripts.dev={scripts.get('dev')!r}",
    ))
    checks.append((
        "desktop_dev_contract",
        scripts.get("dev:desktop") == "npm run backend:build && vite",
        f"scripts['dev:desktop']={scripts.get('dev:desktop')!r}",
    ))
    checks.append((
        "tauri_dev_url",
        build_config.get("devUrl") == "http://localhost:3000",
        f"build.devUrl={build_config.get('devUrl')!r}",
    ))
    checks.append((
        "tauri_before_dev_command",
        build_config.get("beforeDevCommand") == "npm run dev:desktop",
        f"build.beforeDevCommand={build_config.get('beforeDevCommand')!r}",
    ))
    return checks


def check_panel_contract() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    if not PANEL_APP_TSX.exists():
        return [("panel_app", False, f"Falta {PANEL_APP_TSX}")]
    if not PANEL_API_TS.exists():
        return [("panel_api", False, f"Falta {PANEL_API_TS}")]

    app_source = PANEL_APP_TSX.read_text(encoding="utf-8")
    api_source = PANEL_API_TS.read_text(encoding="utf-8")

    checks.append((
        "panel_session_storage",
        "setStoredSession(session);" in app_source and "clearStoredSession();" in app_source,
        "App.tsx persiste y limpia la sesion local",
    ))
    checks.append((
        "panel_job_polling",
        "useSWR<{ jobs: MessageJob[] }>(currentRoute === 'app' && currentUserId ? apiUrl(`/api/messages/jobs?workspace_id=${currentUserId}`) : null, fetcher, { refreshInterval: 2000 })" in app_source,
        "App.tsx sigue haciendo polling del estado de jobs cada 2s",
    ))
    checks.append((
        "api_authorization_header",
        'headers.set("Authorization", `Bearer ${session.token}`);' in api_source,
        "api.ts adjunta el bearer token automaticamente",
    ))
    checks.append((
        "api_session_expiration_signal",
        "botardium-session-expired" in api_source,
        "api.ts notifica expiracion de sesion al panel",
    ))
    return checks

def main():
    print("=" * 50)
    print("[smoke] Botardium Core - Smoke Test")
    print(f"   Python: {sys.version}")
    print("=" * 50)
    print()

    print("[deps] Verificando dependencias:")
    results = []
    for module_name, pip_name in DEPENDENCIES.items():
        results.append(check_dependency(module_name, pip_name))

    print()
    print("[runtime] Verificando contrato runtime:")
    contract_checks = check_runtime_contract()
    contract_results = []
    for name, ok, detail in contract_checks:
        contract_results.append(ok)
        marker = "OK" if ok else "FAIL"
        print(f"  {marker} {name} - {detail}")

    print()
    print("[panel] Verificando contrato auth/polling:")
    panel_checks = check_panel_contract()
    panel_results = []
    for name, ok, detail in panel_checks:
        panel_results.append(ok)
        marker = "OK" if ok else "FAIL"
        print(f"  {marker} {name} - {detail}")

    print()
    ok = sum(results)
    total = len(results)
    ok_contracts = sum(contract_results)
    total_contracts = len(contract_results)
    ok_panel = sum(panel_results)
    total_panel = len(panel_results)
    print(f"[summary] Dependencias: {ok}/{total}")
    print(f"[summary] Contrato runtime: {ok_contracts}/{total_contracts}")
    print(f"[summary] Contrato panel: {ok_panel}/{total_panel}")

    if all(results) and all(contract_results) and all(panel_results):
        print("[ok] Entorno operativo. Listo para trabajar.")
        return 0
    else:
        print("[warn] Hay dependencias faltantes o desalineacion de contrato. Ejecuta:")
        print("   pip install -r requirements.txt")
        return 1

if __name__ == "__main__":
    sys.exit(main())
