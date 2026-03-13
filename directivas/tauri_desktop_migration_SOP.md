# SOP: Migracion Botardium a app desktop Windows con Tauri

## Objetivo

Empaquetar Botardium como aplicacion de escritorio para Windows (`botardium.exe`) usando `Tauri + Vite + sidecar Python`, de modo que cada operador use su propia IP local y ejecute el producto sin depender de `localhost` manual ni del repo abierto.

## Arquitectura decidida

- Frontend: `botardium-panel/web/` con `Vite + React`.
- Shell desktop: `botardium-panel/web/src-tauri/`.
- Backend local: `scripts/main.py` empaquetado con `PyInstaller` como sidecar `botardium-api-<target>.exe`.
- Persistencia local desktop: `%APPDATA%/Botardium/` para DB, `.tmp`, logs, sesiones y configuracion editable del usuario.

## Regla dura

- No migrar el backend Python a comandos Rust salvo que sea estrictamente necesario.
- No dejar `http://localhost:8000` hardcodeado en componentes React.
- No mezclar rutas del repo con rutas de runtime frozen; todo modulo Python debe resolver una sola raiz operativa en desktop.
- El sidecar debe considerarse no listo hasta responder `/health`.

## Riesgos conocidos

- Tauri puede abrir la UI antes de que el backend sidecar termine de bootear, generando falsos errores de red.
- PyInstaller cambia `PROJECT_ROOT` y rompe accesos a `.tmp`, `database/` o assets si cada script resuelve rutas por su cuenta.
- Si `.env` se lee desde el bundle temporal, la configuracion no persiste entre instalaciones.
- Si el frontend usa URLs absolutas a `localhost`, la app desktop queda acoplada a un puerto fijo y no puede degradar con gracia.

## Solucion definitiva

1. Centralizar `apiBaseUrl` en frontend con fallback consistente para web/dev/desktop.
2. Esperar healthcheck del sidecar desde Tauri antes de considerar la app lista.
3. Introducir un modulo comun de runtime Python para resolver `PROJECT_ROOT`, `APPDATA`, `DB_DIR`, `TMP_DIR` y config persistente.
4. Mantener build reproducible: `python scripts/build_backend.py` + `npm run build` + `npx tauri build`.
5. Documentar cualquier nuevo aprendizaje en `memoria_maestra.md` para evitar regresiones de empaquetado.

## Optimizacion de bundle

- No empaquetar toda la carpeta `.agents/skills/` dentro del sidecar; incluir solo los modulos core realmente usados por runtime (`stealth_engine.py`, `stealth_mod.py`, `adb_manager.py`, `human_interactor.py`, `db_manager.py`).
- Excluir de PyInstaller modulos pesados ajenos al runtime operativo (`torch`, `tensorflow`, `pandas`, `scipy`, `matplotlib`, `jupyter`, etc.) para evitar sidecars gigantes.
- Medir el peso del sidecar y del instalador en cada iteracion; un cambio correcto debe bajar el bundle sin romper `py_compile`, `cargo check` ni `tauri build`.

## Que NO hacer

- No volver a depender de Next.js para runtime desktop.
- No asumir que `sys._MEIPASS` sirve como carpeta de escritura.
- No lanzar el sidecar sin timeout, healthcheck ni logging claro.
- No repartir la configuracion de runtime entre varios scripts con logica distinta.
