# Botardium

Botardium es una aplicación para operar automatización y prospección sobre Instagram con una arquitectura híbrida:

- `botardium-panel/web`: interfaz React/Vite y shell desktop con Tauri.
- `scripts/`: backend FastAPI, runtime local, scraping, mensajería, colas y utilidades operativas.
- `tests/`: suite de validación para runtime, auth por workspace, colas, pooling de sesiones, recovery y utilidades.

Este README apunta a ser el documento principal de onboarding para alguien que entra al proyecto y necesita entender rápido qué corre, dónde vive cada cosa y cómo levantarlo sin asumir nada fuera del repo.

## Qué es Botardium

Según el código actual, Botardium combina:

- un panel web/desktop para operar workspaces, cuentas de Instagram, campañas, leads y mensajería;
- un backend local en Python expuesto como API FastAPI;
- automatización ligada a `patchright`, ADB y utilidades internas de stealth empaquetadas como sidecar del desktop.

El backend se presenta como `Botardium Core API` y se describe en `scripts/main.py` como un motor para Patchright, ADB y extracción de leads. La UI también expone funciones de estrategia con IA (`Magic Box`), revisión de updates, autenticación local por workspace y operación de campañas/mensajes.

## Arquitectura De Alto Nivel

```text
React + Vite UI (web)
        |
        | HTTP a http://127.0.0.1:8000
        v
FastAPI monolítico en scripts/main.py
        |
        | usa runtime_paths.py para DB, logs, config, sessions
        v
SQLite + archivos runtime + sesiones + side effects locales
        |
        +--> Patchright / stealth engine / scraping
        +--> ADB / utilidades auxiliares
        +--> Google GenAI + fallbacks locales para funciones de IA

Tauri Desktop
        |
        +--> levanta el frontend
        +--> spawnea el sidecar botardium-api
        +--> espera /health en 127.0.0.1:8000
```

Piezas clave verificadas:

- La UI usa `VITE_API_BASE_URL` o fallback a `http://127.0.0.1:8000`.
- El shell Tauri espera que el backend local responda en `127.0.0.1:8000`.
- `scripts/runtime_paths.py` centraliza DB, `.tmp`, `config`, `sessions`, logs y secretos runtime.
- En desktop empaquetado, el backend Python viaja como binario sidecar `botardium-api`.

## Stack Verificado

### Frontend / Web

| Componente | Versión / estado | Fuente |
|---|---|---|
| React | `19.2.4` instalada (`^19.2.0` en manifest) | `botardium-panel/web/package-lock.json` |
| React DOM | `19.2.4` instalada | `botardium-panel/web/package-lock.json` |
| Vite | `6.4.1` instalada (`^6.3.5` en manifest) | `botardium-panel/web/package-lock.json` |
| TypeScript | `^5` | `botardium-panel/web/package.json` |
| Tailwind CSS | `^3.4.1` | `botardium-panel/web/package.json` |
| ESLint | `9.39.4` instalada (`^9.39.1` en manifest) | `botardium-panel/web/package-lock.json` |
| SWR | `^2.4.1` | `botardium-panel/web/package.json` |
| Tauri JS API | `2.10.1` instalada (`^2.5.0` en manifest) | `botardium-panel/web/package-lock.json` |

### Desktop

| Componente | Versión / estado | Fuente |
|---|---|---|
| Tauri runtime (Rust) | `2.10.3` | `botardium-panel/web/src-tauri/Cargo.lock` |
| Tauri build | `2.5.6` | `botardium-panel/web/src-tauri/Cargo.lock` |
| Tauri CLI | `2.10.1` instalada | `botardium-panel/web/package-lock.json` |
| Rust edition | `2021` | `botardium-panel/web/src-tauri/Cargo.toml` |
| Rust mínimo | `1.77.2` | `botardium-panel/web/src-tauri/Cargo.toml` |
| Bundle desktop | NSIS | `botardium-panel/web/src-tauri/tauri.conf.json` |

### Backend / Runtime

| Componente | Versión / estado | Fuente |
|---|---|---|
| Python | `3.13` en CI/release | `.github/workflows/release-tauri.yml` |
| FastAPI | usado, sin pin | `requirements.txt` + `scripts/main.py` |
| Uvicorn | usado, sin pin | `requirements.txt` |
| Pydantic | usado, sin pin | `requirements.txt` |
| Patchright | usado, sin pin | `requirements.txt` |
| Google GenAI | usado, sin pin | `requirements.txt` + `scripts/main.py` |
| SQLite | runtime principal | `scripts/main.py` |
| bcrypt / pyjwt | auth local | `requirements.txt` |
| ppadb | integración ADB | `requirements.txt` |

Nota importante: `requirements.txt` no está versionado con pins exactos, así que en backend sólo es seguro afirmar dependencias verificadas, no versiones exactas instaladas.

## Módulos Y Features Principales

### UI / Operación

- Login y sesión por workspace.
- Gestión de workspaces y export/import sanitizado.
- Gestión de cuentas de Instagram.
- Warmup de cuentas y relogin.
- Operación de campañas de scraping.
- Gestión de leads y estados masivos.
- Generación y regeneración de borradores de mensajes.
- Cola y ejecución de jobs de mensajería.
- `Magic Box`: estrategia asistida por IA para sugerir fuentes (`hashtag`, `followers`, `location`).
- Chequeo de updates nativo/manual en desktop.

### Backend / Runtime

Rutas visibles en `scripts/main.py` muestran, entre otras, estas áreas:

- `/api/auth/*`: login local y sesión firmada por workspace.
- `/api/workspaces*`: alta, baja, export, import y settings IA.
- `/api/accounts*` y `/api/ig/login`: cuentas, login IG, profile y warmup.
- `/api/bot/*`: inicio, estado y acciones sobre campañas.
- `/api/leads*`: listado, borrado, bulk status y drafts.
- `/api/messages*`: preview, queue, run y control de jobs.
- `/health` y `/health/detailed`: estado operativo y convergencia de paths.

### Infra Runtime / Persistencia

- Resolución centralizada de paths en `scripts/runtime_paths.py`.
- Migración de secretos runtime a `config/runtime_secrets.json`.
- Export/import con omisión de secretos, passwords y material de sesión.
- Backups, snapshots y restore bajo `scripts/backup`, `scripts/recovery` y `scripts/health`.
- Session pooling, job queue, retry utils y observabilidad cubiertos por tests dedicados.

## Estructura Del Proyecto

```text
.
├── README.md
├── requirements.txt
├── botardium-panel/
│   └── web/
│       ├── src/                # React app principal
│       ├── src-tauri/          # shell desktop Tauri + sidecar config
│       ├── package.json
│       └── vite.config.ts
├── scripts/
│   ├── main.py                # backend FastAPI principal
│   ├── runtime_paths.py       # paths runtime y writable root
│   ├── runtime_config.py      # secretos/config sensible runtime
│   ├── build_backend.py       # empaquetado PyInstaller del sidecar
│   ├── start_local_stack.py   # levanta backend + frontend local
│   ├── lead_scraper.py
│   ├── outreach_manager.py
│   ├── session_pool.py
│   ├── job_queue.py
│   ├── backup/
│   ├── recovery/
│   └── health/
├── tests/                     # pytest/unittest sobre runtime y backend
├── directivas/                # SOPs operativos del producto
├── docs/                      # documentación técnica variada
├── .agents/                   # skills y utilidades auxiliares del repo
└── .github/workflows/         # CI liviano y release desktop Windows
```

## Desarrollo Local

### Prerrequisitos razonables según el repo

- Node.js `20` para alinear con CI/release desktop.
- Python `3.13` para alinear con CI/release desktop.
- Rust toolchain para Tauri desktop.
- En Windows, NSIS si vas a empaquetar instaladores.

### Instalación de dependencias

Backend, desde raíz:

```bash
pip install -r requirements.txt
```

Frontend/desktop, desde `botardium-panel/web`:

```bash
npm ci
```

### Correr sólo la web

Desde `botardium-panel/web`:

```bash
npm run dev
```

La UI queda en `http://127.0.0.1:3000`.

### Correr sólo el backend

Desde raíz:

```bash
python -m uvicorn scripts.main:app --host 127.0.0.1 --port 8000
```

El healthcheck base responde en `http://127.0.0.1:8000/health`.

### Correr web + backend como stack local

Desde raíz:

```bash
python scripts/start_local_stack.py
```

O en Windows:

```bat
scripts\start_local_stack.cmd
```

Importante: este launcher hace `npm run build` del frontend antes de levantar la stack. Para iteración diaria sin build completo, suele ser más práctico levantar backend y web por separado.

### Correr el desktop en desarrollo

Desde `botardium-panel/web`:

```bash
npm run tauri:dev
```

Tauri usa estas precondiciones declaradas en `tauri.conf.json`:

- `beforeDevCommand`: `npm run dev:desktop`
- `beforeBuildCommand`: `npm run build:desktop`

Y `dev:desktop` ejecuta:

```bash
npm run backend:build && vite
```

O sea: en modo desktop dev el backend sidecar se recompila antes de abrir la app.

## Comandos Útiles Del Repo

### Web / Desktop

Desde `botardium-panel/web`:

```bash
npm ci
npm run dev
npm run lint
npm run tauri:dev
npm run tauri:build
npm run backend:build
```

### Backend / Operación

Desde raíz:

```bash
python -m uvicorn scripts.main:app --host 127.0.0.1 --port 8000
python scripts/start_local_stack.py
python scripts/healthcheck_local.py
python scripts/smoke_test.py
python scripts/smoke_hashtag_suite.py --hashtags esteticasargentina --limit 8
```

## Testing Y Verificación Reales En Este Repo

No hay un script único de `test` en `botardium-panel/web/package.json`, pero sí existen comandos y suites concretas en uso:

### Backend / Python

Desde raíz:

```bash
python -m pytest tests
```

Suites visibles por tema:

- `tests/test_phase1_wiring.py`
- `tests/test_phase2_auth_scope.py`
- `tests/test_phase3_paths.py`
- `tests/test_phase4_job_integration.py`
- `tests/test_phase5_retry_utils.py`
- `tests/test_phase6_observabilidad.py`
- `tests/test_phase7_job_queue.py`
- `tests/test_phase8_session_pooling.py`
- `tests/test_phase9_disaster_recovery.py`
- `tests/test_runtime_config.py`
- `tests/test_job_runtime.py`

### Frontend / JS puntual

Desde `botardium-panel/web`:

```bash
node --test src/lib/update-check.test.mjs
npm run lint
```

### Verificaciones operativas

- `python scripts/healthcheck_local.py`: consulta frontend/backend local y tamaños de logs.
- `python scripts/smoke_test.py`: chequeo básico de dependencias core.
- `python scripts/smoke_hashtag_suite.py ...`: regresión operativa de scraping por hashtags.

## Notas De Backend Y Runtime

- El backend principal vive en `scripts/main.py` y hoy es un archivo grande que concentra API, auth, DB, campañas, mensajes y parte del runtime.
- En Windows, el backend fuerza `asyncio.WindowsProactorEventLoopPolicy()`.
- `scripts/runtime_paths.py` decide el `WRITABLE_ROOT`:
  - en dev usa el repo;
  - en modo empaquetado usa `%APPDATA%\Botardium`.
- La DB canónica es `database/botardium.db` bajo el writable root, con lógica de migración desde paths legacy.
- Los secretos runtime del workspace se mueven a `config/runtime_secrets.json` y no deben exportarse ni versionarse.
- El desktop sidecar controla la salud/versionado del backend y mata procesos viejos si detecta mismatch de versión.

## Notas De Sistema Operativo

### Windows-first

Windows es el camino principal verificado por el repo actual:

- el release desktop corre en `windows-latest`;
- el empaquetado produce instaladores NSIS;
- `tauri.conf.json` configura NSIS `currentUser` y updater `passive`;
- hay scripts `.cmd` para levantar/detener la stack local;
- el backend tiene compatibilidad explícita con `WindowsProactorEventLoopPolicy`.

### macOS best effort

Hay señales de compatibilidad parcial, pero no de validación completa:

- `Cargo.toml` incluye dependencias para `macos`, `windows` y `linux`;
- el release automatizado del repo no construye macOS;
- las reglas del proyecto aclaran que macOS es experimental y no debe romper el flujo Windows.

Tomalo como soporte best effort, no como plataforma primaria.

## Caveats Actuales

- `requirements.txt` no fija versiones exactas del backend.
- El backend principal está muy concentrado en `scripts/main.py`, lo que eleva costo de cambio y onboarding.
- El repo mezcla código de producto con tooling de agentes/SDD (`.agents/`, `examples/`, parte de `docs/`), así que no toda la documentación raíz describe Botardium producto.
- No existe un `npm test` unificado para frontend; hoy hay verificación puntual con `node --test` y `eslint`.
- `start_local_stack.py` construye frontend antes de levantar la stack, lo cual no es ideal para feedback rápido.
- El pipeline de release desktop automatizado está orientado sólo a Windows.

## Documentación Relacionada

- `docs/runtime-config-migration.md`: manejo de secretos runtime y export/import sanitizado.
- `directivas/`: SOPs operativos del producto.
- `docs/phase9_disaster_recovery_spec.md`: especificación de backup/recovery alineada con módulos existentes bajo `scripts/backup`, `scripts/recovery` y `scripts/health`.

## Punto De Partida Recomendado Para Onboarding

1. Leer este README completo.
2. Revisar `botardium-panel/web/package.json` y `scripts/main.py` para entender entrypoints reales.
3. Levantar backend y web por separado antes de probar Tauri.
4. Correr `python -m pytest tests`, `npm run lint` y `node --test src/lib/update-check.test.mjs` para validar entorno.
5. Recién después, pasar a desktop (`npm run tauri:dev`) o a smoke suites operativas.
