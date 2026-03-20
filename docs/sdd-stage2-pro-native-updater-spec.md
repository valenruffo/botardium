# SDD Spec - Stage 2 PRO Updater Nativo (Botardium Desktop)

## Objetivo
Implementar un flujo de actualizacion nativo en Botardium Desktop (Windows NSIS + Tauri v2) que priorice instalacion in-app y elimine la apertura de navegador en el camino principal, manteniendo fallback temporal al endpoint Python existente.

## Alcance
- Plataforma prioritaria: Windows x64 (bundle NSIS).
- Canal primario: updater nativo de Tauri (check, download, install, restart).
- Canal secundario temporal: `GET /api/app/update-status` del backend Python para degradacion controlada.

## Requisitos funcionales

### Usuario
- **RF-U1**: El operador DEBE poder consultar actualizaciones desde UI sin salir de la app.
- **RF-U2**: Si hay version nueva, la UI DEBE mostrar version destino y notas resumidas.
- **RF-U3**: El operador DEBE poder iniciar descarga e instalacion desde un CTA unico "Actualizar ahora".
- **RF-U4**: Durante descarga/instalacion la UI DEBE mostrar progreso y estado legible (buscando, descargando, listo para reiniciar, error).
- **RF-U5**: En fallback, el operador DEBE recibir mensaje claro de degradacion y opcion manual de descarga.

### Sistema
- **RF-S1**: El sistema DEBE usar updater nativo Tauri como primera opcion en desktop.
- **RF-S2**: El sistema DEBE validar metadatos/artefacto firmados antes de habilitar instalacion.
- **RF-S3**: El sistema NO DEBE abrir navegador en el flujo principal exitoso.
- **RF-S4**: Si updater nativo no esta disponible (plugin/config/red/feed), el sistema DEBE conmutar al endpoint Python existente.
- **RF-S5**: El sistema DEBE registrar telemetria local del flujo (`check_ok`, `update_available`, `download_progress`, `install_ok`, `fallback_used`, `error_code`).
- **RF-S6**: El sistema DEBE ser idempotente: multiples clicks no deben lanzar descargas paralelas.

## Escenarios (Gherkin simplificado)

### Happy path
1. **Escenario HP-1 - Update nativo exitoso**  
   GIVEN app desktop en version `vX` y feed firmado con `vY>vX`  
   WHEN operador hace click en "Buscar actualizacion" y luego "Actualizar ahora"  
   THEN la app descarga, valida firma, instala y solicita reinicio sin abrir navegador.

2. **Escenario HP-2 - No hay update**  
   GIVEN app en version mas reciente  
   WHEN operador consulta actualizaciones  
   THEN la UI informa "ya estas en la ultima version" en < 3 s (sin fallback visible).

### Error path
3. **Escenario ER-1 - Firma invalida**  
   GIVEN manifest/artefacto con firma invalida  
   WHEN se intenta instalar  
   THEN la instalacion se aborta, se muestra error de seguridad y NO se instala binario.

4. **Escenario ER-2 - Corte de red durante descarga**  
   GIVEN update disponible y descarga iniciada  
   WHEN la red se interrumpe  
   THEN la UI muestra error recuperable y permite reintento unico sin duplicar procesos.

### Fallback
5. **Escenario FB-1 - Plugin updater no operativo**  
   GIVEN fallo de inicializacion del updater nativo  
   WHEN operador consulta actualizaciones  
   THEN se usa `GET /api/app/update-status` como fallback y se etiqueta "modo compatibilidad".

6. **Escenario FB-2 - Fallback manual**  
   GIVEN fallback activo y `download_url` disponible  
   WHEN operador elige descarga manual  
   THEN se abre URL externa solo en este flujo secundario y se registra `fallback_used=true`.

## Requisitos no funcionales
- **RNF-SEC-1 (firma)**: solo se aceptan updates con firma valida del canal configurado en Tauri; mismatch => hard fail.
- **RNF-ROB-1 (robustez)**: timeout de check <= 8 s; timeout de descarga configurable; reintento controlado (max 1 automatico o manual).
- **RNF-ROB-2 (consistencia)**: estado de update persistido en memoria UI para no romper por refrescos/renders.
- **RNF-UX-1**: mensajes de estado en espanol operador; acciones bloqueadas mientras hay update en curso.
- **RNF-UX-2**: no navegador en camino principal; solo degradacion explicita.
- **RNF-PERF-1**: deteccion inicial de update al abrir app <= 5 s luego de backend ready.
- **RNF-PERF-2**: polling pasivo max cada 15 min (mantener costo de red actual o menor).

## Criterios de aceptacion testeables
- **CA-1**: en desktop con feed valido, click en "Actualizar ahora" completa flujo nativo sin `openExternal`.
- **CA-2**: firma invalida produce rechazo verificable y no cambia version instalada.
- **CA-3**: si updater nativo falla en runtime, `update-status` Python responde y la UI muestra badge de compatibilidad.
- **CA-4**: doble click en CTA de update no crea dos descargas/procesos.
- **CA-5**: al menos 5 eventos de telemetria local quedan registrados por ciclo (check, decision, progreso, resultado, fallback/error).
- **CA-6**: en "sin update" el usuario recibe confirmacion en <= 3 s.
- **CA-7**: el flujo principal no abre navegador; solo el boton manual de fallback puede hacerlo.

## Mapeo explicito a repo
- `botardium-panel/web/src/App.tsx`: reemplazar flujo `openUpdateDownload` por maquina de estados updater nativo + UI de progreso/fallback.
- `botardium-panel/web/src/lib/api.ts`: conservar cliente HTTP para fallback Python y normalizar mensajes de error.
- `botardium-panel/web/src-tauri/src/lib.rs`: registrar plugin updater, exponer comandos/eventos de check/download/install y telemetria local.
- `botardium-panel/web/src-tauri/Cargo.toml`: agregar dependencia de updater plugin Tauri v2.
- `botardium-panel/web/src-tauri/tauri.conf.json`: configurar endpoints de updater, clave publica de firma y estrategia para NSIS.
- `botardium-panel/web/src-tauri/capabilities/default.json`: habilitar permisos requeridos del updater plugin.
- `scripts/main.py`: mantener `GET /api/app/update-status` como fallback temporal (sin romper contrato actual).
- `directivas/local_workspaces_SOP.md`: alinear UX minima de updates (detectar, ofrecer instalador, reinicio controlado).
- `directivas/tauri_desktop_migration_SOP.md`: validar coherencia con boot sidecar/healthcheck y degradacion sin hardcodeos fragiles.

## Fuera de alcance (Stage 2 PRO)
- Soporte Linux/macOS.
- Auto-rollbacks binarios multi-version.
- Cambio de proveedor de releases fuera de GitHub.
