"""
PrimeBot Core — Stealth Engine
================================
Motor de navegación invisible usando Patchright (Playwright parcheado).
Gestiona la creación de browsers indetectables con fingerprint realista.

Dependencias: patchright, python-dotenv
Consulta: directivas/memoria_maestra.md § 4 (Reglas de IP y Fingerprint)
"""

import asyncio
import os
import random
import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Optional, cast
from pathlib import Path

logger = logging.getLogger("primebot.stealth")

WINDOWS_BROWSER_CANDIDATES = [
    ("msedge", None),
    ("chrome", None),
    (None, r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    (None, r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    (None, r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    (None, r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]


@dataclass
class StealthBrowserSession:
    playwright: Any
    browser: Any
    context: Any
    page: Any

# --------------------------------------------------------------------------- #
#  Pool de User-Agents reales (Chromium desktop, actualizado 2025-2026)
# --------------------------------------------------------------------------- #
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]

# --------------------------------------------------------------------------- #
#  Viewport pool — variaciones reales de resolución de escritorio
# --------------------------------------------------------------------------- #
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 720},
]

# Timezones para match con proxies del mismo país
TIMEZONES = {
    "ar": "America/Argentina/Buenos_Aires",
    "us": "America/New_York",
    "es": "Europe/Madrid",
    "br": "America/Sao_Paulo",
    "mx": "America/Mexico_City",
}


def _randomize_viewport(base: dict[str, int]) -> dict[str, int]:
    """Agrega variación ±50px al viewport base para evadir fingerprinting."""
    return {
        "width": base["width"] + random.randint(-50, 50),
        "height": base["height"] + random.randint(-30, 30),
    }


def _pick_user_agent() -> str:
    """Selecciona un User-Agent aleatorio del pool."""
    return random.choice(USER_AGENTS)


def _is_missing_browser_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "executable doesn't exist" in lowered
        or "browser executable" in lowered
        or "not found" in lowered
        or "enoent" in lowered
    )


async def _install_patchright_chromium() -> None:
    logger.warning("Chromium de Patchright ausente. Instalando binario automaticamente...")
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "patchright", "install", "chromium"],
        check=True,
    )


async def _launch_chromium_with_fallback(playwright: Any, launch_kwargs: dict[str, Any]):
    try:
        return await playwright.chromium.launch(**launch_kwargs)
    except Exception as exc:
        message = str(exc)
        if not _is_missing_browser_error(message):
            raise

        logger.warning("Patchright Chromium no esta disponible. Intentando fallback con navegador instalado...")
        fallback_errors: list[str] = []
        for channel, executable_path in WINDOWS_BROWSER_CANDIDATES:
            extra_kwargs = dict(launch_kwargs)
            label = channel or executable_path or "unknown-browser"
            if executable_path:
                if not Path(executable_path).exists():
                    continue
                extra_kwargs["executable_path"] = executable_path
            elif channel:
                extra_kwargs["channel"] = channel
            try:
                logger.info(f"Intentando navegador fallback: {label}")
                return await playwright.chromium.launch(**extra_kwargs)
            except Exception as fallback_exc:
                fallback_errors.append(f"{label}: {fallback_exc}")

        if getattr(sys, "frozen", False):
            raise RuntimeError(
                "Botardium no encontro un navegador Chromium utilizable para iniciar sesion. "
                "Instala Microsoft Edge o Google Chrome en esta PC."
            ) from exc

        try:
            await _install_patchright_chromium()
            return await playwright.chromium.launch(**launch_kwargs)
        except Exception as install_exc:
            details = "; ".join(fallback_errors[:3])
            raise RuntimeError(
                "Patchright no encontro Chromium y el fallback con navegadores instalados tambien fallo. "
                f"Detalles: {details or install_exc}"
            ) from install_exc


async def create_stealth_browser(
    proxy: Optional[str] = None,
    headless: bool = False,
    timezone_id: str = "ar",
    locale: str = "es-AR",
):
    """
    Lanza un browser Chromium parcheado (Patchright) con fingerprint realista.

    Args:
        proxy: URL del proxy (http/socks5). Si None, usa conexión directa.
        headless: Ejecutar sin ventana visible. Default False para debugging.
        timezone_id: Clave del timezone (ar, us, es, br, mx).
        locale: Locale del navegador (es-AR, en-US, etc.).

    Returns:
        StealthBrowserSession listo para operar.
    """
    from patchright.async_api import async_playwright

    logger.info("🚀 Iniciando Stealth Browser (Patchright)...")

    pw = await async_playwright().start()

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    launch_kwargs = {
        "headless": headless,
        "args": launch_args,
    }

    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
        logger.info(f"   Proxy: {proxy[:30]}...")

    try:
        browser = await _launch_chromium_with_fallback(pw, launch_kwargs)
    except Exception as exc:
        await pw.stop()
        raise RuntimeError(f"No se pudo iniciar Patchright Chromium: {exc}") from exc

    viewport = _randomize_viewport(random.choice(VIEWPORTS))
    user_agent = _pick_user_agent()
    tz = TIMEZONES.get(timezone_id, TIMEZONES["ar"])

    context = await browser.new_context(
        viewport=cast(Any, viewport),
        user_agent=user_agent,
        locale=locale,
        timezone_id=tz,
        color_scheme="light",
        # Permisos que un usuario real tendría
        permissions=["geolocation"],
    )

    page = await context.new_page()

    logger.info(f"   Viewport: {viewport['width']}x{viewport['height']}")
    logger.info(f"   UA: {user_agent[:60]}...")
    logger.info(f"   Timezone: {tz}")
    logger.info("✅ Stealth Browser listo.")

    return StealthBrowserSession(
        playwright=pw,
        browser=browser,
        context=context,
        page=page,
    )


async def navigate_like_human(page, url: str, wait_range: tuple = (2, 5)):
    """
    Navega a una URL simulando comportamiento humano:
    - Delay aleatorio antes de navegar
    - Espera a que la red esté idle
    - Scroll suave inicial

    Args:
        page: Página de Patchright.
        url: URL destino.
        wait_range: Rango de espera post-navegación (segundos).
    """
    logger.info(f"🌐 Navegando a {url[:50]}...")

    await page.goto(url, wait_until="domcontentloaded")

    # Espera humana post-carga
    wait_time = random.uniform(*wait_range)
    await asyncio.sleep(wait_time)

    # Scroll inicial suave (como un usuario que revisa la página)
    scroll_amount = random.randint(100, 400)
    await page.mouse.wheel(0, scroll_amount)
    await asyncio.sleep(random.uniform(0.5, 1.5))

    logger.info(f"   ✅ Página cargada. Scroll: {scroll_amount}px. Wait: {wait_time:.1f}s")


async def close_stealth_browser(session: Optional[StealthBrowserSession]):
    """Cierra context, browser y playwright para evitar errores de transporte en Windows."""
    if not session:
        return

    try:
        if getattr(session, "context", None):
            await session.context.close()
    except Exception:
        pass

    try:
        if getattr(session, "browser", None):
            await session.browser.close()
    except Exception:
        pass

    try:
        if getattr(session, "playwright", None):
            await session.playwright.stop()
    except Exception:
        pass

    logger.info("🛑 Stealth Browser cerrado.")
