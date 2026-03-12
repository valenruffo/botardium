"""
Botardium Core — Session Manager
==================================
Login persistente con Patchright. Login manual una sola vez,
luego reutiliza cookies/storage para evitar re-login (trigger #1 de baneo).

Consulta: directivas/memoria_maestra.md § 5 (Login programático repetido)
          directivas/memoria_maestra.md § 8 (Lección Fase 1: Sesiones)

Uso:
    python scripts/session_manager.py --setup       # Primer login manual
    python scripts/session_manager.py --check       # Verificar sesión existente
    python scripts/session_manager.py --reset       # Borrar sesión y re-login
"""

import asyncio
import json
import os
import sys
import argparse
import logging
import shutil
import time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = PROJECT_ROOT / ".agents" / "sessions"
TMP_DIR = PROJECT_ROOT / ".tmp"
PROFILE_PATH = TMP_DIR / "account_profile.json"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("primebot.session")

# Load .env
load_dotenv(PROJECT_ROOT / ".env")

# Add skill directory to path for imports
sys.path.insert(0, str(PROJECT_ROOT / ".agents" / "skills"))


def _get_username() -> str:
    """Obtiene el username de IG desde .env o account_profile."""
    username = os.getenv("IG_USERNAME", "").strip()
    if not username and PROFILE_PATH.exists():
        try:
            profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            username = profile.get("ig_username", "")
        except (json.JSONDecodeError, KeyError):
            pass
    if not username or username == "unknown":
        logger.error("IG_USERNAME no configurado en .env")
        sys.exit(1)
    return username


def _get_session_dir(username: str) -> Path:
    """Retorna el directorio de sesión para una cuenta."""
    session_dir = SESSIONS_DIR / username
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _get_storage_path(username: str) -> Path:
    """Path al archivo de estado de sesión (cookies + storage)."""
    return _get_session_dir(username) / "storage_state.json"


def _load_account_profile() -> dict:
    """Carga el perfil de cuenta para configurar proxy y fingerprint."""
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            pass
    logger.warning("account_profile.json no encontrado. Ejecutar account_check.py primero.")
    return {}


def session_exists(username: str) -> bool:
    """Verifica si existe una sesión guardada para la cuenta."""
    storage_path = _get_storage_path(username)
    return storage_path.exists() and storage_path.stat().st_size > 100


async def setup_session(username: str) -> bool:
    """
    PRIMER USO: Abre browser stealth para login manual.

    1. Lanza Patchright con fingerprint del perfil de cuenta
    2. Navega a login de Instagram
    3. Espera a que el usuario se loguee manualmente
    4. Verifica que el login fue exitoso
    5. Guarda cookies + storage en .agents/sessions/{username}/

    Returns:
        True si la sesión se guardó exitosamente.
    """
    from stealth_engine import create_stealth_browser, close_stealth_browser

    profile = _load_account_profile()
    proxy = profile.get("proxy_url") or None

    logger.info(f"--- Session Setup para @{username} ---")
    logger.info("Abriendo browser stealth para login manual...")

    session = await create_stealth_browser(
        proxy=proxy,
        headless=False,  # Siempre visible para login manual
    )
    browser = session.browser
    context = session.context
    page = session.page

    try:
        # Navegar a Instagram login
        await page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        logger.info("")
        logger.info("=" * 60)
        logger.info("  ACCION REQUERIDA: Logueate manualmente en el browser.")
        logger.info("  Esperando automaticamente a que llegues al Feed...")
        logger.info("=" * 60)
        logger.info("")

        # Loop checking if login was successful instead of blocking input
        logged_in = False
        max_wait_time = 300 # 5 minutes max to login
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            await asyncio.sleep(2)
            current_url = page.url
            if "/accounts/login" not in current_url:
                logged_in = True
                logger.info(f"Detectado cambio de URL: {current_url} (ya no es login)")
                break

        # Check 2: Buscar cookies de sesión de IG
        cookies = await context.cookies("https://www.instagram.com")
        session_cookies = [c for c in cookies if c.get("name") in ("sessionid", "ds_user_id")]
        if session_cookies:
            logged_in = True
            logger.info(f"Cookies de sesion encontradas: {len(session_cookies)}")

        if not logged_in:
            logger.error("No se detecto login exitoso. Intenta de nuevo.")
            await close_stealth_browser(session)
            return False

        # Guardar estado completo (cookies + localStorage + sessionStorage)
        storage_path = _get_storage_path(username)
        await context.storage_state(path=str(storage_path))

        # Guardar metadata de sesión
        session_meta = {
            "username": username,
            "created_at": datetime.now().isoformat(),
            "last_used": datetime.now().isoformat(),
            "login_method": "manual",
            "cookies_count": len(cookies),
            "session_cookies": [c["name"] for c in session_cookies],
        }
        meta_path = _get_session_dir(username) / "session_meta.json"
        meta_path.write_text(json.dumps(session_meta, indent=2), encoding="utf-8")

        logger.info(f"Sesion guardada en: {storage_path}")
        logger.info(f"Cookies totales: {len(cookies)}")
        logger.info("Session setup completado exitosamente.")

        await close_stealth_browser(session)
        return True

    except Exception as e:
        logger.error(f"Error durante setup: {e}")
        await close_stealth_browser(session)
        return False


async def load_session(username: str):
    """
    USOS POSTERIORES: Carga sesión guardada sin pasar por login.

    Returns:
        Tuple[browser, context, page] con sesión activa, o None si falla.
    """
    from stealth_engine import create_stealth_browser

    storage_path = _get_storage_path(username)

    if not session_exists(username):
        logger.error(f"No existe sesion para @{username}. Ejecutar --setup primero.")
        return None

    profile = _load_account_profile()
    proxy = profile.get("proxy_url") or None

    logger.info(f"Cargando sesion existente para @{username}...")

    # Lanzar browser
    from patchright.async_api import async_playwright
    from stealth_engine import (
        _randomize_viewport, _pick_user_agent, VIEWPORTS, TIMEZONES,
    )
    import random

    pw = await async_playwright().start()

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    launch_kwargs = {"headless": False, "args": launch_args}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}

    browser = await pw.chromium.launch(**launch_kwargs)

    # Cargar hardware profile si existe, sino usar defaults
    hw_profile_path = _get_session_dir(username) / "hardware_profile.json"
    if hw_profile_path.exists():
        hw = json.loads(hw_profile_path.read_text(encoding="utf-8"))
        viewport = {"width": hw["viewport_width"], "height": hw["viewport_height"]}
        user_agent = hw["user_agent"]
    else:
        viewport = _randomize_viewport(random.choice(VIEWPORTS))
        user_agent = _pick_user_agent()

    # Crear context CON el storage state guardado
    context = await browser.new_context(
        storage_state=str(storage_path),
        viewport=viewport,
        user_agent=user_agent,
        locale="es-AR",
        timezone_id=TIMEZONES.get("ar", "America/Argentina/Buenos_Aires"),
        color_scheme="light",
    )

    page = await context.new_page()

    # Navegar al feed para verificar sesión
    await page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
    await asyncio.sleep(3)

    # Verificar que no nos redirigió al login
    if "/accounts/login" in page.url:
        logger.error("Sesion expirada. Ejecutar --setup para re-login manual.")
        await browser.close()
        return None

    # Actualizar metadata
    meta_path = _get_session_dir(username) / "session_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["last_used"] = datetime.now().isoformat()
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    logger.info(f"Sesion cargada exitosamente. URL: {page.url}")
    return browser, context, page


async def check_session(username: str) -> bool:
    """Verifica si la sesión existe y es válida sin abrir el browser."""
    storage_path = _get_storage_path(username)
    meta_path = _get_session_dir(username) / "session_meta.json"

    if not storage_path.exists():
        logger.info(f"No existe sesion para @{username}")
        return False

    # Leer metadata
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        logger.info(f"Sesion encontrada para @{username}")
        logger.info(f"  Creada: {meta.get('created_at', 'N/A')}")
        logger.info(f"  Ultimo uso: {meta.get('last_used', 'N/A')}")
        logger.info(f"  Cookies: {meta.get('cookies_count', 'N/A')}")
    else:
        logger.info(f"Sesion encontrada pero sin metadata")

    # Verificar que el storage_state tiene contenido válido
    try:
        state = json.loads(storage_path.read_text(encoding="utf-8"))
        cookies = state.get("cookies", [])
        ig_cookies = [c for c in cookies if "instagram" in c.get("domain", "")]
        logger.info(f"  Cookies de IG: {len(ig_cookies)}")

        has_session = any(c["name"] == "sessionid" for c in ig_cookies)
        if has_session:
            logger.info("  Estado: VALIDA (sessionid presente)")
        else:
            logger.warning("  Estado: POSIBLEMENTE EXPIRADA (sin sessionid)")
        return has_session

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"  Error leyendo storage_state: {e}")
        return False


def reset_session(username: str):
    """Elimina la sesión guardada para forzar re-login."""
    session_dir = _get_session_dir(username)
    if session_dir.exists():
        shutil.rmtree(session_dir)
        logger.info(f"Sesion de @{username} eliminada.")
    else:
        logger.info(f"No habia sesion de @{username} para eliminar.")


# --------------------------------------------------------------------------- #
#  API pública para otros scripts
# --------------------------------------------------------------------------- #

async def load_or_create_session(username: str = None):
    """
    API principal para el resto del sistema.
    Carga sesión si existe, o lanza setup si no.

    Returns:
        Tuple[browser, context, page] con sesión activa.
    """
    if username is None:
        username = _get_username()

    if session_exists(username):
        result = await load_session(username)
        if result:
            return result
        # Si falló (sesión expirada), hacer setup
        logger.info("Sesion expirada, iniciando re-setup...")

    success = await setup_session(username)
    if not success:
        raise RuntimeError(f"No se pudo crear sesion para @{username}")

    return await load_session(username)


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

async def main():
    parser = argparse.ArgumentParser(description="Botardium Session Manager")
    parser.add_argument("--setup", action="store_true", help="Login manual y guardar sesion")
    parser.add_argument("--check", action="store_true", help="Verificar sesion existente")
    parser.add_argument("--reset", action="store_true", help="Eliminar sesion y re-login")
    args = parser.parse_args()

    username = _get_username()

    if args.reset:
        reset_session(username)
        await setup_session(username)
    elif args.setup:
        if session_exists(username):
            logger.info(f"Ya existe sesion para @{username}. Usar --reset para re-crear.")
            await check_session(username)
        else:
            await setup_session(username)
    elif args.check:
        await check_session(username)
    else:
        # Default: check o setup
        if session_exists(username):
            await check_session(username)
        else:
            logger.info("No hay sesion. Iniciando setup...")
            await setup_session(username)


if __name__ == "__main__":
    asyncio.run(main())
