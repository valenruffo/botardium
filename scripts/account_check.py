"""
Botardium Core — Account Check (Onboarding Determinante)
==========================================================
Clasifica la cuenta de Instagram y genera un perfil de agresividad
(Account DNA) que todos los scripts de negocio deben consultar.

Consulta: directivas/account_dna_SOP.md
Output: .tmp/account_profile.json

Uso:
    python scripts/account_check.py
"""

import json
import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from scripts.runtime_config import load_bootstrap_env
from scripts.runtime_paths import MEMORIA_PATH, PROFILE_PATH, SOURCE_ROOT, TMP_DIR

# Paths
PROJECT_ROOT = SOURCE_ROOT

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("primebot.onboarding")

load_bootstrap_env()


# --------------------------------------------------------------------------- #
#  Perfiles predefinidos (Account DNA)
# --------------------------------------------------------------------------- #

PROFILES = {
    "personal": {
        "type": "personal",
        "label": "Personal / Agencia (Alta Confianza)",
        "max_dms_per_day": 40,
        "max_follows_per_day": 25,
        "max_likes_per_day": 65,
        "max_comments_per_day": 12,
        "warmup_duration_min": 0,
        "ip_rotation_enabled": False,
        "ip_rotation_every_n_actions": None,
        "action_delay_dm": {"min": 120, "max": 480},      # 2-8 min en segundos
        "typing_delay_ms": {"min": 50, "max": 200},
        "mouse_delay_ms": {"min": 100, "max": 500},
        "dm_block_size": 10,
        "dm_block_pause_min": 60,
        "dm_block_pause_max": 90,
        "action_delay_follow": {"min": 30, "max": 180},    # 30s - 3 min
        "action_delay_like": {"min": 5, "max": 30},        # 5-30s
        "proxy_type": "residential",
        "session_max_hours": 3,
        "session_pause_hours": {"min": 1, "max": 4},
        "operating_hours": {"start": 8, "end": 23},
        "scale_increment_dms": 3,
        "scale_increment_every_days": 3,
        "max_dms_cap": 50,
        "session_warmup_required": False,
    },
    "prospector": {
        "type": "prospector",
        "label": "Nueva / Prospectora",
        "max_dms_per_day": 10,
        "max_follows_per_day": 12,
        "max_likes_per_day": 40,
        "max_comments_per_day": 7,
        "warmup_duration_min": 25,
        "ip_rotation_enabled": True,
        "ip_rotation_every_n_actions": 5,
        "action_delay_dm": {"min": 180, "max": 600},      # 3-10 min en segundos
        "typing_delay_ms": {"min": 50, "max": 200},
        "mouse_delay_ms": {"min": 100, "max": 500},
        "dm_block_size": 10,
        "dm_block_pause_min": 60,
        "dm_block_pause_max": 90,
        "action_delay_follow": {"min": 60, "max": 240},    # 1-4 min
        "action_delay_like": {"min": 10, "max": 45},       # 10-45s
        "proxy_type": "mobile_4g",
        "session_max_hours": 2,
        "session_pause_hours": {"min": 2, "max": 6},
        "operating_hours": {"start": 9, "end": 22},
        "scale_increment_dms": 5,
        "scale_increment_every_days": 3,
        "max_dms_cap": 30,
        "session_warmup_required": True,
    },
    "rehab": {
        "type": "rehab",
        "label": "Rehabilitación / Sensible",
        "max_dms_per_day": 8,
        "max_follows_per_day": 8,
        "max_likes_per_day": 30,
        "max_comments_per_day": 4,
        "warmup_duration_min": 20,
        "ip_rotation_enabled": False,
        "ip_rotation_every_n_actions": None,
        "action_delay_dm": {"min": 240, "max": 720},
        "typing_delay_ms": {"min": 50, "max": 200},
        "mouse_delay_ms": {"min": 100, "max": 500},
        "dm_block_size": 10,
        "dm_block_pause_min": 75,
        "dm_block_pause_max": 90,
        "action_delay_follow": {"min": 90, "max": 300},
        "action_delay_like": {"min": 12, "max": 60},
        "proxy_type": "residential",
        "session_max_hours": 2,
        "session_pause_hours": {"min": 3, "max": 8},
        "operating_hours": {"start": 10, "end": 21},
        "scale_increment_dms": 3,
        "scale_increment_every_days": 3,
        "max_dms_cap": 20,
        "session_warmup_required": True,
    },
}


# --------------------------------------------------------------------------- #
#  Lógica de Onboarding
# --------------------------------------------------------------------------- #

def check_memoria_maestra() -> bool:
    """Verifica que la Memoria Maestra existe y tiene contenido."""
    if not MEMORIA_PATH.exists():
        logger.warning("⚠️  Memoria Maestra no encontrada. Operando con defaults.")
        return False
    size = MEMORIA_PATH.stat().st_size
    logger.info(f"📖 Memoria Maestra consultada ({size} bytes)")
    return True


def get_account_type() -> str:
    """
    Determina el tipo de cuenta. Prioridad:
    1. Variable de entorno ACCOUNT_TYPE
    2. Perfil existente en .tmp/account_profile.json
    3. Default: 'personal'
    """
    # Desde .env
    env_type = os.getenv("ACCOUNT_TYPE", "").strip().lower()
    if env_type in PROFILES:
        logger.info(f"📋 Tipo de cuenta desde .env: {env_type}")
        return env_type

    # Desde perfil existente
    if PROFILE_PATH.exists():
        try:
            existing = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            existing_type = existing.get("type", "")
            if existing_type in PROFILES:
                logger.info(f"📋 Tipo de cuenta desde perfil existente: {existing_type}")
                return existing_type
        except (json.JSONDecodeError, KeyError):
            pass

    # Default
    logger.info("📋 Tipo de cuenta: personal (default)")
    return "personal"


def load_existing_profile() -> dict:
    """Carga el perfil existente para preservar datos de escalado."""
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            pass
    return {}


def calculate_scaled_limits(profile: dict, existing: dict) -> dict:
    """
    Calcula límites escalados según el perfil y días activos.
    basándose en el historial del perfil existente.
    """
    profile_type = str(profile.get("type") or "").lower()
    if profile_type not in {"prospector", "personal", "rehab"}:
        return profile

    # Si hay un perfil existente, revisar si se puede escalar
    days_active = existing.get("days_active", 0)
    current_max_dms = existing.get("max_dms_per_day", profile["max_dms_per_day"])

    increment = int(profile.get("scale_increment_dms", 0) or 0)
    if days_active > 0 and increment > 0:
        scale_every_days = int(profile.get("scale_increment_every_days", 3))
        scale_cycles = days_active // max(scale_every_days, 1)
        new_max = min(
            profile["max_dms_per_day"] + (scale_cycles * increment),
            int(profile.get("max_dms_cap", profile.get("max_dms_per_day", 30))),
        )
        if new_max > current_max_dms:
            logger.info(f"📈 Escalando DMs: {current_max_dms} → {new_max} (día {days_active})")
            profile["max_dms_per_day"] = new_max
        else:
            profile["max_dms_per_day"] = current_max_dms

    return profile


def generate_profile(account_type: str) -> dict:
    """
    Genera el perfil completo de la cuenta con metadatos.

    Args:
        account_type: 'personal' o 'prospector'.

    Returns:
        Diccionario con toda la configuración de seguridad.
    """
    base_profile = PROFILES[account_type].copy()
    existing = load_existing_profile()

    # Calcular escalado para cuentas prospectoras
    profile = calculate_scaled_limits(base_profile, existing)

    # Metadatos
    days_active = existing.get("days_active", 0)
    if existing.get("created_at"):
        profile["created_at"] = existing["created_at"]
    else:
        profile["created_at"] = datetime.now().isoformat()

    profile["updated_at"] = datetime.now().isoformat()
    profile["days_active"] = days_active + 1
    profile["ig_username"] = os.getenv("IG_USERNAME", "unknown")

    # ADB config
    profile["adb"] = {
        "host": os.getenv("ADB_HOST", "127.0.0.1"),
        "port": int(os.getenv("ADB_PORT", "5037")),
        "device": os.getenv("ADB_DEVICE", ""),
    }

    # Proxy config
    profile["proxy_url"] = os.getenv("PROXY_URL", "")

    return profile


def save_profile(profile: dict) -> Path:
    """Guarda el perfil en .tmp/account_profile.json."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"💾 Perfil guardado: {PROFILE_PATH}")
    return PROFILE_PATH


def display_profile(profile: dict):
    """Muestra el perfil generado de forma legible."""
    print()
    print("=" * 60)
    print(f"🧬 ACCOUNT DNA: {profile['label']}")
    print("=" * 60)
    print(f"   Usuario:           @{profile['ig_username']}")
    print(f"   Tipo:              {profile['type']}")
    print(f"   Día activo:        #{profile['days_active']}")
    print()
    print("   📊 Límites diarios:")
    print(f"      DMs:            {profile['max_dms_per_day']}")
    print(f"      Follows:        {profile['max_follows_per_day']}")
    print(f"      Likes:          {profile['max_likes_per_day']}")
    print(f"      Comments:       {profile['max_comments_per_day']}")
    print()
    print("   ⏱️  Tiempos:")
    print(f"      Warmeo:         {profile['warmup_duration_min']} min")
    dm_delay = profile['action_delay_dm']
    print(f"      Delay DMs:      {dm_delay['min']//60}-{dm_delay['max']//60} min")
    print(f"      Sesión máx:     {profile['session_max_hours']}h")
    hrs = profile['operating_hours']
    print(f"      Horario:        {hrs['start']}:00 - {hrs['end']}:00")
    print()
    print("   🔒 Seguridad:")
    ip_status = "✅ ACTIVA" if profile['ip_rotation_enabled'] else "❌ DESACTIVADA"
    print(f"      Rotación IP:    {ip_status}")
    if profile['ip_rotation_enabled']:
        print(f"      Rotar cada:     {profile['ip_rotation_every_n_actions']} acciones")
    print(f"      Tipo proxy:     {profile['proxy_type']}")
    print()
    print("=" * 60)


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #

def main():
    print()
    print("🔧 Botardium Core — Account Check (Onboarding)")
    print("-" * 50)

    # Step 1: Consultar Memoria Maestra
    check_memoria_maestra()

    # Step 2: Determinar tipo de cuenta
    account_type = get_account_type()

    # Step 3: Generar perfil
    profile = generate_profile(account_type)

    # Step 4: Guardar
    save_profile(profile)

    # Step 5: Mostrar
    display_profile(profile)

    return 0


if __name__ == "__main__":
    sys.exit(main())
