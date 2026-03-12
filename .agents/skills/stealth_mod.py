"""
PrimeBot Core — Stealth Mod
================================
Fingerprint masking consistente por cuenta + behavioral noise.

Diferencia con stealth_engine.py:
  - stealth_engine: LANZA el browser con fingerprint aleatorio por sesión.
  - stealth_mod: FIJA un hardware profile CONSISTENTE por cuenta y lo persiste.
    Instagram sospecha si el mismo usuario aparece con GPU diferente cada vez.

Consulta: directivas/memoria_maestra.md § 4 (Browser Fingerprint)
          directivas/memoria_maestra.md § 5 (Fingerprint inconsistente)
"""

import asyncio
import json
import random
import hashlib
import logging
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional

logger = logging.getLogger("primebot.stealth_mod")

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SESSIONS_DIR = PROJECT_ROOT / ".agents" / "sessions"


# --------------------------------------------------------------------------- #
#  Hardware Profiles — valores reales de dispositivos populares
# --------------------------------------------------------------------------- #

REAL_GPUS = [
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (AMD)", "renderer": "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (Intel)", "renderer": "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"},
    {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Direct3D11 vs_5_0 ps_5_0, D3D11)"},
]

REAL_PLATFORMS = [
    "Win32",
    "Win32",  # peso extra para Windows
    "Win32",
    "MacIntel",
    "Linux x86_64",
]

REAL_FONTS = [
    ["Arial", "Verdana", "Tahoma", "Trebuchet MS", "Times New Roman", "Georgia", "Courier New", "Segoe UI"],
    ["Arial", "Verdana", "Helvetica Neue", "Times New Roman", "Georgia", "Courier New", "Calibri", "Segoe UI"],
    ["Arial", "Verdana", "Tahoma", "Times New Roman", "Georgia", "Segoe UI", "Consolas", "Cambria"],
]

REAL_SCREEN_DEPTHS = [24, 32]
REAL_HARDWARE_CONCURRENCY = [4, 8, 12, 16]
REAL_DEVICE_MEMORY = [4, 8, 16]


@dataclass
class HardwareProfile:
    """Perfil de hardware consistente para una cuenta."""
    viewport_width: int = 1920
    viewport_height: int = 1080
    user_agent: str = ""
    platform: str = "Win32"
    gpu_vendor: str = ""
    gpu_renderer: str = ""
    screen_depth: int = 24
    hardware_concurrency: int = 8
    device_memory: int = 8
    fonts: list = field(default_factory=list)
    canvas_noise_seed: int = 0  # Seed fijo para ruido de canvas

    @classmethod
    def generate(cls, seed: str = "") -> "HardwareProfile":
        """
        Genera un hardware profile determinístico basado en un seed.
        El mismo seed siempre produce el mismo profile → consistencia.
        """
        if seed:
            rng = random.Random(seed)
        else:
            rng = random.Random()

        gpu = rng.choice(REAL_GPUS)

        from skills.stealth_engine import USER_AGENTS, VIEWPORTS

        base_vp = rng.choice(VIEWPORTS)

        return cls(
            viewport_width=base_vp["width"] + rng.randint(-30, 30),
            viewport_height=base_vp["height"] + rng.randint(-20, 20),
            user_agent=rng.choice(USER_AGENTS),
            platform=rng.choice(REAL_PLATFORMS),
            gpu_vendor=gpu["vendor"],
            gpu_renderer=gpu["renderer"],
            screen_depth=rng.choice(REAL_SCREEN_DEPTHS),
            hardware_concurrency=rng.choice(REAL_HARDWARE_CONCURRENCY),
            device_memory=rng.choice(REAL_DEVICE_MEMORY),
            fonts=rng.choice(REAL_FONTS),
            canvas_noise_seed=rng.randint(1, 999999),
        )


def load_or_create_hardware_profile(username: str) -> HardwareProfile:
    """
    Carga el hardware profile para una cuenta. Si no existe, genera uno
    nuevo basado en el username como seed (determinístico) y lo persiste.
    """
    profile_path = SESSIONS_DIR / username / "hardware_profile.json"

    if profile_path.exists():
        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            profile = HardwareProfile(**data)
            logger.info(f"Hardware profile cargado para @{username}")
            return profile
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Error cargando profile, generando nuevo: {e}")

    # Generar nuevo con seed basado en username
    seed = hashlib.sha256(username.encode()).hexdigest()[:16]
    profile = HardwareProfile.generate(seed=seed)

    # Persistir
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        json.dumps(asdict(profile), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"Hardware profile generado y guardado para @{username}")
    logger.info(f"  GPU: {profile.gpu_renderer[:50]}...")
    logger.info(f"  Viewport: {profile.viewport_width}x{profile.viewport_height}")

    return profile


async def apply_fingerprint(context, profile: HardwareProfile):
    """
    Inyecta scripts en el context de Patchright para spoofear
    WebGL, Canvas, AudioContext y navigator properties.

    Args:
        context: BrowserContext de Patchright.
        profile: HardwareProfile con los valores a inyectar.
    """
    fingerprint_script = f"""
    // === PrimeBot Stealth Mod — Fingerprint Override ===

    // WebGL Vendor/Renderer
    const getParameterOrig = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {{
        if (param === 37445) return '{profile.gpu_vendor}';
        if (param === 37446) return '{profile.gpu_renderer}';
        return getParameterOrig.call(this, param);
    }};

    // WebGL2
    if (typeof WebGL2RenderingContext !== 'undefined') {{
        const getParam2Orig = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(param) {{
            if (param === 37445) return '{profile.gpu_vendor}';
            if (param === 37446) return '{profile.gpu_renderer}';
            return getParam2Orig.call(this, param);
        }};
    }}

    // Navigator overrides
    Object.defineProperty(navigator, 'platform', {{get: () => '{profile.platform}'}});
    Object.defineProperty(navigator, 'hardwareConcurrency', {{get: () => {profile.hardware_concurrency}}});
    Object.defineProperty(navigator, 'deviceMemory', {{get: () => {profile.device_memory}}});

    // Screen depth
    Object.defineProperty(screen, 'colorDepth', {{get: () => {profile.screen_depth}}});
    Object.defineProperty(screen, 'pixelDepth', {{get: () => {profile.screen_depth}}});

    // Canvas fingerprint noise (sutil, seed fijo para consistencia)
    const canvasSeed = {profile.canvas_noise_seed};
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {{
        const ctx = this.getContext('2d');
        if (ctx) {{
            const imageData = ctx.getImageData(0, 0, this.width, this.height);
            for (let i = 0; i < imageData.data.length; i += 4) {{
                imageData.data[i] ^= (canvasSeed >> (i % 8)) & 1;
            }}
            ctx.putImageData(imageData, 0, 0);
        }}
        return origToDataURL.apply(this, arguments);
    }};
    """

    await context.add_init_script(fingerprint_script)
    logger.info("Fingerprint masking aplicado al context.")


async def add_behavior_noise(page, duration_seconds: int = 0):
    """
    Agrega "ruido" comportamental: micro-movimientos de mouse,
    scrolls involuntarios y variaciones de focus/blur.

    Si duration_seconds > 0, ejecuta durante ese tiempo.
    Si es 0, ejecuta una sola ráfaga de ruido.

    Args:
        page: Página de Patchright.
        duration_seconds: Duración del ruido continuo.
    """
    import time

    async def _noise_burst():
        """Una ráfaga de ruido (1-3 acciones aleatorias)."""
        actions = random.randint(1, 3)
        for _ in range(actions):
            noise_type = random.choices(
                ["micro_move", "tiny_scroll", "focus_blur", "idle"],
                weights=[35, 25, 15, 25],
                k=1,
            )[0]

            try:
                if noise_type == "micro_move":
                    # Micro-movimiento de mouse (3-15px)
                    dx = random.randint(-15, 15)
                    dy = random.randint(-15, 15)
                    await page.mouse.move(
                        random.randint(200, 1200) + dx,
                        random.randint(200, 700) + dy,
                    )

                elif noise_type == "tiny_scroll":
                    # Scroll involuntario (10-50px)
                    amount = random.randint(10, 50)
                    if random.random() < 0.3:
                        amount = -amount  # Scroll up ocasional
                    await page.mouse.wheel(0, amount)

                elif noise_type == "focus_blur":
                    # Simular que el usuario cambió de pestaña brevemente
                    await page.evaluate("document.hidden")

                else:
                    pass  # Idle — no hacer nada (también es humano)

            except Exception:
                pass  # Silenciar errores de noise

            await asyncio.sleep(random.uniform(0.5, 2.0))

    if duration_seconds <= 0:
        await _noise_burst()
        return

    start = time.time()
    while time.time() - start < duration_seconds:
        await _noise_burst()
        # Pausa entre ráfagas (10-30s para simular periodos de inactividad)
        await asyncio.sleep(random.uniform(10, 30))

    logger.debug(f"Behavior noise completado ({duration_seconds}s)")
