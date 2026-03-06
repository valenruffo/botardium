# Directiva: Instalación de Herramientas de Automatización (SOP)

## Objetivo
Configurar el proyecto con herramientas avanzadas de automatización, navegación y evasión de detección para potenciar a **Botardium**.

## Herramientas a Instalar

### 1. Pure Python ADB (`pure-python-adb`)
- **Fuente:** `https://github.com/Swind/pure-python-adb.git`
- **Uso:** Automatización de dispositivos Android sin necesidad del binario `adb` del sistema (vía Python).

### 2. Browser Use (`browser-use`)
- **Fuente:** `https://github.com/browser-use/browser-use.git`
- **Uso:** Framework para que agentes de IA operen navegadores de forma natural.

### 3. Patchright (`patchright`)
- **Fuente:** `https://github.com/Kaliiiiiiiiii-Vinyzu/patchright.git`
- **Uso:** Versión parcheada de Playwright para evadir sistemas anti-bot (imperceptible).

### 4. FingerprintJS (`fingerprintjs`)
- **Fuente:** `https://github.com/fingerprintjs/fingerprintjs.git`
- **Uso:** Identificación y análisis de huellas digitales del navegador (para entender cómo nos ven).

### 5. DDGS (`ddgs`)
- **Fuente:** `https://github.com/deedy5/ddgs.git`
- **Uso:** Búsquedas en DuckDuckGo para recolección de información sin trackeo.

## Estándar de Almacenamiento
Cualquier herramienta que no traiga un `SKILL.md` nativo deberá ser documentada con uno básico en su raíz para que el Agente sepa cómo invocarla.

## Pasos de Ejecución
1. Clonar repositorios en subcarpetas de `skills/`.
2. Verificar documentación.
3. Actualizar `memoria_maestra.md`.
