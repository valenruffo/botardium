"""
Botardium Core — Outreach Manager
=================================
Orquestador maestro de DMs. Lee leads pendientes de la DB,
respeta los limites diarios (Account DNA), hace batching (bloques de 5)
y delega la humanizacion a human_interactor.

**FASE 4: Integracion con job_runtime para durabilidad e idempotencia**
- Cada ejecución de outreach crea un JobRecord en SQLite
- Usa idempotency_key para evitar ejecución duplicada
- Lease-based locking para recovery ante crashes
- Progress checkpoints para resumabilidad

Consultas: directivas/memoria_maestra.md
           .tmp/account_profile.json
"""

import asyncio
import json
import logging
import random
import re
import time
import sys
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from scripts.runtime_paths import AGENTS_DIR, PROFILE_PATH, SOURCE_ROOT, TMP_DIR

PROJECT_ROOT = SOURCE_ROOT
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(AGENTS_DIR))

EMERGENCY_FLAG = TMP_DIR / "emergency_stop.flag"

from scripts.session_manager import load_or_create_session
from skills.db_manager import DatabaseManager
from skills.human_interactor import type_like_human, random_scroll
from skills.stealth_mod import add_behavior_noise
from scripts.core_warmer import run_warmeo, _capitalize_to_memoria
from scripts.job_runtime import (
    JobRuntime,
    JobStatus,
    JobType,
    JobContext,
    get_job_runtime,
    managed_job,
)

logger = logging.getLogger("primebot.outreach")


def _load_profile() -> dict:
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    logger.error("account_profile.json no encontrado. Ejecutar account_check.py primero.")
    sys.exit(1)


async def _check_anti_pattern(page, memory_log: dict) -> bool:
    """Verifica si Instagram nos bloqueó la accion."""
    checks = [
        'text="Try Again Later"',
        'text="Action Blocked"',
        'text="unusual activity"',
    ]
    for sel in checks:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                logger.error(f"🚨 ALERTA ANTI-PATTERN: Activado '{sel}'")
                memory_log["popups"].append({"type": "ACTION_BLOCKED", "timestamp": datetime.now().isoformat()})
                return True
        except Exception:
            pass
    return False


async def _open_message_composer(page) -> bool:
    import re
    print("[DEBUG _open_message_composer] Intentando JS click nativo...")
    # 1. Prio 1: JS Native Click (most robust against React layout / overlay issues)
    js_click_code = """
    () => {
        const els = Array.from(document.querySelectorAll('div[role="button"], a[role="link"], button'));
        const btn = els.find(d => {
            const text = d.innerText ? d.innerText.trim().toLowerCase() : '';
            return text === 'mensaje' || text === 'message' || text === 'enviar mensaje';
        });
        if (btn) {
            btn.click();
            return true;
        }
        return false;
    }
    """
    try:
        clicked = await page.evaluate(js_click_code)
        print(f"[DEBUG _open_message_composer] JS eval returned: {clicked}")
        if clicked:
            await asyncio.sleep(random.uniform(3, 6))
            try:
                # relax visibility check, just check DOM presence first
                c = await page.locator('div[role="textbox"]').count()
                print(f"[DEBUG _open_message_composer] textbox count: {c}")
                if c > 0:
                    return True
            except Exception as e:
                print(f"[DEBUG _open_message_composer] textbox error: {e}")
    except Exception as e:
        print(f"[DEBUG _open_message_composer] JS eval exception: {e}")

    print("[DEBUG _open_message_composer] JS falló, probando fallback 1 (get_by_role)...")
    # 2. Prio 2: Fallback to exact matches by role (Playwright internal)
    try:
        buttons = page.get_by_role("button", name=re.compile(r"^(Message|Mensaje|Enviar mensaje)$", re.I))
        count = await buttons.count()
        for i in range(count):
            btn = buttons.nth(i)
            try:
                await btn.wait_for(state="visible", timeout=2000)
                if await btn.is_visible():
                    await btn.click(timeout=5000, force=True)
                    await asyncio.sleep(random.uniform(3, 5))
                    if await page.locator('div[role="textbox"]').count() > 0:
                        return True
            except Exception:
                continue
    except Exception:
        pass

    print("[DEBUG _open_message_composer] Fallback 1 falló, probando fallback 2 (selectors)...")
    # 3. Prio 3: Fallback locators
    selectors = [
        'div[role="button"]:text-is("Message")',
        'div[role="button"]:text-is("Mensaje")',
        'div[role="button"]:text-is("Enviar mensaje")',
        'a[role="link"]:text-is("Message")',
        'a[role="link"]:text-is("Mensaje")'
    ]

    for selector in selectors:
        try:
            locs = page.locator(selector)
            c = await locs.count()
            for i in range(c):
                btn = locs.nth(i)
                try:
                    await btn.wait_for(state="visible", timeout=2000)
                    if await btn.is_visible():
                        await btn.click(timeout=5000, force=True)
                        await asyncio.sleep(random.uniform(3, 5))
                        if await page.locator('div[role="textbox"]').count() > 0:
                            return True
                except Exception:
                    continue
        except Exception:
            continue

    print("[DEBUG _open_message_composer] Fallback 2 falló, probando fallback 3 (get_by_text)...")
    text_locators = [
        page.get_by_text(re.compile(r"^message$", re.I)),
        page.get_by_text(re.compile(r"^mensaje$", re.I)),
        page.get_by_text(re.compile(r"^enviar mensaje$", re.I)),
    ]
    for locator in text_locators:
        try:
            c = await locator.count()
            for i in range(c):
                btn = locator.nth(i)
                try:
                    await btn.wait_for(state="visible", timeout=2000)
                    await btn.click(timeout=5000, force=True)
                    await asyncio.sleep(random.uniform(3, 5))
                    if await page.locator('div[role="textbox"]').count() > 0:
                        return True
                except Exception:
                    continue
        except Exception:
            continue

    print("[DEBUG _open_message_composer] TODOS LOS INTENTOS FALLARON.")
    return False


def _next_status_after_send(current_status: str) -> str:
    if current_status == "Listo para contactar":
        return "Primer contacto"
    if current_status == "Primer contacto":
        return "Follow-up 1"
    if current_status == "Follow-up 1":
        return "Follow-up 2"
    return "Completado"


def _send_variant_for_status(current_status: str) -> str | None:
    if current_status == "Listo para contactar":
        return "first_contact"
    if current_status == "Primer contacto":
        return "follow_up_1"
    if current_status == "Follow-up 1":
        return "follow_up_2"
    return None


def _prompt_for_send_variant(lead: Dict, variant: str) -> str:
    base_prompt = str(lead.get("message_prompt") or "").strip()
    defaults = {
        "first_contact": "Te escribo corto porque me pareció interesante lo que hacen y quería abrir una conversación simple para ver si tiene sentido hablar.",
        "follow_up_1": "Retomo este mensaje por si te quedó colgado. Si querés, te comparto una idea puntual aplicada a tu caso.",
        "follow_up_2": "Te dejo este último mensaje para no insistir de más. Si te sirve, coordinamos cuando te quede cómodo.",
    }
    if variant == "first_contact":
        return base_prompt or defaults[variant]
    return defaults.get(variant, defaults["follow_up_1"])


def _runtime_message_for_lead(lead: Dict) -> str:
    status = str(lead.get("status") or "Listo para contactar")
    variant = _send_variant_for_status(status)
    if not variant:
        return ""

    if variant == "first_contact":
        existing = str(lead.get("last_message_preview") or "").strip()
        if existing:
            return existing

    prompt = _prompt_for_send_variant(lead, variant)
    full_name = str(lead.get("full_name") or "").strip()
    first_name = ""
    if full_name and full_name.lower() not in {"instagram user", "usuario", "empresa"}:
        token = full_name.split()[0].strip()
        if len(token) >= 3 and token.isalpha():
            first_name = token

    if first_name:
        greeting = f"Hola {first_name},"
    else:
        greeting = "Hola,"

    if variant == "follow_up_1":
        opener = f"{greeting} retomo este mensaje por si te quedó colgado."
    elif variant == "follow_up_2":
        opener = f"{greeting} te dejo este último mensaje y no molesto más."
    else:
        opener = f"{greeting} te escribo porque creo que puede sumarte una idea puntual."

    message = f"{opener} {prompt}".strip()
    return re.sub(r"\s+", " ", message)


async def run_outreach(
    dry_run: bool = False,
    lead_ids: list[int] | None = None,
    limit_override: int | None = None,
    progress_hook=None,
    job_id: str | None = None,
    worker_id: str | None = None,
):
    """
    Ejecuta el flujo principal de Outreach (Mensajeria).
    
    FASE 4: Integracion con job_runtime para durabilidad e idempotencia.
    Si se proporciona job_id, el job sera gestionado por el sistema de jobs:
    - Crea un JobRecord en SQLite con lease-based locking
    - Usa idempotency_key para evitar ejecuciones duplicadas
    - Progress checkpoints para resumabilidad
    - Recovery automatico de jobs huerfanos
    
    Args:
        job_id: ID del job en job_runtime. Si se proporciona, se gestiona el lifecycle.
        worker_id: ID del worker que ejecuta el job. Default: generated uuid.
    """
    runtime = get_job_runtime()
    job_record = None
    workspace_id = 1
    
    if job_id:
        worker_id = worker_id or f"outreach_worker_{uuid.uuid4().hex[:8]}"
        job_runtime = runtime
        
        idempotency_key = runtime.generate_idempotency_key(
            "outreach",
            str(workspace_id),
            str(sorted(lead_ids)) if lead_ids else "all_pending",
            datetime.now().date().isoformat()
        )
        
        job_record = runtime.create_job(
            job_id=job_id,
            job_type=JobType.MESSAGE_OUTREACH.value,
            workspace_id=workspace_id,
            payload={
                "lead_ids": lead_ids,
                "limit_override": limit_override,
                "dry_run": dry_run,
            },
            idempotency_key=idempotency_key,
        )
        
        if job_record and job_record.status == JobStatus.COMPLETED.value:
            logger.info(f"Job {job_id} ya completado anteriormente (idempotency hit)")
            return {"sent": 0, "processed": 0, "errors": 0, "job_status": "completed", "result": json.loads(job_record.result or "{}")}
        
        try:
            with managed_job(job_id, worker_id, job_runtime) as ctx:
                result = await _run_outreach_impl(
                    dry_run=dry_run,
                    lead_ids=lead_ids,
                    limit_override=limit_override,
                    progress_hook=progress_hook,
                    ctx=ctx,
                )
                ctx.complete(result)
                return {**result, "job_status": "completed"}
        except Exception as e:
            if job_runtime.get_job(job_id):
                job_runtime.fail_job(job_id, str(e))
            raise
    else:
        return await _run_outreach_impl(
            dry_run=dry_run,
            lead_ids=lead_ids,
            limit_override=limit_override,
            progress_hook=progress_hook,
            ctx=None,
        )


async def _run_outreach_impl(
    dry_run: bool = False,
    lead_ids: list[int] | None = None,
    limit_override: int | None = None,
    progress_hook=None,
    ctx=None,
) -> Dict[str, Any]:
    """
    Ejecuta el flujo principal de Outreach (Mensajeria).
    """
    profile = _load_profile()
    db = DatabaseManager()
    
    # 1. Determinar Limites Diarios y Estado
    # (En un bot en produccion, aquí cruzariamos contra una DB de analytics diarios
    # para saber cuantos ya enviamos hoy. Por ahora, tomaremos el maximo total del perfil).
    max_dms = limit_override or profile.get("max_dms_per_day", 10)
    delay_dm = profile.get("action_delay_dm", {"min": 120, "max": 480})
    batch_size = int(profile.get("dm_block_size", 10))
    block_pause_min = int(profile.get("dm_block_pause_min", 60))
    block_pause_max = int(profile.get("dm_block_pause_max", 90))
    ip_rotation_enabled = profile.get("ip_rotation_enabled", False)
    ip_rotation_freq = profile.get("ip_rotation_every_n_actions", 5)
    session_warmup_required = bool(profile.get("session_warmup_required", True))

    if dry_run:
        max_dms = 2
        delay_dm = {"min": 5, "max": 10}
        logger.info("=== DRY RUN MODE: Limites reducidos ===")

    logger.info("=" * 60)
    logger.info(f"✉️  Botardium Outreach Manager")
    logger.info(f"   Max DMs permitidos: {max_dms}")
    logger.info(f"   Delay entre DMs: {delay_dm['min']//60}-{delay_dm['max']//60} min")
    logger.info("=" * 60)

    # 2. Obtener Leads
    # Pedimos la cantidad exacta que nos permite el limite
    selected_ids = list(lead_ids) if lead_ids is not None else None
    leads = db.get_outreach_leads(limit=max_dms, ids=selected_ids)
    
    if not leads:
        logger.info("No hay leads listos en la cola de outreach.")
        if progress_hook:
            await progress_hook({"status": "completed", "progress": 100, "current_action": "No habia leads listos para enviar."})
        return {"sent": 0, "processed": 0, "errors": 0}

    logger.info(f"Procesando {len(leads)} leads pendientes...")
    no_dm_button = 0
    blocked = 0

    # 3. Iniciar Navegador
    browser, context, page = await load_or_create_session(str(profile.get("ig_username") or ""))
    
    # Warmeo Pre-Outreach (Mandatorio)
    if not dry_run and session_warmup_required:
        logger.info("Ejecutando Warmeo Pre-Sesion mandatorio...")
        warmup_res = await run_warmeo(duration_min=max(15, min(int(profile.get("warmup_duration_min", 20)), 25)))
        if warmup_res:
            db.update_account_warmup_log(str(profile.get("ig_username", "")), warmup_res)
    elif not dry_run:
        logger.info("Cuenta personal madura: bypass de warmup de sesion previo.")
    
    # Tracking de la sesión
    dms_sent_this_session = 0
    consecutive_actions_for_ip_rotation = 0
    memory_log = {"dms_sent": 0, "popups": []}

    errors = 0
    processed_count = 0
    started_ts = time.time()
    compose_min_seconds = 35
    compose_max_seconds = 70

    def _estimate_eta_seconds(processed: int, total: int) -> int:
        remaining = max(0, total - processed)
        if remaining <= 0:
            return 0
        elapsed = max(1.0, time.time() - started_ts)
        if processed <= 0:
            return int(remaining * 140)
        avg_per_lead = elapsed / processed
        return int(max(10, remaining * avg_per_lead))

    def _estimate_eta_range(processed: int, total: int) -> tuple[int, int]:
        remaining = max(0, total - processed)
        min_per_lead = int(delay_dm.get("min", 120)) + compose_min_seconds
        max_per_lead = int(delay_dm.get("max", 480)) + compose_max_seconds
        if processed > 0:
            elapsed = max(1.0, time.time() - started_ts)
            observed_avg = elapsed / processed
            observed_min = max(30, int(observed_avg * 0.8))
            observed_max = max(observed_min + 15, int(observed_avg * 1.25))
            min_per_lead = max(60, min(max_per_lead, observed_min))
            max_per_lead = max(min_per_lead + 15, min(3600, observed_max))
        return remaining * min_per_lead, remaining * max_per_lead

    def _update_job_progress(current: int, total: int, current_lead: str):
        if ctx:
            progress = current / max(total, 1)
            checkpoint = f"lead_{current}:{current_lead}"
            ctx.update_progress(progress, checkpoint)
    
    try:
        # BATCHING: Procesar en bloques definidos por perfil
        for i, lead in enumerate(leads):
            if EMERGENCY_FLAG.exists():
                logger.error("🚨 EMERGENCY STOP ACTIVADO. Abortando loop de mensajería inmediatamente.")
                _update_job_progress(i, len(leads), "EMERGENCY_STOP")
                break

            username = lead['ig_username']
            logger.info(f"\n--- [DM {i+1}/{len(leads)}] Target: @{username} ---")
            _update_job_progress(i, len(leads), username)
            if progress_hook:
                eta_min, eta_max = _estimate_eta_range(i, len(leads))
                await progress_hook({
                    "status": "running",
                    "progress": int((i / max(len(leads), 1)) * 100),
                    "current_action": f"Procesando @{username} ({i+1}/{len(leads)})",
                    "current_lead": username,
                    "processed": i,
                    "total": len(leads),
                    "eta_seconds": _estimate_eta_seconds(i, len(leads)),
                    "eta_min_seconds": eta_min,
                    "eta_max_seconds": eta_max,
                    "metrics": {
                        "sent": dms_sent_this_session,
                        "errors": errors,
                        "blocked": blocked,
                        "no_dm_button": no_dm_button,
                    },
                })

            # 4. Rotacion IP (Si aplica)
            if ip_rotation_enabled and consecutive_actions_for_ip_rotation >= ip_rotation_freq:
                logger.info("🔄 Activando rotación IP via ADB (Ciclo cumplido)...")
                from skills.adb_manager import ADBManager
                adb = ADBManager(**profile.get("adb", {}))
                if adb.connect():
                    adb.rotate_ip()
                consecutive_actions_for_ip_rotation = 0
                
                # Pausa post-rotación
                await asyncio.sleep(random.uniform(10, 20))

            # 5. Navegar al perfil organico
            await page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(3, 7))

            # Verificar Anti-Pattern al cargar perfil
            if await _check_anti_pattern(page, memory_log):
                logger.error("Bloqueo detectado al cargar perfil. Abortando sesion.")
                blocked += 1
                break

            # Simulacion de lectura de perfil
            await random_scroll(page, "down", (300, 600), (2, 5))
            if random.random() < 0.3:
                await random_scroll(page, "up", (100, 300), (1, 3))

            # 6. Click Mensaje
            try:
                if not await _open_message_composer(page):
                    logger.warning(f"No se pudo encontrar el boton Mensaje para @{username}.")
                    db.update_status(username, "Error - No DM Button")
                    db.update_lead_after_message(username, "Error - No DM Button", result="sin_boton_dm", error_detail="No se encontró el botón Mensaje en el perfil.")
                    no_dm_button += 1
                    errors += 1
                    processed_count += 1
                    if progress_hook:
                        eta_min, eta_max = _estimate_eta_range(i + 1, len(leads))
                        await progress_hook({
                            "status": "running",
                            "progress": int(((i + 1) / max(len(leads), 1)) * 100),
                            "current_action": f"Sin botón DM en @{username} ({i+1}/{len(leads)})",
                            "current_lead": username,
                            "processed": i + 1,
                            "total": len(leads),
                            "eta_seconds": _estimate_eta_seconds(i + 1, len(leads)),
                            "eta_min_seconds": eta_min,
                            "eta_max_seconds": eta_max,
                            "metrics": {
                                "sent": dms_sent_this_session,
                                "errors": errors,
                                "blocked": blocked,
                                "no_dm_button": no_dm_button,
                            },
                        })
                    continue
            except Exception as e:
                logger.warning(f"Error buscando boton Mensaje para @{username}: {e}")
                db.update_status(username, "Error - No DM Button")
                db.update_lead_after_message(username, "Error - No DM Button", result="error_apertura_dm", error_detail=str(e))
                no_dm_button += 1
                errors += 1
                processed_count += 1
                if progress_hook:
                    eta_min, eta_max = _estimate_eta_range(i + 1, len(leads))
                    await progress_hook({
                        "status": "running",
                        "progress": int(((i + 1) / max(len(leads), 1)) * 100),
                        "current_action": f"Fallo al abrir DM en @{username} ({i+1}/{len(leads)})",
                        "current_lead": username,
                        "processed": i + 1,
                        "total": len(leads),
                        "eta_seconds": _estimate_eta_seconds(i + 1, len(leads)),
                        "eta_min_seconds": eta_min,
                        "eta_max_seconds": eta_max,
                        "metrics": {
                            "sent": dms_sent_this_session,
                            "errors": errors,
                            "blocked": blocked,
                            "no_dm_button": no_dm_button,
                        },
                    })
                continue

            # 7. Redactar y Enviar DM
            try:
                message_template = _runtime_message_for_lead(lead)
                if not message_template:
                    logger.info(f"Lead @{username} ya no tiene un siguiente paso automático para enviar.")
                    continue
                
                # El selector de input de dms (varía, este es genérico de contenteditable)
                input_box = page.locator('div[role="textbox"]')
                
                # Espera suave (se superó el timeout estricto de visibilidad)
                await asyncio.sleep(2)
                
                if not dry_run:
                    await type_like_human(page, 'div[role="textbox"]', message_template)
                    # Enviar (Intentos combinados: Tecla Enter + Click JS en el boton de envio)
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(1)
                    
                    # Fallback click JS (A veces Instagram ignora 'Enter' y requiere click en el boton Enviar explicitamente)
                    await page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('div[role="button"]'));
                        const sendBtn = btns.find(b => {
                            const t = b.innerText ? b.innerText.trim().toLowerCase() : '';
                            return t === 'enviar' || t === 'send';
                        });
                        if (sendBtn) sendBtn.click();
                    }""")
                    
                    logger.info(f"✅ DM enviado a @{username}")
                else:
                    logger.info(f"✅ [DRY RUN] Simulación DM escrito a @{username}")

                sent_at = datetime.now().isoformat()
                next_status = _next_status_after_send(str(lead.get("status") or "Listo para contactar"))
                next_follow_up = datetime.fromtimestamp(time.time() + (3 * 86400)).isoformat() if next_status in {"Primer contacto", "Follow-up 1", "Follow-up 2"} else None
                db.update_lead_after_message(
                    username,
                    next_status,
                    sent_at=sent_at,
                    follow_up_due_at=next_follow_up,
                    message_variant=str(lead.get("message_variant") or "v1-personalizado"),
                    result="enviado" if not dry_run else "dry_run_ok",
                    error_detail=None,
                )
                dms_sent_this_session += 1
                consecutive_actions_for_ip_rotation += 1
                memory_log["dms_sent"] += 1
                if progress_hook:
                    eta_min, eta_max = _estimate_eta_range(i + 1, len(leads))
                    await progress_hook({
                        "status": "running",
                        "progress": int(((i + 1) / max(len(leads), 1)) * 100),
                        "current_action": f"DM enviado a @{username} ({i+1}/{len(leads)})",
                        "current_lead": username,
                        "processed": i + 1,
                        "total": len(leads),
                        "eta_seconds": _estimate_eta_seconds(i + 1, len(leads)),
                        "eta_min_seconds": eta_min,
                        "eta_max_seconds": eta_max,
                        "metrics": {
                            "sent": dms_sent_this_session,
                            "errors": errors,
                            "blocked": blocked,
                            "no_dm_button": no_dm_button,
                        },
                    })
                processed_count += 1

            except Exception as e:
                logger.error(f"Error escribiendo DM a @{username}: {e}")
                db.update_status(username, "Error - Fallo envio")
                db.update_lead_after_message(username, "Error - Fallo envio", result="error_envio", error_detail=str(e))
                errors += 1
                processed_count += 1
                if progress_hook:
                    eta_min, eta_max = _estimate_eta_range(i + 1, len(leads))
                    await progress_hook({
                        "status": "running",
                        "progress": int(((i + 1) / max(len(leads), 1)) * 100),
                        "current_action": f"Error de envío en @{username} ({i+1}/{len(leads)})",
                        "current_lead": username,
                        "processed": i + 1,
                        "total": len(leads),
                        "eta_seconds": _estimate_eta_seconds(i + 1, len(leads)),
                        "eta_min_seconds": eta_min,
                        "eta_max_seconds": eta_max,
                        "metrics": {
                            "sent": dms_sent_this_session,
                            "errors": errors,
                            "blocked": blocked,
                            "no_dm_button": no_dm_button,
                        },
                    })

            # 8. Descansos (Delays y Batching)
            if i < len(leads) - 1:
                # Descanso largo entre batches
                if (i + 1) % batch_size == 0:
                    pause_min = random.randint(block_pause_min, block_pause_max) if not dry_run else 1
                    logger.info(f"☕ Batch de {batch_size} completado. Pausa de batching: {pause_min} min...")
                    if not dry_run:
                        # Durante pausas largas aplicamos ruido para mantener la conexion viva
                        await add_behavior_noise(page, duration_seconds=(pause_min * 60))
                    else:
                        await asyncio.sleep(pause_min)
                else:
                    # Delay normal entre DMs (Gaussiano en el rango definido en Account DNA)
                    delay_sec = random.uniform(delay_dm['min'], delay_dm['max'])
                    logger.info(f"⏳ Delay pre-calculado de {delay_sec:.1f}s antes del proximo DM...")
                    await add_behavior_noise(page, duration_seconds=int(delay_sec))

    except Exception as e:
        logger.error(f"Falla critica en Orchestrator: {e}")
        if progress_hook:
            await progress_hook({"status": "error", "progress": 0, "current_action": f"Falla critica: {e}"})
    finally:
        logger.info("=" * 60)
        logger.info(f"🏁 Outreach Sesion Finalizada | DMs enviados: {dms_sent_this_session}")
        logger.info("=" * 60)
        
        # Capitalizar bloqueos en Memoria Maestra si los hubo
        if memory_log["popups"]:
            _capitalize_to_memoria(memory_log)
            
        await browser.close()

    if progress_hook:
        await progress_hook({
            "status": "completed",
            "progress": 100,
            "current_action": f"Outreach finalizado. {dms_sent_this_session} DM(s) enviados.",
            "processed": processed_count,
            "total": len(leads),
            "current_lead": None,
            "eta_seconds": 0,
            "eta_min_seconds": 0,
            "eta_max_seconds": 0,
            "metrics": {
                "sent": dms_sent_this_session,
                "errors": errors,
                "blocked": blocked,
                "no_dm_button": no_dm_button,
            },
        })

    return {"sent": dms_sent_this_session, "processed": processed_count, "errors": errors, "blocked": blocked, "no_dm_button": no_dm_button}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Botardium Outreach Manager")
    parser.add_argument("--dry-run", action="store_true", help="Simulacion, no envia mensajes reales y reduce esperas")
    args = parser.parse_args()

    asyncio.run(run_outreach(dry_run=args.dry_run))
