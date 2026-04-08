"""
Botardium Core — Lead Scraper
==================================
Extracción de leads interceptando respuestas JSON de la API (GraphQL/v1).
Mas rapido y seguro que parsear HTML.
Incluye filtros de calidad basados en bio (Keywords).

Consulta: directivas/memoria_maestra.md
Output: database/botardium.db

Uso:
    python scripts/lead_scraper.py --target hashtag --query "marketing" --limit 50
    python scripts/lead_scraper.py --target followers --query "elonmusk" --limit 50
"""

import asyncio
import json
import argparse
import contextvars
import logging
import os
import re
import sys
import time
import random
import uuid
from datetime import datetime
from urllib.parse import quote
from pathlib import Path
from typing import Any, Dict
from scripts.runtime_config import load_bootstrap_env
from scripts.runtime_paths import PROFILE_PATH, SKILLS_DIR, SOURCE_ROOT, TMP_DIR
from scripts.job_runtime import JobType, get_job_runtime, managed_job

# Paths
API_ROOT = SOURCE_ROOT
PROJECT_ROOT = SOURCE_ROOT
sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(SKILLS_DIR))

STATUS_FILE = TMP_DIR / "scraper_status.json"
RUNTIME_EVIDENCE_DIR = TMP_DIR / "runtime_failures"
SCRAPER_STATUS_HOOK = contextvars.ContextVar("scraper_status_hook", default=None)

# Imports del Core
from scripts.session_manager import load_or_create_session
from db_manager import DatabaseManager

try:
    from google import genai as google_genai
    from google.genai import types as google_genai_types
except Exception:
    google_genai = None
    google_genai_types = None

logger = logging.getLogger("primebot.scraper")
load_bootstrap_env()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
GEMINI_NICHE_CACHE: dict[str, tuple[bool, str]] = {}

MIN_FOLLOWERS = 80
MIN_POSTS = 3
MIN_HASHTAG_POSTS_FOR_SCRAPE = 6
HASHTAG_LINK_SELECTORS = [
    "article a[href*='/p/']",
    "article a[href*='/reel/']",
    "main a[href*='/p/']",
    "main a[href*='/reel/']",
    "a[href*='/p/']",
    "a[href*='/reel/']",
]


def _sanitize_artifact_component(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip().lower())
    return cleaned.strip("-._") or "runtime"


async def _humanized_wait(min_seconds: float, max_seconds: float, reason: str) -> float:
    delay = random.uniform(min_seconds, max(max_seconds, min_seconds))
    logger.debug("Humanized wait %.2fs | %s", delay, reason)
    await asyncio.sleep(delay)
    return delay


async def _capture_runtime_evidence(
    page,
    stage: str,
    error: Exception | str | None = None,
    *,
    selector: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    RUNTIME_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    stem = f"scraper_{_sanitize_artifact_component(stage)}_{timestamp}"
    screenshot_path = RUNTIME_EVIDENCE_DIR / f"{stem}.png"
    metadata_path = RUNTIME_EVIDENCE_DIR / f"{stem}.json"
    detail = str(error).strip() if error is not None else ""
    evidence: dict[str, Any] = {
        "flow": "scraper",
        "stage": stage,
        "selector": selector or "",
        "error": detail,
        "timestamp": datetime.now().isoformat(),
        "page_url": "",
        "page_title": "",
        "screenshot_path": "",
        "extra": extra or {},
    }

    if page is not None:
        try:
            evidence["page_url"] = str(page.url or "")
        except Exception as exc:
            logger.debug("No pude leer page.url para evidencia scraper (%s): %s", stage, exc)
        try:
            evidence["page_title"] = str(await page.title())
        except Exception as exc:
            logger.debug("No pude leer title para evidencia scraper (%s): %s", stage, exc)
        try:
            await page.screenshot(path=str(screenshot_path), full_page=True, timeout=5000)
            evidence["screenshot_path"] = str(screenshot_path)
        except Exception as exc:
            evidence["screenshot_error"] = str(exc)
            logger.warning("No pude guardar screenshot de scraper en %s: %s", screenshot_path, exc)

    metadata_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.warning("Evidencia de scraper guardada en %s", metadata_path)
    return evidence


async def _open_location_target(context, page, query: str):
    """Resuelve una location usando el endpoint interno de search y navega al lugar."""
    search_url = f"https://www.instagram.com/web/search/topsearch/?context=place&query={quote(query)}"
    response = await context.request.get(search_url)
    if not response.ok:
        raise RuntimeError(f"No pude resolver la location '{query}' desde topsearch.")

    payload = await response.json()
    places = payload.get("places") or []
    if not places:
        fallback_url = f"https://www.instagram.com/explore/search/keyword/?q={quote(query)}"
        update_scraper_status("running", 0, 0, f"Topsearch sin places. Fallback a {fallback_url}...")
        await page.goto(fallback_url, wait_until="domcontentloaded", timeout=20000)
        await _humanized_wait(2.2, 4.6, "location fallback search settle")
        return

    location = (places[0] or {}).get("place", {}).get("location", {})
    pk = location.get("pk") or location.get("id")
    slug = location.get("slug") or location.get("name") or query
    if not pk:
        raise RuntimeError(f"Location sin pk valida para '{query}'.")

    target_url = f"https://www.instagram.com/explore/locations/{pk}/{quote(str(slug).replace(' ', '-'))}/"
    update_scraper_status("running", 0, 0, f"Location encontrada. Navegando a {target_url}...")
    await page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
    await _humanized_wait(2.2, 4.6, "location page settle")


async def _collect_post_links(page) -> list[str]:
    selectors = HASHTAG_LINK_SELECTORS
    links: list[str] = []
    for selector in selectors:
        try:
            hrefs = await page.locator(selector).evaluate_all(
                "els => els.map(el => el.getAttribute('href')).filter(Boolean)"
            )
            if isinstance(hrefs, list):
                links.extend(str(href) for href in hrefs)
        except Exception as exc:
            logger.debug("Fallo leyendo links con selector %s: %s", selector, exc)
            continue
    deduped: list[str] = []
    seen: set[str] = set()
    for href in links:
        if href not in seen:
            seen.add(href)
            deduped.append(href)
    return deduped


def _adaptive_cooldown(failure_streak: int) -> float:
    if failure_streak >= 8:
        return random.uniform(8, 12)
    if failure_streak >= 5:
        return random.uniform(5, 8)
    if failure_streak >= 3:
        return random.uniform(2.5, 4.5)
    return random.uniform(0.8, 1.5)


def _extract_post_owners_from_json(data: Any) -> list[dict[str, Any]]:
    """Extract post owner user objects from Instagram's API/GraphQL responses.

    Unlike _extract_users_from_json (which looks for user lists), this searches
    for post→owner patterns in the JSON tree, extracting the profile of whoever
    authored each post.  This is the key to reliable hashtag scraping.
    """
    owners: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            # Pattern 1: GraphQL post with owner
            owner = node.get("owner")
            if isinstance(owner, dict) and owner.get("username"):
                un = str(owner["username"])
                if un not in seen:
                    seen.add(un)
                    owners.append(owner)

            # Pattern 2: API v1 media with user
            user = node.get("user")
            if isinstance(user, dict) and user.get("username") and user.get("pk"):
                un = str(user["username"])
                if un not in seen:
                    seen.add(un)
                    owners.append(user)

            # Pattern 3: caption → user (API v1 media items)
            caption = node.get("caption")
            if isinstance(caption, dict):
                cap_user = caption.get("user")
                if isinstance(cap_user, dict) and cap_user.get("username") and cap_user.get("pk"):
                    un = str(cap_user["username"])
                    if un not in seen:
                        seen.add(un)
                        owners.append(cap_user)

            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(data)
    return owners


async def _extract_author_via_grid_click(page, href: str, own_username: str, source_url: str) -> str | None:
    target_href = href if href.startswith("/") else f"/{href.lstrip('/')}"
    cleaned = target_href.split("?", 1)[0].split("#", 1)[0]

    # Try direct navigation to the post URL first (more reliable than click)
    # Extract the post shortcode from href
    post_url = f"https://www.instagram.com{cleaned}" if cleaned.startswith("/") else cleaned

    clicked = False
    try:
        clicked = bool(await page.evaluate(
            """
            (targetHref) => {
              const normalize = (value) => (value || '').split('?')[0].split('#')[0];
              const links = Array.from(document.querySelectorAll("a[href*='/p/'], a[href*='/reel/']"));
              const match = links.find((el) => normalize(el.getAttribute('href')) === normalize(targetHref));
              if (!match) return false;

              const rect = match.getBoundingClientRect();
              if (rect.top < 0 || rect.bottom > window.innerHeight) {
                match.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
              }

              const clickable = match.closest('a, button, article, div') || match;
              clickable.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true, view: window }));
              clickable.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
              clickable.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
              clickable.click();
              return true;
            }
            """,
            cleaned,
        ))
        if not clicked:
            return None
        await _humanized_wait(1.5, 3.2, "post modal settle after click")

        # Try DOM-based extraction first
        candidate_username = await asyncio.wait_for(_extract_post_author_username(page, own_username), timeout=4)

        # If DOM extraction failed, try meta tag extraction (more reliable)
        if not candidate_username:
            try:
                og_title = await page.evaluate(
                    """() => document.querySelector('meta[property="og:title"]')?.getAttribute('content') || ''"""
                )
                # Instagram og:title format: "Full Name (@username) • Instagram photo"
                # or "username on Instagram: ..."
                if og_title:
                    at_match = re.search(r"@([a-zA-Z0-9_.]+)", og_title)
                    if at_match:
                        candidate_username = at_match.group(1).lower()
                    elif " on Instagram" in og_title:
                        candidate_username = og_title.split(" on Instagram")[0].strip().lower()
            except Exception as exc:
                logger.debug("No pude leer og:title para post %s: %s", cleaned, exc)
    except Exception as exc:
        logger.warning("Fallo extrayendo autor via grid click para %s: %s", cleaned, exc)
        await _capture_runtime_evidence(page, "grid_click_author", exc, selector=cleaned, extra={"source_url": source_url})
        candidate_username = None
    finally:
        try:
            current_url = str(page.url or "")
            if "/p/" in current_url or "/reel/" in current_url:
                await asyncio.wait_for(page.go_back(wait_until="domcontentloaded", timeout=10000), timeout=12)
            else:
                await asyncio.wait_for(page.keyboard.press("Escape"), timeout=3)
                await _humanized_wait(0.35, 0.9, "post dialog close settle")
        except Exception as exc:
            logger.debug("No pude volver con go_back/Escape desde %s: %s", current_url if 'current_url' in locals() else cleaned, exc)
            try:
                await asyncio.wait_for(page.goto(source_url, wait_until="domcontentloaded", timeout=20000), timeout=22)
                await _humanized_wait(0.8, 1.8, "restore source url after grid click failure")
            except Exception as restore_exc:
                logger.warning("No pude restaurar la pagina origen %s: %s", source_url, restore_exc)
                await _capture_runtime_evidence(page, "grid_click_restore", restore_exc, extra={"source_url": source_url})

    if candidate_username and candidate_username == own_username:
        return None
    return candidate_username


async def _collect_selector_counts(page, selectors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for selector in selectors:
        try:
            counts[selector] = await page.locator(selector).count()
        except Exception as exc:
            logger.debug("No pude contar selector %s: %s", selector, exc)
            counts[selector] = 0
    return counts


def _is_on_hashtag_url(url: str, hashtag: str) -> bool:
    normalized = _normalize_hashtag(hashtag)
    lowered = str(url or "").lower()
    return f"/explore/tags/{normalized}" in lowered


async def _collect_hashtag_page_diagnostics(page, hashtag: str) -> dict[str, Any]:
    selector_counts = await _collect_selector_counts(page, HASHTAG_LINK_SELECTORS)
    current_url = str(page.url or "")
    try:
        title = await page.title()
    except Exception as exc:
        logger.debug("No pude leer title del hashtag %s: %s", hashtag, exc)
        title = ""
    try:
        canonical = await page.evaluate(
            """() => document.querySelector('link[rel="canonical"]')?.getAttribute('href') || ''"""
        )
    except Exception as exc:
        logger.debug("No pude leer canonical del hashtag %s: %s", hashtag, exc)
        canonical = ""
    total_links = int(sum(selector_counts.values()))
    normalized = _normalize_hashtag(hashtag)
    is_search_keyword_url = f"/explore/search/keyword/?q=%23{normalized}" in current_url.lower()
    is_tag_url = _is_on_hashtag_url(current_url, hashtag)
    is_hashtag_context = bool(is_tag_url or (is_search_keyword_url and total_links > 0))
    return {
        "expected_hashtag": normalized,
        "current_url": current_url,
        "canonical_url": str(canonical or ""),
        "page_title": str(title or ""),
        "selector_counts": selector_counts,
        "total_post_links": total_links,
        "is_tag_url": is_tag_url,
        "is_search_keyword_url": is_search_keyword_url,
        "is_hashtag_context": is_hashtag_context,
        "grid_detected": total_links > 0,
    }


async def _wait_for_hashtag_grid(page, hashtag: str, rounds: int = 4) -> dict[str, Any]:
    best: dict[str, Any] = {}
    best_links = -1
    for attempt in range(rounds):
        await _humanized_wait(0.8 + attempt, 1.6 + attempt, f"wait for hashtag grid attempt {attempt + 1}")
        diag = await _collect_hashtag_page_diagnostics(page, hashtag)
        links = int(diag.get("total_post_links") or 0)
        if links > best_links:
            best_links = links
            best = diag
        if links >= MIN_HASHTAG_POSTS_FOR_SCRAPE:
            diag["ready"] = True
            diag["ready_attempt"] = attempt + 1
            return diag
        await page.mouse.wheel(0, random.randint(1000, 2200))

    if not best:
        best = await _collect_hashtag_page_diagnostics(page, hashtag)
    best["ready"] = bool(int(best.get("total_post_links") or 0) >= MIN_HASHTAG_POSTS_FOR_SCRAPE)
    best["ready_attempt"] = rounds
    return best


async def _open_hashtag_via_search(page, hashtag: str) -> bool:
    normalized = _normalize_hashtag(hashtag)
    if not normalized:
        return False

    search_url = f"https://www.instagram.com/explore/search/keyword/?q=%23{quote(normalized)}"
    await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
    await _humanized_wait(1.5, 3.1, "hashtag search results settle")

    link_selectors = [
        f"a[href*='/explore/tags/{normalized}/']",
        "a[href*='/explore/tags/']",
    ]

    for selector in link_selectors:
        locator = page.locator(selector)
        count = await locator.count()
        if count <= 0:
            continue
        for index in range(min(count, 8)):
            candidate = locator.nth(index)
            href = (await candidate.get_attribute("href") or "").lower()
            if normalized not in href and selector != "a[href*='/explore/tags/']":
                continue
            try:
                await candidate.click(timeout=2500)
                try:
                    await page.wait_for_url(f"**/explore/tags/{normalized}/**", timeout=5000)
                except Exception as exc:
                    logger.debug("wait_for_url no confirmó hashtag %s: %s", normalized, exc)
                    await _humanized_wait(1.4, 2.9, "hashtag click fallback settle")
                current_url = page.url.lower()
                if "/explore/tags/" in current_url and normalized in current_url:
                    return True
            except Exception as exc:
                logger.debug("Click de hashtag %s falló con selector %s: %s", normalized, selector, exc)
                continue

    return False


def _normalize_hashtag(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "", str(value or "").replace("#", "").strip().lower())
    return cleaned


def _hashtag_variants(query: str) -> list[str]:
    base = _normalize_hashtag(query)
    if not base:
        return []

    variants = [base]
    if len(base) >= 5:
        if base.endswith("s") and len(base) > 6:
            variants.append(base[:-1])
        else:
            variants.append(f"{base}s")
    if base.endswith("es") and len(base) > 8:
        variants.append(base[:-2])

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in variants:
        normalized = _normalize_hashtag(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _extract_hashtag_candidates(payload: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    def _push(node: Any) -> None:
        if not isinstance(node, dict):
            return
        name = str(node.get("name") or "").strip()
        if not name:
            return
        media_count = node.get("media_count")
        if isinstance(media_count, str):
            media_count = _parse_compact_number(media_count)
        if not isinstance(media_count, int):
            media_count = 0
        candidates.append({"name": _normalize_hashtag(name), "media_count": max(0, media_count)})

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("hashtag"), dict):
                _push(node.get("hashtag"))
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = str(candidate.get("name") or "")
        if not key:
            continue
        previous = deduped.get(key)
        if not previous or int(candidate.get("media_count") or 0) > int(previous.get("media_count") or 0):
            deduped[key] = candidate
    return list(deduped.values())


async def _precheck_hashtag_target(context, page, query: str) -> dict[str, Any]:
    variants = _hashtag_variants(query)
    if not variants:
        return {
            "state": "not_found",
            "selected": "",
            "posts_seen": 0,
            "attempts": [],
            "suggestions": [],
            "open_mode": "direct",
        }

    attempts: list[dict[str, Any]] = []
    found_in_search = False
    for index, variant in enumerate(variants, start=1):
        target_url = f"https://www.instagram.com/explore/tags/{variant}/"
        update_scraper_status("running", 0, 0, f"Validando hashtag #{variant} ({index}/{len(variants)})...")
        search_media_count = 0
        used_search_flow = False
        try:
            topsearch_url = f"https://www.instagram.com/web/search/topsearch/?context=blended&query={quote(variant)}"
            response = await context.request.get(topsearch_url)
            if response.ok:
                payload = await response.json()
                candidates = _extract_hashtag_candidates(payload)
                exact = next((item for item in candidates if item.get("name") == variant), None)
                if exact:
                    found_in_search = True
                    search_media_count = int(exact.get("media_count") or 0)
        except Exception:
            pass

        await page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
        diag = await _wait_for_hashtag_grid(page, variant, rounds=4)
        posts_seen = int(diag.get("total_post_links") or 0)

        if posts_seen < MIN_HASHTAG_POSTS_FOR_SCRAPE and search_media_count > 0:
            try:
                opened = await _open_hashtag_via_search(page, variant)
                if opened:
                    used_search_flow = True
                    diag = await _wait_for_hashtag_grid(page, variant, rounds=4)
                    posts_seen = max(posts_seen, int(diag.get("total_post_links") or 0))
            except Exception:
                pass

        attempts.append({
            "tag": variant,
            "posts_seen": posts_seen,
            "search_media_count": search_media_count,
            "used_search_flow": used_search_flow,
        })
        if posts_seen >= MIN_HASHTAG_POSTS_FOR_SCRAPE:
            return {
                "state": "valid",
                "selected": variant,
                "posts_seen": posts_seen,
                "attempts": attempts,
                "suggestions": [],
                "open_mode": "search" if used_search_flow else "direct",
            }
    best = max(attempts, key=lambda item: int(item.get("posts_seen") or 0), default={"tag": variants[0], "posts_seen": 0})
    best_tag = str(best.get("tag") or variants[0])
    best_posts = int(best.get("posts_seen") or 0)
    if best_posts > 0:
        return {
            "state": "too_narrow",
            "selected": best_tag,
            "posts_seen": best_posts,
            "attempts": attempts,
            "suggestions": [variant for variant in variants if variant != best_tag][:2],
            "open_mode": "direct",
        }

    if found_in_search:
        return {
            "state": "found_no_posts",
            "selected": best_tag,
            "posts_seen": best_posts,
            "attempts": attempts,
            "suggestions": [variant for variant in variants if variant != best_tag][:2],
            "open_mode": "search",
        }

    return {
        "state": "not_found",
        "selected": variants[0],
        "posts_seen": 0,
        "attempts": attempts,
        "suggestions": variants[1:3],
        "open_mode": "direct",
    }

def update_scraper_status(status: str, progress: int, total: int, message: str, meta: Dict[str, Any] | None = None):
    """Escribe el progreso a un archivo JSON para que Streamlit lo lea en vivo."""
    data = {
        "status": status,
        "progress": progress,
        "total": total,
        "message": message,
        "timestamp": time.time() if "time" in sys.modules else None,
        "meta": meta or {},
    }
    STATUS_FILE.write_text(json.dumps(data), encoding="utf-8")
    hook = SCRAPER_STATUS_HOOK.get()
    if callable(hook):
        hook(data)


def _scraper_checkpoint_from_status(data: Dict[str, Any]) -> str:
    meta = data.get("meta") or {}
    source = str(meta.get("source") or "scraper")
    status = str(data.get("status") or "running")
    progress = int(data.get("progress") or 0)
    total = max(1, int(data.get("total") or 1))
    return f"{source}:{status}:{progress}/{total}"[:220]


def _install_runtime_status_hook(job_ctx, total: int):
    safe_total = max(1, int(total) or 1)

    def _hook(data: Dict[str, Any]) -> None:
        progress = int(data.get("progress") or 0)
        fraction = max(0.0, min(1.0, progress / safe_total))
        job_ctx.update_progress(fraction, checkpoint=_scraper_checkpoint_from_status(data))

    return SCRAPER_STATUS_HOOK.set(_hook)


def enqueue_scraper_job(
    target_type: str,
    query: str,
    limit: int = 50,
    username: str | None = None,
    filters: dict[str, Any] | None = None,
    campaign_id: str | None = None,
    workspace_id: int = 1,
    runtime=None,
):
    job_runtime = runtime or get_job_runtime()
    idempotency_key = job_runtime.generate_idempotency_key(
        "scrape",
        str(workspace_id),
        str(target_type),
        str(query).strip().lower(),
        str(limit),
        str(username or ""),
        str(campaign_id or ""),
        json.dumps(filters or {}, sort_keys=True, ensure_ascii=True),
    )
    return job_runtime.create_job(
        job_id=f"scrape_{uuid.uuid4().hex[:12]}",
        job_type=JobType.SCRAPE_LEADS.value,
        workspace_id=int(workspace_id),
        payload={
            "target_type": target_type,
            "query": query,
            "limit": int(limit),
            "username": username,
            "filters": filters or {},
            "campaign_id": campaign_id,
        },
        idempotency_key=idempotency_key,
    )


async def resume_scraper_job(job_id: str, runtime=None):
    job_runtime = runtime or get_job_runtime()
    job = job_runtime.get_job(job_id)
    if not job:
        raise RuntimeError(f"Scraper job {job_id} no encontrado")
    payload = job.payload or {}
    if isinstance(payload, str):
        payload = json.loads(payload or "{}")
    return await run_scraper(
        str(payload.get("target_type") or ""),
        str(payload.get("query") or ""),
        int(payload.get("limit") or 50),
        username=payload.get("username"),
        filters=payload.get("filters") or {},
        campaign_id=payload.get("campaign_id"),
        job_id=job_id,
        workspace_id=int(job.workspace_id or 1),
    )

# Filtros de Calidad: Leads B2B / High Ticket
TARGET_KEYWORDS = [
    "ceo", "founder", "owner", "dueño", "fundador", "director", "manager",
    "agency", "agencia", "coach", "consultant", "consultor", "marketing",
    "b2b", "ventas", "sales", "creator", "creador", "emprendedor", "entrepreneur",
    "broker", "real estate", "realtor", "inmobiliaria", "inmobiliario", "asesor inmobiliario",
    "agente inmobiliario", "propiedades", "bienes raices", "realty", "luxury real estate"
]

OFFTOPIC_STRONG_TERMS = [
    "noticias", "news", "diario", "periodico", "periodismo", "portal", "radio", "television", "tv",
    "memes", "humor", "farandula", "chismes", "viral", "futbol", "deportes", "fan", "fanpage", "club", "racing", "boca", "river"
]

EXCLUDE_KEYWORDS = [
    "onlyfans", "spam", "bot", "crypto", "forex", "trading", "18+"
]


def _extract_metric(user: dict[str, Any], *paths: tuple[str, ...]) -> int:
    for path in paths:
        node: Any = user
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, int):
            return node
    return 0


def _normalize_text(value: str) -> str:
    lowered = value.lower()
    lowered = lowered.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    return lowered


# Geographic abbreviations for compound hashtag splitting
_GEO_ABBREVS: dict[str, list[str]] = {
    "bsas": ["buenos aires", "bsas"],
    "buenosaires": ["buenos aires"],
    "caba": ["capital federal", "caba", "buenos aires"],
    "cdmx": ["ciudad de mexico", "cdmx", "mexico"],
    "ciudaddemexico": ["ciudad de mexico", "cdmx", "mexico"],
    "mexico": ["mexico", "ciudad de mexico", "cdmx"],
    "arg": ["argentina"],
    "argentina": ["argentina"],
    "rosario": ["rosario"],
    "cordoba": ["cordoba"],
    "mendoza": ["mendoza"],
    "miami": ["miami"],
    "bogota": ["bogota"],
    "lima": ["lima"],
    "santiago": ["santiago"],
    "medellin": ["medellin"],
    "montevideo": ["montevideo"],
}

# Domain-specific semantic expansions
_DOMAIN_TERMS: dict[str, list[str]] = {
    "constructora": ["constructora", "constructoras", "construccion", "obra", "obras", "edificio", "arquitectura", "ingeniero", "ingenieria", "desarrollo inmobiliario", "proyecto"],
    "inmobili": ["inmobiliaria", "inmobiliario", "broker", "propiedades", "real estate", "realtor", "bienes raices"],
    "broker": ["broker", "brokers", "realtor", "realtors", "asesor", "asesores", "agente", "agentes", "broker inmobiliario", "asesor inmobiliario", "agente inmobiliario", "real estate", "propiedades"],
    "estetica": ["estetica", "esteticas", "belleza", "dermatologia", "skincare", "cosmetologia", "tratamiento facial", "clinica estetica"],
    "odontolog": ["odontologo", "odontologia", "dental", "dentista", "clinica dental", "ortodoncia"],
    "abogad": ["abogado", "abogados", "abogada", "estudio juridico", "derecho", "legal", "bufete"],
    "contador": ["contador", "contadora", "contadores", "contabilidad", "estudio contable", "impuestos"],
    "arquitect": ["arquitecto", "arquitecta", "arquitectura", "estudio de arquitectura", "diseno", "proyecto"],
    "gimnasio": ["gimnasio", "gym", "fitness", "entrenamiento", "crossfit", "personal trainer"],
    "restaurant": ["restaurante", "restaurant", "gastronomia", "chef", "cocina", "comida"],
}


def _split_compound_hashtag(normalized: str) -> list[str]:
    """Split a compound hashtag like 'constructorasbsas' into meaningful components."""
    parts: list[str] = []
    remaining = normalized

    # Try to find geographic suffixes first (greedy, longest match)
    for geo in sorted(_GEO_ABBREVS.keys(), key=len, reverse=True):
        if remaining.endswith(geo) and len(remaining) > len(geo):
            domain_part = remaining[:-len(geo)]
            if len(domain_part) >= 3:
                parts.append(domain_part)
                parts.extend(_GEO_ABBREVS[geo])
                remaining = ""
                break

    # If no geo suffix found, try geo prefixes
    if remaining:
        for geo in sorted(_GEO_ABBREVS.keys(), key=len, reverse=True):
            if remaining.startswith(geo) and len(remaining) > len(geo):
                domain_part = remaining[len(geo):]
                if len(domain_part) >= 3:
                    parts.extend(_GEO_ABBREVS[geo])
                    parts.append(domain_part)
                    remaining = ""
                    break

    if remaining:
        parts.append(remaining)

    return parts


def _source_tokens_split(source_value: str) -> tuple[list[str], list[str]]:
    """Return (domain_tokens, geo_tokens) from a source hashtag/query.

    Domain tokens indicate niche relevance (constructora, construccion, obra, ...).
    Geo tokens indicate location only (buenos aires, bsas, ...) and must NOT
    be used to bypass niche filtering.
    """
    normalized = _normalize_text(source_value)
    tokens = re.findall(r"[a-z0-9]+", normalized)
    domain: list[str] = []
    geo: list[str] = []

    # Collect all known geo terms
    all_geo_terms: set[str] = set()
    for geo_key, geo_expansions in _GEO_ABBREVS.items():
        all_geo_terms.add(geo_key)
        for g in geo_expansions:
            all_geo_terms.add(g)

    # Process each raw token and also try to split compound words
    all_fragments: list[str] = []
    for token in tokens:
        all_fragments.append(token)
        if len(token) > 6:
            split_parts = _split_compound_hashtag(token)
            if len(split_parts) > 1:
                all_fragments.extend(split_parts)

    for token in all_fragments:
        is_geo = token in all_geo_terms

        if is_geo:
            geo.append(token)
            if token in _GEO_ABBREVS:
                geo.extend(_GEO_ABBREVS[token])
        else:
            domain.append(token)
            # Singular/plural variants
            if token.endswith("s") and len(token) > 5:
                domain.append(token[:-1])
            elif token.endswith("es") and len(token) > 6:
                domain.append(token[:-2])
            elif len(token) >= 4 and not token.endswith("s"):
                domain.append(f"{token}s")

            # Domain semantic expansion
            for domain_key, domain_expansions in _DOMAIN_TERMS.items():
                if domain_key in token:
                    domain.extend(domain_expansions)
                    break

    domain_deduped = list(dict.fromkeys([t for t in domain if len(t) >= 3]))
    geo_deduped = list(dict.fromkeys([t for t in geo if len(t) >= 3]))
    return domain_deduped, geo_deduped


def _source_tokens(source_value: str) -> list[str]:
    """Backwards-compatible: returns all tokens (domain + geo)."""
    domain, geo = _source_tokens_split(source_value)
    combined = domain + geo
    return list(dict.fromkeys(combined))


def _term_variants(term: str) -> list[str]:
    normalized = _normalize_text(term)
    variants = [normalized]
    compact = normalized.replace(" ", "")
    if compact != normalized:
        variants.append(compact)
    if normalized.endswith("s") and len(normalized) > 5:
        variants.append(normalized[:-1])
    else:
        variants.append(f"{normalized}s")
    if normalized.endswith("es") and len(normalized) > 6:
        variants.append(normalized[:-2])
    return list(dict.fromkeys([value for value in variants if len(value) >= 3]))


def _strategy_context_terms(filters: dict[str, Any]) -> tuple[list[str], list[str]]:
    context = filters.get("strategy_context") or {}
    if not isinstance(context, dict):
        return [], []

    include_terms: list[str] = []
    exclude_terms: list[str] = []
    for raw in context.get("include_terms") or []:
        include_terms.extend(_term_variants(str(raw or "")))
    for raw in context.get("exclude_terms") or []:
        exclude_terms.extend(_term_variants(str(raw or "")))

    include_terms = list(dict.fromkeys([term for term in include_terms if len(term) >= 3]))[:24]
    exclude_terms = list(dict.fromkeys([term for term in exclude_terms if len(term) >= 3]))[:24]
    return include_terms, exclude_terms


def _normalize_context_values(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        term = _normalize_text(str(raw or "").strip())
        if len(term) < 3 or term in seen:
            continue
        seen.add(term)
        normalized.append(term)
    return normalized[:24]


def _count_term_hits(profile_text: str, terms: list[str]) -> int:
    hits = 0
    for term in terms:
        if term and term in profile_text:
            hits += 1
    return hits


def _extract_json_dict(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _gemini_niche_decision(user: dict[str, Any], filters: dict[str, Any], source_value: str) -> tuple[bool, str] | None:
    if not GOOGLE_API_KEY or google_genai is None or google_genai_types is None:
        return None

    context = filters.get("strategy_context") or {}
    intent_summary = ""
    include_terms = []
    exclude_terms = []
    
    if isinstance(context, dict):
        intent_summary = str(context.get("intent_summary") or "").strip()
        include_terms = _normalize_context_values(context.get("include_terms") or [])
        exclude_terms = _normalize_context_values(context.get("exclude_terms") or [])
        
    if not intent_summary and not include_terms:
        intent_summary = f"Perfiles estrictamente relacionados comercial o profesionalmente con: {source_value}. Rechazar futbol, deportes, memes, farandula, o perfiles personales sin relacion."

    profile_payload = {
        "username": str(user.get("username") or "").strip(),
        "full_name": str(user.get("full_name") or "").strip(),
        "bio": str(user.get("biography") or "").strip(),
        "source": source_value,
        "followers": int(_extract_metric(user, ("follower_count",), ("edge_followed_by", "count"))),
        "posts": int(_extract_metric(user, ("media_count",), ("edge_owner_to_timeline_media", "count"))),
        "intent_summary": intent_summary,
        "include_terms": include_terms,
        "exclude_terms": exclude_terms,
    }
    cache_key = json.dumps(profile_payload, ensure_ascii=True, sort_keys=True)
    if cache_key in GEMINI_NICHE_CACHE:
        return GEMINI_NICHE_CACHE[cache_key]

    system_prompt = """
    Eres un clasificador de relevancia de nicho para leads de Instagram.
    Debes decidir si el perfil pertenece realmente al nicho pedido por el usuario.

    Reglas:
    - Acepta solo si el perfil parece pertenecer al nicho principal pedido.
    - Rechaza cuentas adyacentes, medios, tiendas o rubros vecinos si no encajan claramente.
    - Basa la decision en username, full_name y bio.
    - Devuelve JSON exacto: {"accept": true|false, "reason": "breve"}
    """

    try:
        client = google_genai.Client(api_key=GOOGLE_API_KEY)
        response = client.models.generate_content(
            model=os.getenv("GOOGLE_FLASH_MODEL", "gemini-3-flash"),
            contents=json.dumps(profile_payload, ensure_ascii=False),
            config=google_genai_types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        parsed = _extract_json_dict(getattr(response, "text", "") or "")
        decision = bool(parsed.get("accept"))
        reason = str(parsed.get("reason") or "Clasificacion Gemini").strip()[:120]
        GEMINI_NICHE_CACHE[cache_key] = (decision, reason)
        return decision, reason
    except Exception:
        return None


def _coherence_mismatch(profile_text: str, source_tokens: list[str], has_keyword: bool, source_match: bool) -> bool:
    if has_keyword or source_match:
        return False

    token_hits = 0
    for token in source_tokens:
        if token and token in profile_text:
            token_hits += 1
            if token_hits >= 1:
                return False

    mismatch_hits = 0
    for term in OFFTOPIC_STRONG_TERMS:
        if term in profile_text:
            mismatch_hits += 1
            
    if mismatch_hits >= 1:
        return True
        
    return True


def _context_niche_mismatch(profile_text: str, include_terms: list[str], exclude_terms: list[str]) -> bool:
    if not include_terms:
        return False
    positive_hits = _count_term_hits(profile_text, include_terms)
    negative_hits = _count_term_hits(profile_text, exclude_terms)
    if positive_hits >= 1:
        return False
    if negative_hits >= 1:
        return True
    # No positive NOR negative signals: DO NOT auto-reject.
    # Let the profile pass; other filters (coherence, Gemini) can still catch it.
    # Before this fix, we returned True here, which killed most valid leads.
    return False


def _parse_compact_number(value: str) -> int:
    raw = str(value or "").strip().lower().replace(" ", "")
    if not raw:
        return 0

    raw = raw.replace("mil", "k").replace("millon", "m").replace("millones", "m")

    multiplier = 1
    if raw.endswith("k"):
        multiplier = 1000
        raw = raw[:-1]
    elif raw.endswith("m"):
        multiplier = 1000000
        raw = raw[:-1]

    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "." in raw:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
            raw = raw.replace(".", "")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", raw):
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(",", ".")

    try:
        return int(float(raw) * multiplier)
    except Exception:
        return 0


async def _extract_counts_from_profile_header(page) -> tuple[int, int]:
    try:
        items = await page.locator("main header li").all_inner_texts()
    except Exception:
        items = []

    followers = 0
    posts = 0
    for text in items:
        normalized = str(text or "").lower().strip()
        number_match = re.search(r"[\d.,]+\s*[kKmM]?", normalized)
        if not number_match:
            continue
        value = _parse_compact_number(number_match.group(0))
        if any(keyword in normalized for keyword in ["followers", "seguidores", "seguidor"]):
            followers = max(followers, value)
        if any(keyword in normalized for keyword in ["posts", "post", "publicaciones", "publicacion"]):
            posts = max(posts, value)

    return followers, posts


async def _extract_profile_snapshot(page, username: str) -> dict[str, Any]:
    await page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded")
    await _humanized_wait(1.4, 3.1, f"profile snapshot settle @{username}")

    og_title = await page.evaluate(
        """() => document.querySelector('meta[property="og:title"]')?.getAttribute('content') || ''"""
    )
    og_description = await page.evaluate(
        """() => document.querySelector('meta[property="og:description"]')?.getAttribute('content') || ''"""
    )
    title = await page.title()

    followers_match = re.search(r"([\d.,kKmM]+)\s+(followers?|seguidores?)", og_description, flags=re.IGNORECASE)
    posts_match = re.search(r"([\d.,kKmM]+)\s+(posts?|publicaciones?)", og_description, flags=re.IGNORECASE)

    followers_count = _parse_compact_number(followers_match.group(1)) if followers_match else 0
    posts_count = _parse_compact_number(posts_match.group(1)) if posts_match else 0

    if followers_count == 0 or posts_count == 0:
        header_followers, header_posts = await _extract_counts_from_profile_header(page)
        if followers_count == 0:
            followers_count = header_followers
        if posts_count == 0:
            posts_count = header_posts

    full_name = ""
    title_source = og_title or title
    if "(@" in title_source:
        full_name = title_source.split("(@", 1)[0].strip()

    # Private account detection: multiple signals
    is_private = False
    og_desc_lower = og_description.lower()
    if "privada" in og_desc_lower or "private" in og_desc_lower:
        is_private = True
    if not is_private:
        try:
            body_text = await page.evaluate(
                """() => document.body?.innerText?.substring(0, 3000) || ''"""
            )
            body_lower = body_text.lower()
            if "this account is private" in body_lower or "esta cuenta es privada" in body_lower:
                is_private = True
        except Exception as exc:
            logger.debug("No pude detectar privacidad leyendo body de @%s: %s", username, exc)
    # If og:description is very short/empty AND posts_count is 0, likely private
    if not is_private and len(og_description.strip()) < 10 and posts_count == 0:
        is_private = True

    is_following = False
    try:
        is_following = bool(await page.evaluate(
            """() => {
               const btns = Array.from(document.querySelectorAll('header button, header div[role="button"]'));
               return btns.some(b => {
                 const text = (b.textContent || '').trim().toLowerCase();
                 return ['following', 'siguiendo', 'requested', 'pendiente'].includes(text);
               });
            }"""
        ))
    except Exception as exc:
        logger.debug("No pude chequear is_following para @%s: %s", username, exc)

    return {
        "username": username,
        "full_name": full_name,
        "biography": og_description,
        "follower_count": followers_count,
        "media_count": posts_count,
        "is_private": is_private,
        "is_following": is_following,
    }


async def _extract_post_author_username(page, own_username: str) -> str | None:
    candidates = await page.evaluate(
        """
        () => Array.from(document.querySelectorAll("a[href^='/']"))
          .map((el, index) => ({
            href: el.getAttribute('href') || '',
            text: (el.textContent || '').trim(),
            index,
          }))
        """
    )

    if not isinstance(candidates, list):
        return None

    disallowed_roots = {
        "",
        "accounts",
        "about",
        "api",
        "challenge",
        "developer",
        "direct",
        "explore",
        "legal",
        "p",
        "reel",
        "reels",
        "stories",
        "web",
    }

    ranked: dict[str, dict[str, int]] = {}
    for item in candidates:
        href = str((item or {}).get("href") or "")
        if not href.startswith("/") or href.startswith("//"):
            continue

        cleaned = href.split("?", 1)[0].split("#", 1)[0].strip("/")
        segments = [segment for segment in cleaned.split("/") if segment]
        if len(segments) != 1:
            continue

        username = segments[0].lower()
        if username in disallowed_roots or username == (own_username or ""):
            continue

        data = ranked.setdefault(username, {"count": 0, "first_index": int((item or {}).get("index") or 0)})
        data["count"] += 1
        data["first_index"] = min(data["first_index"], int((item or {}).get("index") or 0))

    if not ranked:
        return None

    ordered = sorted(ranked.items(), key=lambda entry: (-entry[1]["count"], entry[1]["first_index"]))
    return ordered[0][0]


async def _collect_post_authors(page, query: str, target_type: str, db: DatabaseManager, extracted_params: dict[str, Any], limit: int, own_username: str) -> None:
    source_url = str(page.url or "")
    post_links: list[str] = []
    seen_links: set[str] = set()
    seen_usernames: set[str] = set()
    max_scrolls = max(8, limit * 4) if target_type == "hashtag" else max(4, limit)
    extracted_params.setdefault("diagnostics", {"posts_seen": 0, "authors_seen": 0, "profile_errors": 0, "api_authors": 0, "grid_click_authors": 0})
    profile_page = await page.context.new_page()

    page_diag = await _collect_hashtag_page_diagnostics(page, query) if target_type == "hashtag" else {}
    if target_type == "hashtag":
        extracted_params.setdefault("diagnostics", {})["page_diag"] = page_diag
        if not bool(page_diag.get("is_hashtag_context")):
            extracted_params.setdefault("rejected", {})["pagina_hashtag_no_verificada"] = extracted_params.setdefault("rejected", {}).get("pagina_hashtag_no_verificada", 0) + 1
            update_scraper_status(
                "running",
                extracted_params["total"],
                limit,
                f"No se verificó la página de hashtag para #{query}.",
                meta={
                    "source": extracted_params["source"],
                    "accepted_count": extracted_params.get("total", 0),
                    "rejected": extracted_params.get("rejected", {}),
                    "posts_seen": 0,
                    "authors_seen": 0,
                    "profile_errors": extracted_params["diagnostics"].get("profile_errors", 0),
                    "page_diagnostics": page_diag,
                },
            )
            return

    # ── Phase 1: Capture post-owner usernames via API interception while scrolling ──
    api_captured_owners: list[dict[str, Any]] = []
    api_captured_usernames: set[str] = set()

    async def _intercept_hashtag_response(response) -> None:
        """Capture post owners from Instagram API responses during scrolling."""
        try:
            url = response.url
            if not any(ep in url for ep in ["graphql/query", "api/v1/tags/", "api/v1/media/", "api/v1/feed/", "web_info", "search"]):
                return
            if response.request.method == "OPTIONS":
                return
            text = await response.text()
            data = json.loads(text)
            owners = _extract_post_owners_from_json(data)
            for owner in owners:
                un = str(owner.get("username") or "").strip().lower()
                if un and un != own_username and un not in api_captured_usernames:
                    api_captured_usernames.add(un)
                    api_captured_owners.append(owner)
        except Exception as exc:
            logger.debug("No pude parsear respuesta interceptada %s: %s", response.url, exc)

    # Register the API interceptor
    page.on("response", lambda resp: asyncio.ensure_future(_intercept_hashtag_response(resp)))

    # Scroll to load posts and trigger API calls
    desired_post_pool = min(180, max(limit * 6, 30))
    for scroll_index in range(max_scrolls):
        hrefs = await _collect_post_links(page)
        for href in hrefs[:60]:
            if href and href not in seen_links:
                seen_links.add(href)
                post_links.append(href)

        extracted_params["diagnostics"]["posts_seen"] = len(post_links)

        if len(post_links) >= desired_post_pool or len(api_captured_owners) >= limit * 3:
            break

        await page.mouse.wheel(0, random.randint(1800, 3200))
        await asyncio.sleep(random.uniform(2, 4))
        update_scraper_status(
            "running",
            extracted_params["total"],
            limit,
            f"Explorando posts de {target_type}:{query} ({len(post_links)} posts, {len(api_captured_owners)} autores via API)",
            meta={
                "source": extracted_params["source"],
                "accepted_count": extracted_params.get("total", 0),
                "rejected": extracted_params.get("rejected", {}),
                "posts_seen": len(post_links),
                "authors_seen": extracted_params["diagnostics"].get("authors_seen", 0),
                "api_authors_captured": len(api_captured_owners),
                "profile_errors": extracted_params["diagnostics"].get("profile_errors", 0),
            },
        )

    if not post_links and not api_captured_owners:
        extracted_params.setdefault("rejected", {})["sin_posts_visibles"] = extracted_params.setdefault("rejected", {}).get("sin_posts_visibles", 0) + 1
        latest_diag = await _collect_hashtag_page_diagnostics(page, query) if target_type == "hashtag" else {}
        extracted_params.setdefault("diagnostics", {})["page_diag"] = latest_diag
        update_scraper_status(
            "running",
            extracted_params["total"],
            limit,
            f"No se detectaron posts visibles para {target_type}:{query}",
            meta={
                "source": extracted_params["source"],
                "accepted_count": extracted_params.get("total", 0),
                "rejected": extracted_params.get("rejected", {}),
                "posts_seen": 0,
                "authors_seen": 0,
                "profile_errors": extracted_params["diagnostics"].get("profile_errors", 0),
                "page_diagnostics": latest_diag,
            },
        )
        return

    logger.info(f"📡 API interceptor captured {len(api_captured_owners)} unique post owners")
    extracted_params["diagnostics"]["api_authors"] = len(api_captured_owners)

    try:
        # ── Phase 2a: Process API-captured owners (fast path, no grid clicking needed) ──
        for owner in api_captured_owners:
            if extracted_params["total"] >= limit:
                break

            candidate_username = str(owner.get("username") or "").strip().lower()
            if not candidate_username or candidate_username in seen_usernames or candidate_username == own_username:
                continue
            seen_usernames.add(candidate_username)
            extracted_params["diagnostics"]["authors_seen"] = len(seen_usernames)

            # Always visit profile page for complete bio data.
            # API owner data often has only username/full_name, missing biography.
            # Without full bio, niche filters produce false rejections.
            try:
                profile = await _extract_profile_snapshot(profile_page, candidate_username)
            except Exception as exc:
                extracted_params["diagnostics"]["profile_errors"] = extracted_params["diagnostics"].get("profile_errors", 0) + 1
                extracted_params.setdefault("rejected", {})["perfil_no_legible"] = extracted_params.setdefault("rejected", {}).get("perfil_no_legible", 0) + 1
                logger.warning("No pude extraer snapshot para @%s via API: %s", candidate_username, exc)
                await _capture_runtime_evidence(profile_page, "profile_snapshot_api", exc, extra={"username": candidate_username, "query": query})
                continue

            is_valid, reason = _is_valid_lead(
                profile,
                own_username,
                target_type,
                query,
                extracted_params.get("filters", {}),
            )
            if not is_valid:
                extracted_params.setdefault("rejected", {})[reason] = extracted_params.setdefault("rejected", {}).get(reason, 0) + 1
                continue

            inserted = db.add_lead(
                username=profile.get("username", candidate_username),
                full_name=profile.get("full_name", ""),
                bio=profile.get("biography", ""),
                source=extracted_params["source"],
                campaign_id=extracted_params.get("campaign_id", ""),
            )
            if inserted:
                extracted_params["total"] += 1
                extracted_params.setdefault("accepted", []).append(candidate_username)
                logger.info(f"✅ Lead via API [{extracted_params['total']}/{limit}]: @{candidate_username}")
            else:
                extracted_params.setdefault("rejected", {})["duplicado"] = extracted_params.setdefault("rejected", {}).get("duplicado", 0) + 1

            await _humanized_wait(0.3, 0.8, f"between API author validations @{candidate_username}")

            update_scraper_status(
                "running",
                extracted_params["total"],
                limit,
                f"Validando autores via API desde {target_type}:{query} ({extracted_params['total']}/{limit})",
                meta={
                    "source": extracted_params["source"],
                    "accepted_count": extracted_params.get("total", 0),
                    "accepted_usernames": extracted_params.get("accepted", []),
                    "rejected": extracted_params.get("rejected", {}),
                    "posts_seen": len(post_links),
                    "authors_seen": extracted_params["diagnostics"].get("authors_seen", 0),
                    "api_authors_captured": len(api_captured_owners),
                    "profile_errors": extracted_params["diagnostics"].get("profile_errors", 0),
                },
            )

        # ── Phase 2b: Grid-click fallback for remaining posts if limit not reached ──
        if extracted_params["total"] < limit and post_links:
            logger.info(f"🖱️ Grid-click fallback: need {limit - extracted_params['total']} more leads, trying {len(post_links)} posts")
            consecutive_post_failures = 0
            for href in list(post_links):
                if extracted_params["total"] >= limit:
                    break

                candidate_username = await _extract_author_via_grid_click(page, href, own_username, source_url)
                if not candidate_username:
                    extracted_params.setdefault("rejected", {})["post_no_legible"] = extracted_params.setdefault("rejected", {}).get("post_no_legible", 0) + 1
                    consecutive_post_failures += 1
                    await asyncio.sleep(_adaptive_cooldown(consecutive_post_failures))
                    if consecutive_post_failures >= 10:
                        logger.info("Grid click fallback: too many failures, stopping")
                        break
                    continue

                consecutive_post_failures = 0
                if candidate_username in seen_usernames:
                    continue
                seen_usernames.add(candidate_username)
                extracted_params["diagnostics"]["authors_seen"] = len(seen_usernames)
                extracted_params["diagnostics"]["grid_click_authors"] = extracted_params["diagnostics"].get("grid_click_authors", 0) + 1

                try:
                    profile = await _extract_profile_snapshot(profile_page, candidate_username)
                except Exception as exc:
                    extracted_params["diagnostics"]["profile_errors"] = extracted_params["diagnostics"].get("profile_errors", 0) + 1
                    extracted_params.setdefault("rejected", {})["perfil_no_legible"] = extracted_params.setdefault("rejected", {}).get("perfil_no_legible", 0) + 1
                    logger.warning("No pude extraer snapshot para @%s via grid click: %s", candidate_username, exc)
                    await _capture_runtime_evidence(profile_page, "profile_snapshot_grid", exc, extra={"username": candidate_username, "query": query, "href": href})
                    continue

                is_valid, reason = _is_valid_lead(
                    profile,
                    own_username,
                    target_type,
                    query,
                    extracted_params.get("filters", {}),
                )
                if not is_valid:
                    extracted_params.setdefault("rejected", {})[reason] = extracted_params.setdefault("rejected", {}).get(reason, 0) + 1
                    continue

                inserted = db.add_lead(
                    username=profile["username"],
                    full_name=profile.get("full_name", ""),
                    bio=profile.get("biography", ""),
                    source=extracted_params["source"],
                    campaign_id=extracted_params.get("campaign_id", ""),
                )
                if inserted:
                    extracted_params["total"] += 1
                    extracted_params.setdefault("accepted", []).append(profile["username"])
                    logger.info(f"✅ Lead via grid [{extracted_params['total']}/{limit}]: @{candidate_username}")
                else:
                    extracted_params.setdefault("rejected", {})["duplicado"] = extracted_params.setdefault("rejected", {}).get("duplicado", 0) + 1

                await _humanized_wait(1.0, 2.0, f"between grid author validations @{candidate_username}")
    finally:
        await profile_page.close()


def _is_valid_lead(user: dict[str, Any], own_username: str, source_type: str, source_value: str, filters: dict[str, Any]) -> tuple[bool, str]:
    username = str(user.get("username") or "").strip().lower()
    bio = _normalize_text(str(user.get("biography") or "").strip())
    full_name = str(user.get("full_name") or "").strip()
    full_name_norm = _normalize_text(full_name)
    username_norm = _normalize_text(username)

    if not username or len(username) < 3:
        return False, "username_invalido"
    if own_username and username == own_username:
        return False, "self_scraping"
    if user.get("is_private"):
        return False, "privada"
    if user.get("is_following"):
        return False, "ya_seguido"
    if any(ex in bio for ex in EXCLUDE_KEYWORDS):
        return False, "keyword_excluida"

    followers = _extract_metric(
        user,
        ("follower_count",),
        ("edge_followed_by", "count"),
    )
    posts = _extract_metric(
        user,
        ("media_count",),
        ("edge_owner_to_timeline_media", "count"),
    )

    source_domain_tokens, source_geo_tokens = _source_tokens_split(source_value)
    source_tokens = source_domain_tokens + source_geo_tokens
    has_keyword = any(kw in bio for kw in TARGET_KEYWORDS)
    source_match = any(token in bio or token in full_name_norm or token in username_norm for token in source_tokens)
    profile_text = " ".join([bio, full_name_norm, username_norm])
    semantic_real_estate_match = any(
        phrase in profile_text
        for phrase in [
            "broker inmobiliario",
            "brokers inmobiliarios",
            "asesor inmobiliario",
            "agente inmobiliario",
            "agentes inmobiliarios",
            "real estate",
            "realtor",
            "propiedades",
            "inmobiliaria",
            "inmobiliario",
        ]
    )
    source_match = source_match or semantic_real_estate_match
    has_identity = bool(full_name or bio)
    configured_min_followers = filters.get("min_followers")
    configured_min_posts = filters.get("min_posts")
    min_followers = int(configured_min_followers) if configured_min_followers is not None else (30 if source_match else MIN_FOLLOWERS)
    min_posts = int(configured_min_posts) if configured_min_posts is not None else (2 if source_match else MIN_POSTS)
    require_identity = bool(filters.get("require_identity", True))
    require_keyword_match = bool(filters.get("require_keyword_match", False))
    require_coherence = bool(filters.get("require_coherence", True))
    followers_mode = str(filters.get("followers_mode") or "strict")
    include_terms, exclude_terms = _strategy_context_terms(filters)
    positive_context_hits = _count_term_hits(profile_text, include_terms)
    negative_context_hits = _count_term_hits(profile_text, exclude_terms)
    # CRITICAL: use ONLY domain tokens for niche checks, not geo tokens.
    # Geo tokens ("buenos aires") match any account from that city.
    # Domain tokens ("constructora", "construccion") indicate actual niche relevance.
    domain_hits = _count_term_hits(profile_text, source_domain_tokens)
    all_source_hits = _count_term_hits(profile_text, source_tokens)

    source_match = source_match or positive_context_hits > 0 or all_source_hits > 0

    if source_type in {"hashtag", "location"}:
        if followers < min_followers:
            return False, "baja_audiencia"
        if posts < min_posts:
            return False, "baja_actividad"
        if require_identity and not has_identity:
            return False, "sin_identidad"
        gemini_checked = False
        gemini_approved = False
        
        if positive_context_hits <= 0 and domain_hits <= 0 and not has_keyword and not source_match:
            gemini_decision = _gemini_niche_decision(user, filters, source_value)
            if gemini_decision is not None:
                gemini_checked = True
                gemini_approved = gemini_decision[0]
                if not gemini_approved:
                    return False, "perfil_fuera_nicho"
                    
        elif include_terms and negative_context_hits > positive_context_hits and domain_hits <= 0:
            gemini_decision = _gemini_niche_decision(user, filters, source_value)
            if gemini_decision is not None:
                gemini_checked = True
                gemini_approved = gemini_decision[0]
                if not gemini_approved:
                    return False, "perfil_fuera_nicho"

        if require_coherence and not gemini_approved and _coherence_mismatch(profile_text, source_domain_tokens, has_keyword, bool(domain_hits > 0)):
            return False, "perfil_fuera_nicho"
        return True, "ok"

    if followers and followers < min_followers and not has_keyword and not source_match:
        return False, "baja_audiencia"
    if posts and posts < min_posts and not has_keyword and not source_match:
        return False, "baja_actividad"
    if require_identity and not has_identity:
        return False, "sin_identidad"
    if require_keyword_match and not has_keyword and not source_match:
        return False, "sin_match_nicho"
    if source_type == "followers" and followers_mode in {"balanced", "expansive"}:
        if not has_identity and followers_mode == "balanced":
            return False, "sin_identidad"
        if not has_keyword and not source_match and followers_mode == "expansive" and followers < max(15, min_followers):
            return False, "sin_senales"
    if not has_keyword and not source_match and not (followers >= min_followers and posts >= min_posts):
        return False, "sin_senales"

    return True, "ok"


async def _handle_response(response, db: DatabaseManager, extracted_count: dict, limit: int, own_username: str):
    """
    Callback que intercepta todas las respuestas de red.
    Busca endpoints de GraphQL o API v1 que contengan usuarios.
    """
    # Evitar procesar si ya llegamos al limite
    if extracted_count["total"] >= limit:
        return

    url = response.url
    # Endpoints comunes donde Instagram devuelve listas de usuarios
    if "graphql/query" in url or "api/v1/friendships/" in url or "api/v1/tags/" in url:
        try:
            # Algunas respuestas CORS (preflight) no tienen body
            if response.request.method == "OPTIONS":
                return
                
            text = await response.text()
            data = json.loads(text)
            users_found = _extract_users_from_json(data)
            
            for user in users_found:
                if extracted_count["total"] >= limit:
                    break
                    
                is_valid, reason = _is_valid_lead(
                    user,
                    own_username,
                    extracted_count.get("target_type", ""),
                    extracted_count.get("query", ""),
                    extracted_count.get("filters", {}),
                )
                if not is_valid:
                    extracted_count.setdefault("rejected", {})[reason] = extracted_count.setdefault("rejected", {}).get(reason, 0) + 1
                    continue
                
                # Insertar en DB
                username = user.get("username", "")
                full_name = user.get("full_name", "")
                bio = user.get("biography", "")
                 
                if username:
                    inserted = db.add_lead(
                        username=username,
                        full_name=full_name,
                        bio=user.get("biography", ""),
                        source=extracted_count["source"],
                        campaign_id=extracted_count.get("campaign_id", ""),
                    )
                    
                    if inserted:
                        extracted_count["total"] += 1
                        extracted_count.setdefault("accepted", []).append(username)
                        logger.info(f"✅ Lead extraído [{extracted_count['total']}/{limit}]: @{username} | Bio: {bio[:30]}...")
                        logger.info(f"   ⭐ Lead validado por filtros de calidad")
                    else:
                        extracted_count.setdefault("rejected", {})["duplicado"] = extracted_count.setdefault("rejected", {}).get("duplicado", 0) + 1

        except Exception as e:
            # Silenciar errores de parseo (muchas requests no son el JSON esperado)
            pass


def _extract_users_from_json(data: dict) -> list:
    """Busca recursivamente objetos de usuario en el JSON de Instagram."""
    users = []
    
    def _search(node):
        if isinstance(node, dict):
            # Formato API v1
            if "username" in node and "pk" in node:
                # Evitar capturar nuestro propio user u objetos incompletos
                if len(node["username"]) > 1:
                    users.append(node)
                    
            # Formato GraphQL (node -> user)
            if "node" in node and isinstance(node["node"], dict) and "username" in node["node"]:
                users.append(node["node"])
                
            for v in node.values():
                _search(v)
        elif isinstance(node, list):
            for item in node:
                _search(item)
                
    _search(data)
    
    # Deduplicar por username iterando la lista
    unique_users = {}
    for u in users:
        un = u.get("username")
        if un and un not in unique_users:
            unique_users[un] = u
            
    return list(unique_users.values())


async def run_scraper(
    target_type: str,
    query: str,
    limit: int = 50,
    username: str | None = None,
    filters: dict[str, Any] | None = None,
    campaign_id: str | None = None,
    job_id: str | None = None,
    worker_id: str | None = None,
    workspace_id: int = 1,
    job_ctx=None,
):
    if job_ctx is not None:
        token = _install_runtime_status_hook(job_ctx, limit)
        try:
            return await _run_scraper_impl(target_type, query, limit, username=username, filters=filters, campaign_id=campaign_id)
        finally:
            SCRAPER_STATUS_HOOK.reset(token)

    if not job_id:
        return await _run_scraper_impl(target_type, query, limit, username=username, filters=filters, campaign_id=campaign_id)

    runtime = get_job_runtime()
    worker = worker_id or f"scraper_{uuid.uuid4().hex[:8]}"
    job = runtime.create_job(
        job_id=job_id,
        job_type=JobType.SCRAPE_LEADS.value,
        workspace_id=int(workspace_id),
        payload={
            "target_type": target_type,
            "query": query,
            "limit": int(limit),
            "username": username,
            "filters": filters or {},
            "campaign_id": campaign_id,
        },
        idempotency_key=runtime.generate_idempotency_key(
            "scrape",
            str(workspace_id),
            str(target_type),
            str(query).strip().lower(),
            str(limit),
            str(username or ""),
            str(campaign_id or ""),
            json.dumps(filters or {}, sort_keys=True, ensure_ascii=True),
        ),
    )
    if job and job.status == "completed":
        return json.loads(job.result or "{}") if job.result else {"accepted_count": 0}

    with managed_job(job_id, worker, runtime) as ctx:
        token = _install_runtime_status_hook(ctx, limit)
        try:
            result = await _run_scraper_impl(target_type, query, limit, username=username, filters=filters, campaign_id=campaign_id)
            ctx.complete(result)
            return result
        finally:
            SCRAPER_STATUS_HOOK.reset(token)


async def _run_scraper_impl(target_type: str, query: str, limit: int = 50, username: str | None = None, filters: dict[str, Any] | None = None, campaign_id: str | None = None):
    """
    Ejecuta el scraper abriendo el browser y navegando al target.
    """
    update_scraper_status("running", 0, limit, "Inicializando entorno y DB...")
    
    logger.info("=" * 50)
    logger.info(f"🕷️ Botardium Scraper — Extrayendo {limit} leads")
    logger.info(f"   Target: {target_type} -> '{query}'")
    logger.info("=" * 50)

    # Get username to prevent auto-aborts
    ig_username = ""
    if PROFILE_PATH.exists():
        try:
            profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            ig_username = profile.get("ig_username", "").lower()
        except Exception as exc:
            logger.warning("No pude leer account_profile.json para auto-abort del scraper: %s", exc)

    db = DatabaseManager()
    browser = None
    context = None
    page = None
    success = False
    last_error = ""

    update_scraper_status("running", 0, limit, "Lanzando navegador furtivo...")
    if username:
        session_tuple = await load_or_create_session(username)
    else:
        session_tuple = await load_or_create_session()

    if not session_tuple:
        raise RuntimeError("No se pudo cargar una sesion valida para el scraper.")

    browser, context, page = session_tuple

    extracted_params = {
        "total": 0,
        "source": f"{target_type}_{query}",
        "target_type": target_type,
        "query": query,
        "filters": filters or {},
        "campaign_id": campaign_id or "",
    }

    if target_type == "followers":
        page.on("response", lambda response: asyncio.ensure_future(
            _handle_response(response, db, extracted_params, limit, ig_username)
        ))

    try:
        try:
            effective_query = query
            hashtag_open_mode = "direct"
            url = ""
            if target_type == "hashtag":
                precheck = await _precheck_hashtag_target(context, page, query)
                attempts = precheck.get("attempts") or []
                attempts_text = ", ".join([
                    f"#{item.get('tag')}({item.get('posts_seen', 0)} visibles/{item.get('search_media_count', 0)} busqueda{' via-search' if item.get('used_search_flow') else ''})"
                    for item in attempts
                ])
                suggestions = [f"#{tag}" for tag in (precheck.get("suggestions") or []) if tag]

                if precheck.get("state") == "not_found":
                    extracted_params.setdefault("rejected", {})["hashtag_no_encontrado"] = extracted_params.setdefault("rejected", {}).get("hashtag_no_encontrado", 0) + 1
                    suggestion_text = f" Probá variantes: {', '.join(suggestions)}." if suggestions else ""
                    message = f"No encontré el hashtag #{query} en resultados de búsqueda.{suggestion_text}"
                    if attempts_text:
                        message = f"{message} Intentos: {attempts_text}."
                    update_scraper_status("error", 0, limit, message, meta={
                        "source": extracted_params["source"],
                        "accepted_count": 0,
                        "rejected": extracted_params.get("rejected", {}),
                    })
                    raise RuntimeError(message)

                if precheck.get("state") == "found_no_posts":
                    extracted_params.setdefault("rejected", {})["hashtag_sin_posts_visibles"] = extracted_params.setdefault("rejected", {}).get("hashtag_sin_posts_visibles", 0) + 1
                    selected = str(precheck.get("selected") or query)
                    suggestion_text = f" Probá variantes: {', '.join(suggestions)}." if suggestions else ""
                    message = f"Hashtag encontrado (#{selected}), pero no pude ver publicaciones en esta sesión.{suggestion_text}"
                    if attempts_text:
                        message = f"{message} Intentos: {attempts_text}."
                    update_scraper_status("error", 0, limit, message, meta={
                        "source": extracted_params["source"],
                        "accepted_count": 0,
                        "rejected": extracted_params.get("rejected", {}),
                    })
                    raise RuntimeError(message)

                if precheck.get("state") == "too_narrow":
                    extracted_params.setdefault("rejected", {})["hashtag_muy_reducido"] = extracted_params.setdefault("rejected", {}).get("hashtag_muy_reducido", 0) + 1
                    selected = str(precheck.get("selected") or query)
                    suggestion_text = f" Probá variantes: {', '.join(suggestions)}." if suggestions else ""
                    message = (
                        f"Hashtag demasiado reducido para scraping util: #{selected} "
                        f"({int(precheck.get('posts_seen') or 0)} posts visibles).{suggestion_text}"
                    )
                    if attempts_text:
                        message = f"{message} Intentos: {attempts_text}."
                    update_scraper_status("error", 0, limit, message, meta={
                        "source": extracted_params["source"],
                        "accepted_count": 0,
                        "rejected": extracted_params.get("rejected", {}),
                    })
                    raise RuntimeError(message)

                effective_query = str(precheck.get("selected") or query)
                hashtag_open_mode = str(precheck.get("open_mode") or "direct")
                extracted_params["source"] = f"hashtag_{effective_query}"
                extracted_params.setdefault("diagnostics", {})["precheck"] = precheck
                if effective_query != _normalize_hashtag(query):
                    update_scraper_status(
                        "running",
                        0,
                        limit,
                        f"Hashtag ajustado automaticamente: #{query} -> #{effective_query}",
                    )
                url = f"https://www.instagram.com/explore/tags/{effective_query}/"
            elif target_type == "followers":
                url = f"https://www.instagram.com/{query}/followers/"
            elif target_type == "location":
                url = "location-search"
            else:
                update_scraper_status("error", 0, limit, f"Target type {target_type} no soportado")
                return

            update_scraper_status("running", 0, limit, f"Navegando a {url}...")
            
            if target_type == "location":
                await _open_location_target(context, page, query)
            elif target_type == "hashtag" and hashtag_open_mode == "search":
                update_scraper_status("running", 0, limit, f"Abriendo #{effective_query} desde búsqueda de hashtags...")
                opened = await _open_hashtag_via_search(page, effective_query)
                if not opened:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            else:
                # Navegacion robusta: networkidle asegura que cargaron APIs
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            
            # Security Check: Auto-Abort
            if ig_username and f"/{ig_username}/" in page.url.lower():
                raise Exception("🚨 AUTO-ABORT: El bot aterrizó en tu propio perfil. Cancelando scraping para proteger tus seguidores de DMs accidentales.")
                
            await _humanized_wait(4.0, 8.0, "post-navigation settle before scraping")

            # En caso de followers, IG requiere abrir el modal manualmente a veces
            if target_type == "followers":
                try:
                    update_scraper_status("running", 0, limit, "Buscando lista de seguidores...")
                    # Click en followers count
                    followers_link = page.locator(f"a[href='/{query}/followers/']").first
                    if await followers_link.is_visible():
                        await followers_link.click()
                        await _humanized_wait(2.2, 4.4, "followers modal settle")
                    else:
                        logger.warning("No se encontro el link de followers. Asegurate de que la cuenta es publica.")
                except Exception as e:
                        logger.warning(f"Error abriendo followers modal: {e}")

            if target_type in {"hashtag", "location"}:
                if target_type == "hashtag":
                    hashtag_diag = await _wait_for_hashtag_grid(page, effective_query, rounds=3)
                    extracted_params.setdefault("diagnostics", {})["page_diag"] = hashtag_diag
                    if not bool(hashtag_diag.get("is_hashtag_context")):
                        extracted_params.setdefault("rejected", {})["pagina_hashtag_no_verificada"] = extracted_params.setdefault("rejected", {}).get("pagina_hashtag_no_verificada", 0) + 1
                        raise RuntimeError(f"No pude verificar la página final del hashtag #{effective_query} en esta sesión.")
                update_scraper_status("running", 0, limit, f"Extrayendo autores de posts para {target_type}:{effective_query}...")
                await _collect_post_authors(page, effective_query, target_type, db, extracted_params, limit, ig_username)
                success = True
            else:
                logger.info("Iniciando scroll profundo para disparar requests a la API...")
                update_scraper_status("running", 0, limit, "Haciendo scroll y capturando leads JSON...")

                # Bucle de scroll hasta alcanzar el límite o agotar intentos
                max_scrolls = limit // 2  # Asumimos ~10-20 usuarios por request
                scrolls = 0
                consecutive_no_new = 0
                last_count = 0

                while extracted_params["total"] < limit and scrolls < max_scrolls:
                    if target_type == "followers":
                        # Scrollear dentro del modal de followers
                        modal = page.locator('div[role="dialog"] >> div[style*="overflow-y"]')
                        try:
                            await modal.evaluate("el => el.scrollTop = el.scrollHeight")
                        except Exception as exc:
                            logger.debug("Fallback scroll dentro del modal de followers: %s", exc)
                            # Fallback scroll
                            await page.mouse.wheel(0, 1000)
                    else:
                        # Scrollear pagina normal (hashtag)
                        await page.mouse.wheel(0, random.randint(1500, 3000))

                    await _humanized_wait(2.0, 5.0, "deep scroll settle")
                    scrolls += 1

                    # Update UI via JSON
                    current_leads = extracted_params["total"]
                    update_scraper_status(
                        "running",
                        current_leads,
                        limit,
                        f"Scrolleando... ({current_leads}/{limit} capturados)",
                        meta={
                            "source": extracted_params["source"],
                            "accepted_count": extracted_params.get("total", 0),
                            "rejected": extracted_params.get("rejected", {}),
                        },
                    )

                    # Check progreso
                    if current_leads == last_count:
                        consecutive_no_new += 1
                        if consecutive_no_new > 5:
                            logger.warning("No se estan cargando mas leads. Fin del scroll.")
                            break
                    else:
                        consecutive_no_new = 0
                        last_count = current_leads

                success = True
        except Exception as e:
            detail = str(e).strip() or repr(e)
            last_error = detail
            logger.exception("Error durante scraping real")
            evidence = await _capture_runtime_evidence(
                page,
                "run_scraper_impl",
                e,
                extra={
                    "source": extracted_params.get("source"),
                    "accepted_count": extracted_params.get("total", 0),
                    "query": query,
                    "target_type": target_type,
                },
            )
            update_scraper_status(
                "error",
                extracted_params["total"],
                limit,
                f"Error: {detail}",
                meta={
                    "source": extracted_params["source"],
                    "accepted_count": extracted_params.get("total", 0),
                    "rejected": extracted_params.get("rejected", {}),
                    "posts_seen": int(extracted_params.get("diagnostics", {}).get("posts_seen", 0)),
                    "authors_seen": int(extracted_params.get("diagnostics", {}).get("authors_seen", 0)),
                    "profile_errors": int(extracted_params.get("diagnostics", {}).get("profile_errors", 0)),
                    "page_diagnostics": extracted_params.get("diagnostics", {}).get("page_diag", {}),
                    "precheck": extracted_params.get("diagnostics", {}).get("precheck", {}),
                    "runtime_evidence": evidence,
                },
            )
            raise
    except Exception as e:
        detail = str(e).strip() or repr(e)
        evidence = await _capture_runtime_evidence(page, "run_scraper_fatal", e, extra={"query": query, "target_type": target_type})
        if not last_error:
            last_error = detail
            update_scraper_status("error", extracted_params["total"], limit, f"Error fatal: {detail}", meta={"runtime_evidence": evidence})
        logger.exception("Scraper abortado por error fatal")
        raise
    finally:
        # DB Sanitization Final
        db.sanitize_leads_source(extracted_params["source"])

        if success:
            logger.info("=" * 50)
            logger.info(f"✅ Scraping finalizado. Leads obtenidos: {extracted_params['total']}/{limit}")
            logger.info("=" * 50)

            update_scraper_status(
                "done",
                extracted_params["total"],
                limit,
                "Scraping finalizado exitosamente. Red de seguridad (Sanitización) aplicada.",
                meta={
                    "source": extracted_params["source"],
                    "accepted_count": extracted_params.get("total", 0),
                    "accepted_usernames": extracted_params.get("accepted", []),
                    "rejected": extracted_params.get("rejected", {}),
                    "posts_seen": int(extracted_params.get("diagnostics", {}).get("posts_seen", 0)),
                    "authors_seen": int(extracted_params.get("diagnostics", {}).get("authors_seen", 0)),
                    "profile_errors": int(extracted_params.get("diagnostics", {}).get("profile_errors", 0)),
                    "page_diagnostics": extracted_params.get("diagnostics", {}).get("page_diag", {}),
                    "precheck": extracted_params.get("diagnostics", {}).get("precheck", {}),
                },
            )
        else:
            logger.error(f"❌ Scraping finalizado con error temprano: {last_error or 'sin detalle'}")

        # Esperar un momento a que terminen de procesar las ultimas requests
        await _humanized_wait(1.5, 2.8, "final scraper drain")
        if browser is not None:
            await browser.close()

    return {
        "accepted_count": int(extracted_params.get("total") or 0),
        "source": extracted_params.get("source"),
        "rejected": extracted_params.get("rejected", {}),
        "campaign_id": campaign_id or "",
        "target_type": target_type,
        "query": query,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Botardium Core Scraper")
    parser.add_argument("--target", choices=["hashtag", "followers", "location"], required=True)
    parser.add_argument("--query", required=True, help="El hashtag (sin #), el username o la location")
    parser.add_argument("--limit", type=int, default=50, help="Cantidad de leads a extraer")
    args = parser.parse_args()

    asyncio.run(run_scraper(args.target, args.query, args.limit))
