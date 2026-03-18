"""
Botardium Core — Core Warmer
================================
Primer flujo operativo real. Simula actividad orgánica de un usuario
que abre Instagram para revisar su feed y ver stories.

Consulta: directivas/memoria_maestra.md § 2.3 (Warmeo obligatorio)
          directivas/account_dna_SOP.md (Duración según tipo de cuenta)

Uso:
    python scripts/core_warmer.py                # Warmeo normal (lee perfil)
    python scripts/core_warmer.py --dry-run      # Test corto de 2 min
    python scripts/core_warmer.py --duration 15  # Override duración (minutos)
"""

import asyncio
import json
import os
import sys
import argparse
import random
import time
import logging
from pathlib import Path
from datetime import datetime
from scripts.runtime_config import load_bootstrap_env
from scripts.runtime_paths import AGENTS_DIR, MEMORIA_PATH, PROFILE_PATH, SOURCE_ROOT, TMP_DIR

# Paths
PROJECT_ROOT = SOURCE_ROOT

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("primebot.warmer")

load_bootstrap_env()

# Ensure project imports (scripts.*) resolve when executed as script
sys.path.insert(0, str(PROJECT_ROOT))

# Add .agents to path
sys.path.insert(0, str(AGENTS_DIR))

IG_BASE = "https://www.instagram.com/"


def _load_profile() -> dict:
    """Carga el perfil de cuenta."""
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    logger.warning("account_profile.json no encontrado. Usando defaults.")
    return {"warmup_duration_min": 15}


# --------------------------------------------------------------------------- #
#  Acciones de Warmeo
"""
Botardium Core — Core Warmer
================================
Primer flujo operativo real. Simula actividad orgánica de un usuario
que abre Instagram para revisar su feed y ver stories.

Consulta: directivas/memoria_maestra.md § 2.3 (Warmeo obligatorio)
          directivas/account_dna_SOP.md (Duración según tipo de cuenta)

Uso:
    python scripts/core_warmer.py                # Warmeo normal (lee perfil)
    python scripts/core_warmer.py --dry-run      # Test corto de 2 min
    python scripts/core_warmer.py --duration 15  # Override duración (minutos)
"""

IG_BASE = "https://www.instagram.com/"


def _load_profile() -> dict:
    """Carga el perfil de cuenta."""
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    logger.warning("account_profile.json no encontrado. Usando defaults.")
    return {"warmup_duration_min": 15}


# --------------------------------------------------------------------------- #
#  Acciones de Warmeo
# --------------------------------------------------------------------------- #

async def _scroll_feed(page, cycles: int = 5, max_likes: int = 0):
    """Scroll orgánico del feed principal."""
    from skills.human_interactor import random_scroll

    likes_given = 0
    logger.info(f"  Feed: scrolling {cycles} veces, target likes: {max_likes}...")
    for i in range(cycles):
        # Scroll down con pausa de lectura
        scroll_amount = random.randint(300, 800)
        await page.mouse.wheel(0, scroll_amount)
        read_time = random.uniform(3, 12)  # Simular lectura de un post realista
        await asyncio.sleep(read_time)
        
        # Ocasionalmente dar un like por doble tap a un post visible
        if likes_given < max_likes and random.random() < 0.4:
            try:
                # Buscamos imagenes q suelen ser posts en el feed, limitando a viewport
                await page.evaluate("""() => {
                    const imgs = Array.from(document.querySelectorAll('article img'));
                    const visibleImg = imgs.find(img => {
                        const rec = img.getBoundingClientRect();
                        return rec.top >= 0 && rec.top <= window.innerHeight / 2 && rec.height > 100;
                    });
                    if (visibleImg) {
                        // Despachar doble click sintetico para dar like en IG web
                        const ev = new MouseEvent('dblclick', {
                            bubbles: true, cancelable: true, view: window
                        });
                        visibleImg.dispatchEvent(ev);
                    }
                }""")
                likes_given += 1
                logger.info("    -> Like dado (Doble-click en post)")
                await asyncio.sleep(random.uniform(1, 3))
            except Exception as e:
                pass

        # Ocasionalmente hacer scroll up (re-leer algo)
        if random.random() < 0.15:
            await page.mouse.wheel(0, -random.randint(100, 300))
            await asyncio.sleep(random.uniform(1, 3))

    logger.info(f"  Feed: {cycles} scrolls completados, {likes_given} likes dados")
    return cycles, likes_given


async def _view_stories(page, count: int = 3, max_likes: int = 0):
    """
    Intenta ver stories haciendo clic en el carousel de stories.
    Si no encuentra stories, simplemente espera.
    """
    logger.info(f"  Stories: intentando ver {count} stories, target likes: {max_likes}...")
    stories_viewed = 0
    likes_given = 0

    try:
        # Primero, asegurar que estamos en el feed
        if "/explore" in page.url or page.url != IG_BASE:
            await page.goto(IG_BASE, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(2, 4))

        # Intentar encontrar el carousel de stories
        # Los stories están en un container en la parte superior del feed
        story_selectors = [
            'div[role="button"] canvas',           # Story ring canvas
            'button[aria-label*="Story"]',          # Story button
            'div[role="menuitem"]',                 # Story item
            'header section canvas',               # Canvas en el header
        ]

        for selector in story_selectors:
            try:
                stories = await page.query_selector_all(selector)
                if stories and len(stories) > 1:
                    # Seleccionar stories aleatorias (no el primero que es el nuestro)
                    indices = list(range(1, min(len(stories), 8)))
                    random.shuffle(indices)
                    targets = indices[:count]

                    for idx in targets:
                        try:
                            await stories[idx].click()
                            await asyncio.sleep(random.uniform(3, 8))  # Ver la story realista
                            stories_viewed += 1

                            # Dar un like a la story si no hemos llegado al máximo
                            if likes_given < max_likes and random.random() < 0.6:
                                try:
                                    like_button = await page.query_selector('svg[aria-label="Like"], svg[aria-label="Me gusta"]')
                                    if like_button:
                                        parent_btn = await like_button.evaluate_handle('el => el.closest("button"), el => el.closest("div[role=\'button\']")')
                                        if parent_btn:
                                            await parent_btn.click()
                                            likes_given += 1
                                            logger.info("    -> Like dado a Story")
                                            await asyncio.sleep(random.uniform(1, 2))
                                except Exception:
                                    pass

                            # Avanzar a la siguiente story con probabilidad
                            if random.random() < 0.5:
                                await page.keyboard.press("ArrowRight")
                                await asyncio.sleep(random.uniform(2, 6))
                                stories_viewed += 1

                            # Cerrar stories
                            await page.keyboard.press("Escape")
                            await asyncio.sleep(random.uniform(1, 3))

                        except Exception:
                            continue

                    if stories_viewed > 0:
                        break
            except Exception:
                continue

        if stories_viewed == 0:
            # Fallback: si no encontramos stories, simular espera
            logger.info("  Stories: no se encontraron stories accesibles, esperando...")
            await asyncio.sleep(random.uniform(5, 15))

    except Exception as e:
        logger.warning(f"  Stories: error ({e}), continuando...")
        await asyncio.sleep(random.uniform(3, 8))

    logger.info(f"  Stories: {stories_viewed} visualizadas, {likes_given} likes dados")
    return stories_viewed, likes_given


async def _explore_briefly(page):
    """Visita la pestaña Explore brevemente."""
    logger.info("  Explore: navegando...")
    try:
        await page.goto(f"{IG_BASE}explore/", wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(3, 6))

        # Scrollear un poco
        for _ in range(random.randint(2, 4)):
            await page.mouse.wheel(0, random.randint(200, 500))
            await asyncio.sleep(random.uniform(2, 5))

        # Volver al feed
        await page.goto(IG_BASE, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(2, 4))

        logger.info("  Explore: visitado OK")
        return True
    except Exception as e:
        logger.warning(f"  Explore: error ({e})")
        return False


async def _check_for_popups(page) -> list:
    """
    Detecta popups de Instagram (cookies, notifications, etc.)
    y los documenta para capitalización.
    """
    popups_detected = []

    popup_checks = [
        {"selector": 'button:has-text("Not Now")', "name": "notifications_prompt"},
        {"selector": 'button:has-text("Decline")', "name": "cookies_decline"},
        {"selector": 'button:has-text("Accept")', "name": "cookies_accept"},
        {"selector": 'div[role="dialog"]', "name": "generic_dialog"},
        {"selector": 'text="Try Again Later"', "name": "RATE_LIMIT_WARNING"},
        {"selector": 'text="unusual activity"', "name": "SUSPICIOUS_ACTIVITY"},
    ]

    for check in popup_checks:
        try:
            element = await page.query_selector(check["selector"])
            if element and await element.is_visible():
                popups_detected.append({
                    "type": check["name"],
                    "timestamp": datetime.now().isoformat(),
                })
                logger.warning(f"  POPUP DETECTADO: {check['name']}")

                # Cerrar popups no peligrosos
                if check["name"] in ("notifications_prompt", "cookies_decline"):
                    await element.click()
                    await asyncio.sleep(random.uniform(1, 2))
                    logger.info(f"    Popup cerrado: {check['name']}")
        except Exception:
            continue

    return popups_detected


async def _check_dangerous_popup(page) -> str | None:
    """
    Verifica si hay un popup peligroso que requiere abortar inmediatamente.
    Retorna el tipo de popup peligroso o None si no hay.
    """
    dangerous_checks = [
        ('text="Try Again Later"', "RATE_LIMIT"),
        ('text="unusual activity"', "SUSPICIOUS_ACTIVITY"),
        ('text="Action Blocked"', "ACTION_BLOCKED"),
    ]
    
    for selector, popup_type in dangerous_checks:
        try:
            element = await page.query_selector(selector)
            if element and await element.is_visible():
                return popup_type
        except Exception:
            continue
    
    return None


async def _check_session_expiry(page) -> bool:
    """
    Verifica si la sesión expiró (redireccion a login).
    Retorna True si la sesión expiró, False si está activa.
    """
    try:
        if "/accounts/login" in page.url or "/challenge" in page.url:
            return True
        
        login_indicators = [
            'text="Log in"',
            'text="Iniciar sesión"',
            'input[name="username"]',
        ]
        
        for indicator in login_indicators:
            try:
                element = await page.query_selector(indicator)
                if element and await element.is_visible():
                    return True
            except Exception:
                continue
    except Exception:
        pass
    
    return False


async def _micro_feed_scroll(page, duration_sec: float = 8.0):
    """
    Actividad de micro-warmup: scroll breve por el feed.
    """
    try:
        start_time = time.time()
        scrolls_done = 0
        
        while time.time() - start_time < duration_sec:
            scroll_amount = random.randint(200, 500)
            await page.mouse.wheel(0, scroll_amount)
            scrolls_done += 1
            
            read_time = random.uniform(2, 5)
            await asyncio.sleep(read_time)
            
            if random.random() < 0.3:
                await page.mouse.wheel(0, -random.randint(100, 200))
                await asyncio.sleep(random.uniform(1, 2))
        
        logger.debug(f"    Micro feed scroll: {scrolls_done} scrolls")
        return True
    except Exception as e:
        logger.warning(f"    Micro feed scroll error: {e}")
        return False


async def _micro_stories_view(page, duration_sec: float = 6.0):
    """
    Actividad de micro-warmup: ver stories brevemente.
    """
    try:
        start_time = time.time()
        stories_viewed = 0
        
        if "/explore" in page.url or page.url != IG_BASE:
            await page.goto(IG_BASE, wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(1, 2))
        
        story_selectors = [
            'div[role="button"] canvas',
            'button[aria-label*="Story"]',
            'header section canvas',
        ]
        
        while time.time() - start_time < duration_sec:
            for selector in story_selectors:
                try:
                    stories = await page.query_selector_all(selector)
                    if stories and len(stories) > 1:
                        idx = random.randint(1, min(len(stories) - 1, 4))
                        await stories[idx].click()
                        await asyncio.sleep(random.uniform(2, 4))
                        stories_viewed += 1
                        
                        await page.keyboard.press("Escape")
                        await asyncio.sleep(random.uniform(1, 2))
                        break
                except Exception:
                    continue
            
            if stories_viewed == 0:
                await asyncio.sleep(random.uniform(2, 4))
                break
        
        logger.debug(f"    Micro stories: {stories_viewed} vistas")
        return True
    except Exception as e:
        logger.warning(f"    Micro stories error: {e}")
        return False


async def _micro_explore_brief(page, duration_sec: float = 4.0):
    """
    Actividad de micro-warmup: visita breve a Explore.
    """
    try:
        await page.goto(f"{IG_BASE}explore/", wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(2, 3))
        
        for _ in range(random.randint(1, 2)):
            await page.mouse.wheel(0, random.randint(150, 300))
            await asyncio.sleep(random.uniform(1, 2))
        
        await page.goto(IG_BASE, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(1, 2))
        
        logger.debug("    Micro explore: completado")
        return True
    except Exception as e:
        logger.warning(f"    Micro explore error: {e}")
        return False


async def _micro_idle_behavior(page, duration_sec: float = 3.0):
    """
    Actividad de micro-warmup: comportamiento idle (mouse movement, pausas).
    """
    try:
        from skills.stealth_mod import add_behavior_noise
        await add_behavior_noise(page, duration_seconds=int(duration_sec))
        logger.debug("    Micro idle: completado")
        return True
    except Exception as e:
        logger.warning(f"    Micro idle error: {e}")
        return False


async def run_micro_warmup(page, account_profile: dict, duration_min: float = 3.0, dry_run: bool = False) -> dict:
    """
    Ejecuta un micro-warmup después de enviar DMs exitosamente.
    
    Args:
        page: Página de Patchright activa
        account_profile: Perfil de cuenta con configuración
        duration_min: Duración objetivo en minutos (default 3.0)
        dry_run: Si True, solo loguea sin ejecutar
    
    Returns:
        dict con: success, duration_actual_sec, activities_completed, popups_detected, error
    """
    result = {
        "success": False,
        "duration_actual_sec": 0.0,
        "activities_completed": [],
        "popups_detected": [],
        "error": None,
    }
    
    start_time = time.time()
    
    if dry_run:
        logger.info("   🌡️ Micro-warmup [DRY RUN] - skip ejecución real")
        result["success"] = True
        result["duration_actual_sec"] = 0.0
        return result
    
    logger.info("🔥 Ejecutando micro-warmup...")
    
    try:
        dangerous = await _check_dangerous_popup(page)
        if dangerous:
            logger.warning(f"   🚨 Popup peligroso detectado: {dangerous} - abortando micro-warmup")
            result["popups_detected"].append(dangerous)
            result["error"] = f"Dangerous popup: {dangerous}"
            return result
        
        expired = await _check_session_expiry(page)
        if expired:
            logger.error("   ❌ Sesión expirada detectada - abortando micro-warmup")
            result["error"] = "Session expired"
            return result
        
        activities = [
            ("feed_scroll", _micro_feed_scroll, duration_min * 60 * 0.40, 0.40),
            ("stories_view", _micro_stories_view, duration_min * 60 * 0.30, 0.30),
            ("explore_brief", _micro_explore_brief, duration_min * 60 * 0.15, 0.15),
            ("idle_behavior", _micro_idle_behavior, duration_min * 60 * 0.15, 0.15),
        ]
        
        random.shuffle(activities)
        
        for activity_name, activity_func, max_duration, probability in activities:
            if random.random() > probability and activity_name != "feed_scroll":
                logger.debug(f"   ⏭️ Skipping {activity_name} por probabilidad")
                continue
            
            dangerous = await _check_dangerous_popup(page)
            if dangerous:
                logger.warning(f"   🚨 Popup peligroso durante {activity_name}: {dangerous}")
                result["popups_detected"].append(dangerous)
                break
            
            expired = await _check_session_expiry(page)
            if expired:
                result["error"] = "Session expired"
                break
            
            remaining = (duration_min * 60) - (time.time() - start_time)
            if remaining <= 0:
                break
            
            activity_duration = min(max_duration, remaining * 0.8)
            
            try:
                success = await activity_func(page, activity_duration)
                if success:
                    result["activities_completed"].append(activity_name)
                    logger.debug(f"   ✅ {activity_name} completado")
            except Exception as e:
                logger.warning(f"   ⚠️ {activity_name} fallo: {e}")
        
        result["success"] = len(result["activities_completed"]) > 0
        
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"   ❌ Micro-warmup error: {e}")
    
    finally:
        elapsed = time.time() - start_time
        result["duration_actual_sec"] = round(elapsed, 2)
        
        if result["success"]:
            logger.info(f"   ✅ Micro-warmup completado ({elapsed:.1f}s, {len(result['activities_completed'])} actividades)")
        else:
            logger.warning(f"   ⚠️ Micro-warmup finalizado con errores: {result['error']}")
    
    return result


# --------------------------------------------------------------------------- #
#  Capitalización (Compound)
# --------------------------------------------------------------------------- #

def _capitalize_to_memoria(warmeo_log: dict):
    """
    Registra el resultado del warmeo en la Memoria Maestra.
    Agrega una entrada al Registro de Incidentes si hubo popups peligrosos.
    """
    if not MEMORIA_PATH.exists():
        logger.warning("Memoria Maestra no encontrada, skip capitalización.")
        return

    entry_lines = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Siempre registrar el warmeo en el historial
    duration = warmeo_log.get("duration_min", 0)
    scrolls = warmeo_log.get("total_scrolls", 0)
    stories = warmeo_log.get("stories_viewed", 0)
    popups = warmeo_log.get("popups", [])

    # Si hubo popups peligrosos, registrar como incidente
    dangerous_popups = [p for p in popups if p["type"] in ("RATE_LIMIT_WARNING", "SUSPICIOUS_ACTIVITY")]

    if dangerous_popups:
        content = MEMORIA_PATH.read_text(encoding="utf-8")
        incident_entry = (
            f"\n- **{timestamp}:** ALERTA durante warmeo. "
            f"Popups peligrosos detectados: {[p['type'] for p in dangerous_popups]}. "
            f"Accion: Pausa de seguridad recomendada."
        )
        # Insertar antes de la última línea del registro de incidentes
        content = content.rstrip() + "\n" + incident_entry + "\n"
        MEMORIA_PATH.write_text(content, encoding="utf-8")
        logger.warning(f"INCIDENTE registrado en Memoria Maestra")

    # Log a .tmp para trazabilidad
    log_path = TMP_DIR / "warmeo_log.json"
    logs = []
    if log_path.exists():
        try:
            logs = json.loads(log_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logs = []
    logs.append(warmeo_log)
    # Mantener solo los últimos 50 logs
    logs = logs[-50:]
    log_path.write_text(json.dumps(logs, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(f"Capitalizado: {duration:.1f}min, {scrolls} scrolls, {stories} stories")


# --------------------------------------------------------------------------- #
#  Flujo principal
# --------------------------------------------------------------------------- #

async def run_warmeo(duration_min: int = None, dry_run: bool = False, username: str | None = None):
    """
    Ejecuta el flujo completo de warmeo.

    Args:
        duration_min: Override de duración. Si None, lee del perfil.
        dry_run: Si True, ejecuta solo 2 minutos para testing.
    """
    from scripts.session_manager import load_or_create_session
    from skills.stealth_mod import load_or_create_hardware_profile, apply_fingerprint, add_behavior_noise

    # Cargar configuración
    profile = _load_profile()
    target_username = username or os.getenv("IG_USERNAME", profile.get("ig_username", "unknown"))

    if dry_run:
        duration_min = 2
        logger.info("=== DRY RUN MODE (2 min) ===")
    elif duration_min is None:
        duration_min = profile.get("warmup_duration_min", 15)

    logger.info(f"Core Warmer para @{target_username}")
    logger.info(f"Duracion: {duration_min} min")
    logger.info("-" * 40)

    # Cargar sesión
    browser, context, page = await load_or_create_session(target_username)

    # Aplicar fingerprint consistente
    hw_profile = load_or_create_hardware_profile(target_username)
    await apply_fingerprint(context, hw_profile)

    # Tracking
    start_time = time.time()
    end_time = start_time + (duration_min * 60)
    warmeo_log = {
        "username": target_username,
        "started_at": datetime.now().isoformat(),
        "target_duration_min": duration_min,
        "total_scrolls": 0,
        "likes_given": 0,
        "story_likes_given": 0,
        "stories_viewed": 0,
        "explore_visited": False,
        "popups": [],
    }

    try:
        # Verificar que estamos en el feed
        if "/accounts/login" in page.url:
            raise RuntimeError("Sesion no activa. Ejecuta session_manager --setup y re-loguea la cuenta.")

        logger.info("Warmeo iniciado...")

        target_feed_likes = random.randint(2, 4)
        target_story_likes = random.randint(2, 4)
        logger.info(f"Objetivos calculados de interaccion: {target_feed_likes} likes en feed, {target_story_likes} likes en stories")

        # === FASE 1: Feed Scrolling (60% del tiempo) ===
        feed_end = start_time + (duration_min * 60 * 0.6)
        while time.time() < min(feed_end, end_time):
            remaining = (end_time - time.time()) / 60
            logger.info(f"[{remaining:.1f}min restantes] Scrolling feed...")

            max_feed_likes_remaining = max(0, target_feed_likes - warmeo_log["likes_given"])
            scrolls, likes = await _scroll_feed(page, cycles=random.randint(3, 6), max_likes=max_feed_likes_remaining)
            warmeo_log["total_scrolls"] += scrolls
            warmeo_log["likes_given"] += likes

            # Check popups
            popups = await _check_for_popups(page)
            warmeo_log["popups"].extend(popups)

            # Behavioral noise entre fases
            await add_behavior_noise(page)

            # Pausa entre ciclos
            await asyncio.sleep(random.uniform(5, 15))

        # === FASE 2: Stories (25% del tiempo) ===
        if time.time() < end_time:
            stories_count = random.randint(2, 4)
            max_story_likes_remaining = max(0, target_story_likes - warmeo_log["story_likes_given"])
            stories, s_likes = await _view_stories(page, count=stories_count, max_likes=max_story_likes_remaining)
            warmeo_log["stories_viewed"] = stories
            warmeo_log["story_likes_given"] += s_likes

            popups = await _check_for_popups(page)
            warmeo_log["popups"].extend(popups)

        # === FASE 3: Explore (15% del tiempo, opcional) ===
        if time.time() < end_time and random.random() < 0.6:
            explored = await _explore_briefly(page)
            warmeo_log["explore_visited"] = explored

        # Esperar el tiempo restante con behavior noise
        remaining = end_time - time.time()
        if remaining > 5:
            logger.info(f"Finalizando warmeo con {remaining:.0f}s de idle time...")
            await add_behavior_noise(page, duration_seconds=int(min(remaining, 60)))

    except Exception as e:
        logger.error(f"Error durante warmeo: {e}")
        warmeo_log["error"] = str(e)
        raise

    finally:
        # Registrar resultados
        elapsed = (time.time() - start_time) / 60
        warmeo_log["actual_duration_min"] = round(elapsed, 2)
        warmeo_log["finished_at"] = datetime.now().isoformat()

        # Capitalización en Memoria Maestra
        _capitalize_to_memoria(warmeo_log)

        logger.info("=" * 40)
        logger.info(f"Warmeo completado: {elapsed:.1f} min")
        logger.info(f"  Scrolls: {warmeo_log['total_scrolls']}")
        logger.info(f"  Likes: {warmeo_log['likes_given']}")
        logger.info(f"  Stories: {warmeo_log['stories_viewed']}")
        logger.info(f"  Popups: {len(warmeo_log['popups'])}")
        logger.info("=" * 40)

        await browser.close()
        return warmeo_log

def main():
    parser = argparse.ArgumentParser(description="Botardium Core Warmer")
    parser.add_argument("--dry-run", action="store_true", help="Test corto de 2 min")
    parser.add_argument("--duration", type=int, default=None, help="Override duracion (min)")
    parser.add_argument("--username", type=str, default=None, help="Username de IG para cargar sesión")
    args = parser.parse_args()

    asyncio.run(run_warmeo(duration_min=args.duration, dry_run=args.dry_run, username=args.username))


if __name__ == "__main__":
    main()
