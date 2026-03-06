# Memoria Maestra: Botardium (PrimeBot Core)

## Arquitectura del Sistema
El proyecto opera bajo la metodología de **Ingeniería Compuesta**. Se basa en la automatización de Instagram garantizando la humanización y seguridad para evitar baneos.

## Patrones Globales
- **Seguridad:** Uso estricto de `.env`. Aislamiento de sesiones por cuenta.
- **Estructura:** Lógica delegada a scripts en `scripts/`, conocimiento en `directivas/`.

## Skills Instaladas
Se han instalado un total de **38 skills** en el directorio `skills/`, organizadas en:
- **Automatización de Navegación:**
    - `browser-use`: Agentes de navegación LLM.
    - `patchright`: Playwright indetectable (Chromium focus).
- **Control Móvil:**
    - `pure-python-adb`: Automatización Android (ADB nativo en Python).
- **Inteligencia y Evasión:**
    - `fingerprintjs`: Análisis de huellas digitales del navegador.
    - `ddgs`: Metabuscador (Búsquedas DuckDuckGo, Bing, etc.).
- **Marketing y Diseño:**
    - `frontend-design`: Diseño UI/UX premium.
    - `marketingskills (32 sub-skills)`: Copywriting, SEO, Ads, CRO, etc.

## Historial de Cambios
- **2026-03-06:** Inicialización del proyecto y configuración de estructura de directorios.
- **2026-03-06:** Instalación exitosa de las primeras 33 skills de diseño y marketing.
- **2026-03-06:** Instalación de 5 herramientas clave para automatización y evasión de detección (ADB, Browser Use, Patchright, FingerprintJS, DDGS).
