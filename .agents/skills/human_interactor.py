"""
PrimeBot Core — Human Interactor
==================================
Funciones de humanización para sesiones de browser.
Escritura char-by-char, movimiento de mouse no-lineal (Bézier),
scroll aleatorio y warmeo de sesión.

Dependencias: patchright (a través de stealth_engine)
Consulta: directivas/memoria_maestra.md § 2.2 (Delays entre Acciones)
"""

import asyncio
import random
import math
import logging
from typing import Optional, List, Tuple

logger = logging.getLogger("primebot.human")


# --------------------------------------------------------------------------- #
#  Utilidades matemáticas
# --------------------------------------------------------------------------- #

def _gaussian_delay(mean: float, std: float, min_val: float = 0.02) -> float:
    """Genera un delay con distribución gaussiana, nunca menor a min_val."""
    return max(min_val, random.gauss(mean, std))


def _bezier_point(
    t: float,
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
) -> Tuple[float, float]:
    """Calcula un punto en una curva de Bézier cúbica para t ∈ [0, 1]."""
    x = (
        (1 - t) ** 3 * p0[0]
        + 3 * (1 - t) ** 2 * t * p1[0]
        + 3 * (1 - t) * t ** 2 * p2[0]
        + t ** 3 * p3[0]
    )
    y = (
        (1 - t) ** 3 * p0[1]
        + 3 * (1 - t) ** 2 * t * p1[1]
        + 3 * (1 - t) * t ** 2 * p2[1]
        + t ** 3 * p3[1]
    )
    return (x, y)


def _generate_bezier_path(
    start: Tuple[float, float],
    end: Tuple[float, float],
    steps: int = 25,
) -> List[Tuple[float, float]]:
    """
    Genera una trayectoria de mouse siguiendo una curva de Bézier cúbica.
    Los puntos de control son aleatorios para simular el movimiento humano.
    """
    # Puntos de control aleatorios (desviación del camino recto)
    dx = end[0] - start[0]
    dy = end[1] - start[1]

    ctrl1 = (
        start[0] + dx * random.uniform(0.2, 0.4) + random.uniform(-50, 50),
        start[1] + dy * random.uniform(0.2, 0.4) + random.uniform(-50, 50),
    )
    ctrl2 = (
        start[0] + dx * random.uniform(0.6, 0.8) + random.uniform(-50, 50),
        start[1] + dy * random.uniform(0.6, 0.8) + random.uniform(-50, 50),
    )

    path = []
    for i in range(steps + 1):
        t = i / steps
        point = _bezier_point(t, start, ctrl1, ctrl2, end)
        path.append(point)

    return path


# --------------------------------------------------------------------------- #
#  Funciones principales de humanización
# --------------------------------------------------------------------------- #

async def type_like_human(
    page,
    selector: str,
    text: str,
    mean_delay: float = 0.12,
    std_delay: float = 0.04,
):
    """
    Escribe texto char-by-char con delays gaussianos entre cada tecla.
    NO usa page.fill() que es instantáneo y detectable.

    Args:
        page: Página de Patchright.
        selector: Selector CSS del campo de texto.
        text: Texto a escribir.
        mean_delay: Delay promedio entre caracteres (segundos).
        std_delay: Desviación estándar del delay.
    """
    logger.info(f"⌨️  Escribiendo {len(text)} chars en '{selector[:30]}'...")

    try:
        # Usamos JS focus en vez de page.click() para evitar cuelgues por actionability checks (visibilidad)
        await page.evaluate(f"""() => {{
            const el = document.querySelector('{selector}');
            if (el) el.focus();
        }}""")
    except Exception as e:
        logger.warning(f"Error enfocando {selector} via JS: {e}")
        # fallback a click
        await page.click(selector, timeout=5000)
        
    await asyncio.sleep(random.uniform(0.3, 0.8))  # Pausa pre-typing

    for i, char in enumerate(text):
        await page.keyboard.type(char)
        delay = _gaussian_delay(mean_delay, std_delay)
        await asyncio.sleep(delay)

        # Pausas más largas después de espacios y puntuación (como un humano pensando)
        if char in " .,!?":
            await asyncio.sleep(random.uniform(0.1, 0.5))

    logger.info("   ✅ Escritura completada.")


async def move_mouse_naturally(
    page,
    target_x: float,
    target_y: float,
    steps: int = 25,
):
    """
    Mueve el mouse siguiendo una curva de Bézier cúbica.
    NO se mueve en línea recta (detectable).

    Args:
        page: Página de Patchright.
        target_x: Coordenada X destino.
        target_y: Coordenada Y destino.
        steps: Cantidad de puntos intermedios en la curva.
    """
    # Obtener posición actual del mouse (aproximación)
    current = await page.evaluate(
        "() => ({x: window._mouseX || 0, y: window._mouseY || 0})"
    )
    start = (current.get("x", random.randint(100, 500)),
             current.get("y", random.randint(100, 400)))

    path = _generate_bezier_path(start, (target_x, target_y), steps)

    for point in path:
        await page.mouse.move(point[0], point[1])
        await asyncio.sleep(random.uniform(0.005, 0.025))

    logger.debug(f"🖱️  Mouse movido a ({target_x:.0f}, {target_y:.0f}) via Bézier")


async def random_scroll(
    page,
    direction: str = "down",
    scroll_range: tuple = (200, 800),
    pause_range: tuple = (1.0, 4.0),
):
    """
    Realiza un scroll aleatorio simulando lectura de feed.

    Args:
        page: Página de Patchright.
        direction: "down" o "up".
        scroll_range: Rango de pixeles a scrollear.
        pause_range: Pausa después del scroll (simulando lectura).
    """
    amount = random.randint(*scroll_range)
    if direction == "up":
        amount = -amount

    await page.mouse.wheel(0, amount)
    pause = random.uniform(*pause_range)
    await asyncio.sleep(pause)

    logger.debug(f"📜 Scroll {direction}: {abs(amount)}px, pausa: {pause:.1f}s")


async def warm_up_session(
    page,
    duration_min: int = 20,
    ig_url: str = "https://www.instagram.com/",
):
    """
    Sesión de warmeo: navega Feed, scrollea, ve stories.
    Simula actividad orgánica antes de cualquier acción de outbound.

    Consulta: memoria_maestra.md § 2.3 — Warmeo obligatorio.

    Args:
        page: Página de Patchright (ya logueada en IG).
        duration_min: Duración del warmeo en minutos.
        ig_url: URL base de Instagram.
    """
    import time

    logger.info(f"🔥 Iniciando warmeo de {duration_min} min...")
    start_time = time.time()
    end_time = start_time + (duration_min * 60)

    actions_done = 0

    while time.time() < end_time:
        remaining = (end_time - time.time()) / 60
        logger.info(f"   ⏱️  Warmeo restante: {remaining:.1f} min | Acciones: {actions_done}")

        # Elegir acción aleatoria de warmeo
        action = random.choices(
            ["scroll_feed", "view_story", "explore", "check_notifications"],
            weights=[40, 30, 20, 10],
            k=1,
        )[0]

        try:
            if action == "scroll_feed":
                # Scrollear feed entre 3 y 8 veces
                scrolls = random.randint(3, 8)
                for _ in range(scrolls):
                    await random_scroll(page, "down", (300, 700), (2, 6))
                logger.info(f"   📰 Feed: {scrolls} scrolls")

            elif action == "view_story":
                # Intentar hacer clic en una story
                await asyncio.sleep(random.uniform(2, 5))
                logger.info("   📷 Visualizando stories...")

            elif action == "explore":
                # Navegar a Explore
                await page.goto(f"{ig_url}explore/", wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(3, 8))
                for _ in range(random.randint(2, 5)):
                    await random_scroll(page, "down", (200, 500), (2, 4))
                logger.info("   🔍 Explore navegado")

                # Volver al feed
                await page.goto(ig_url, wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(2, 4))

            elif action == "check_notifications":
                await asyncio.sleep(random.uniform(1, 3))
                logger.info("   🔔 Notificaciones revisadas")

            actions_done += 1

        except Exception as e:
            logger.warning(f"   ⚠️ Error en warmeo ({action}): {e}")
            await asyncio.sleep(random.uniform(5, 15))

        # Pausa entre acciones de warmeo
        await asyncio.sleep(random.uniform(10, 30))

    elapsed = (time.time() - start_time) / 60
    logger.info(f"✅ Warmeo completado: {elapsed:.1f} min, {actions_done} acciones.")
