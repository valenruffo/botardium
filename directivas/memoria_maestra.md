# Memoria Maestra: Botardium Core

> **Última actualización:** 2026-03-06
> Este documento es la fuente de verdad del sistema. Todos los scripts DEBEN consultarlo antes de ejecutar acciones.

---

## 1. Arquitectura del Sistema

El proyecto opera bajo **Ingeniería Compuesta**. Cada error alimenta la memoria para que el siguiente ciclo sea más seguro.

```
bot_ig/
├── .agents/skills/     → Skills, Módulos Python core (stealth, ADB, humanización)
├── scripts/   → Lógica de negocio (account_check, warmer, scraper, messenger) 
├── botardium-panel/web/   → Frontend (Next.js 16)
├── directivas/         → SOPs y esta Memoria Maestra
├── database/           → Base de datos SQLite
├── .tmp/               → Datos volátiles (screenshots, profiles, logs)
└── .env                → Secretos (NUNCA commitear)
```

---

## 2. Límites de Seguridad (Anti-Ban)

### 2.1 Acciones por Día

| Acción       | Cuenta Personal | Cuenta Prospectora | NUNCA exceder |
|-------------|:--------------:|:-----------------:|:------------:|
| DMs          | 20-30          | 10 (escalar +5/día) | 50           |
| Follows      | 20-30          | 10-15              | 60           |
| Likes        | 50-80          | 30-50              | 150          |
| Comments     | 10-15          | 5-10               | 30           |
| Story views  | Sin límite     | Sin límite         | —            |

### 2.2 Delays entre Acciones

| Contexto                  | Rango aleatorio   | Distribución  |
|--------------------------|:-----------------:|:-------------:|
| Entre DMs                 | 2-8 min           | Gaussiana     |
| Entre Follows             | 30s - 3 min       | Uniforme      |
| Entre Likes               | 5-30s             | Gaussiana     |
| Scroll de Feed            | 3-15s por post    | Uniforme      |
| Typing (char-by-char)     | 50-200ms/char     | Gaussiana     |
| Mouse movimiento          | 100-500ms         | Bézier curve  |
| Warmeo pre-sesión         | 15-25 min         | —             |

### 2.3 Reglas de Sesión

- **Duración máxima:** 2-3 horas continuas, luego pausa de 1-4 horas.
- **Horarios humanos:** Operar entre 8:00 - 23:00 hora local del perfil.
- **No operar** de 2:00 - 6:00 AM (señal de bot).
- **Warmeo obligatorio:** Antes de cualquier acción de outbound (DM, Follow), navegar Feed/Stories mínimo 15 min.

---

## 3. Señales de Peligro

### 🔴 STOP INMEDIATO (Detener todas las acciones)
- Mensaje "We detected unusual activity from your account"
- CAPTCHA repetido (más de 2 en una sesión)
- "Try Again Later" en cualquier acción
- Bloqueo temporal de DMs/Follows/Likes
- **Acción:** Pausa mínima de 24h. Registrar en esta sección.

### 🟡 REDUCIR (Bajar velocidad 50%)
- Primer CAPTCHA de la sesión
- Latencia inusual en las respuestas de IG
- Cambio en el HTML/CSS de la interfaz (posible actualización)
- **Acción:** Reducir acciones a la mitad, incrementar delays x2.

### 🟢 OPERACIÓN NORMAL
- Feed carga normalmente
- Stories se reproducen sin errores
- DMs se envían sin warnings

---

## 4. Reglas de IP y Fingerprint

### IPs
- **NUNCA** usar IPs de data centers (AWS, GCP, Azure, DigitalOcean).
- **Preferir** IPs residenciales o móviles (4G/5G).
- **SISTEMA HÍBRIDO:** El sistema ahora es Híbrido. Sabe cuándo usar IP Residencial fija (Cuenta Personal) y cuándo rotar IP vía ADB (Cuenta Nueva) para maximizar la supervivencia.
- **Rotación móvil:** Toggle Modo Avión via ADB cada 5 acciones (solo cuentas prospectoras). Verificar cambio real de IP.
- **Cuentas personales:** IP fija residencial. NO rotar (la consistencia genera confianza).

### Browser Fingerprint
- Usar **Patchright** (Playwright parcheado) como único driver.
- Randomizar: viewport (±50px), user-agent (pool rotativo), timezone (match con IP).
- WebGL vendor/renderer: spoofear con valores reales de hardware popular.
- Canvas hash: inyectar ruido sutil para evadir fingerprinting.

---

## 5. Patrones de Baneo Conocidos

| Patrón                          | Riesgo | Mitigación                                    |
|--------------------------------|:------:|-----------------------------------------------|
| Velocidad constante de acciones | Alto   | Delays gaussianos, no uniformes               |
| Mismo mensaje a múltiples Users | Alto   | Templates con spintax + personalización        |
| Login desde múltiples IPs/día   | Alto   | 1 IP por sesión, máximo 2 cambios/día          |
| Acciones sin warmeo previo      | Medio  | Warmeo obligatorio 15-25 min                  |
| Operar en horario nocturno      | Medio  | Restricción de horario 8:00-23:00              |
| Cuenta nueva con alto volumen   | Alto   | Escala progresiva: 10 → 15 → 20 → 25 DMs     |
| Misma resolución/viewport       | Bajo   | Randomizar ±50px en cada sesión               |
| Login programático repetido     | **Crítico** | Sesión persistente via cookies, NUNCA re-login |
| Fingerprint inconsistente       | Alto   | Fijar hardware profile por cuenta, no randomizar GPU cada sesión |

---

## 6. Skills Instaladas

## 6.1 Estructura consolidada del panel

- `botardium-panel/apps/` fue eliminado para simplificar la operacion.
- El frontend vive ahora en `botardium-panel/web/`.
- La logica Python operativa se mantiene fuera del panel, en scripts y modulos de raiz.
- No recrear `botardium-panel/apps/api/`; cualquier backend local debe integrarse desde la raiz o consumirse por HTTP.

### Core (`.agents/skills/`)
- `stealth_engine` — Motor Patchright + fingerprint spoofing
- `stealth_mod` — Fingerprint masking profundo + behavior randomizer
- `adb_manager` — Control ADB + rotación IP
- `human_interactor` — Escritura humana, mouse curvas, warmeo

### Externas (`skills/`)
- `browser-use` — Agentes de navegación LLM
- `patchright` — Repo del driver parcheado
- `pure-python-adb` — Librería ADB nativa Python
- `fingerprintjs` — Análisis de fingerprint
- `ddgs` — Metabuscador
- `frontend-design` — Diseño UI/UX
- `marketingskills (32 sub-skills)` — Copywriting, SEO, CRO, etc.

---

## 7. Historial de Cambios

- **2026-03-06:** Inicialización del proyecto + estructura de directorios.
- **2026-03-06:** Instalación de 38 skills (marketing, automatización, evasión).
- **2026-03-06:** Setup completo: git init, dependencias, smoke test OK.
- **2026-03-06:** Fase 1 — Construcción módulos core y knowledge base anti-ban.
- **2026-03-06:** Fase 2 — Session Engine, Stealth Mod, Core Warmer.

---

## 8. Lecciones Aprendidas (Compound)

### Fase 1: Onboarding Diferenciado
> **Lección crítica:** El Onboarding diferenciado entre cuentas Personales y Nuevas/Prospectoras es la decisión más importante del sistema. Definir mal el perfil de agresividad desde el inicio lleva a baneos irreversibles. El `account_check.py` DEBE ejecutarse antes de cualquier otra acción. Cada cuenta opera con su propio `account_profile.json` que dicta límites, delays y estrategia de IP. **Nunca tratar dos cuentas con el mismo perfil.**

### Fase 1: Sesiones y Login
> **Lección:** El re-login programático es el trigger #1 de detección. Instagram marca como sospechoso cualquier login que no venga de una sesión previa conocida. La solución: login manual una sola vez → persistir cookies/storage → reutilizar en cada ejecución futura.

### Fase 5: Reporte Diario y Auto-Regulación (The Ultimate Compound)
> **Lección:** El sistema debe generar un Reporte Diario automático al cerrar. Este reporte debe comparar los DMs enviados contra los límites de seguridad de la cuenta (20-45 DMs) y sugerir ajustes para el día siguiente en la Memoria Maestra. La auto-regulación es la clave para la supervivencia a largo plazo.

### Fase 6: Frontend Runtime Estable
> **Lección:** Para uso operativo real de Botardium no se debe depender de `next dev` como runtime estable. En Windows, el servidor de desarrollo puede corromper el cache `.next` y servir HTML sin CSS/JS (`Cannot find module './948.js'`, chunks 404, login pelado). Mitigacion compuesta: limpiar `.next`, reconstruir con `next build` y servir con `next start` para sesiones productivas locales. Si vuelve a aparecer HTML pelado, tratarlo como incidente de runtime, no como bug de UI.

---

## 9. Registro de Incidentes

- **2026-03-07 — Frontend runtime degradado:** Next.js en modo `dev` entrego HTML sin estilos ni chunks JS (`Cannot find module './948.js'`, `/_next/static/... 404`). **Causa probable:** cache `.next` corrupto en Windows durante recargas/restarts repetidos. **Accion correctiva:** detener servidor, borrar `.next`, reconstruir y ejecutar `next start` para operacion estable.
- **2026-03-08 — Reestructura de panel consolidada:** Se elimino `botardium-panel/apps/` y el frontend quedo unificado en `botardium-panel/web/`. **Accion correctiva:** actualizar cualquier referencia residual a `apps/web` o `apps/api` y no recrear esa estructura.
- **2026-03-09 — Consola OpenCode corrompida por procesos en segundo plano:** En Windows, lanzar `uvicorn`, `next dev` u otros procesos largos en segundo plano desde la misma terminal puede dejar secuencias ANSI/VT crudas (`[555;...`, prompts corruptos, `digit-argument`) y volver inutilizable la consola. **Causa probable:** stdout/stderr de procesos hijos compartiendo TTY con PowerShell/PSReadLine. **Accion correctiva:** no usar `next dev` como runtime estable para operacion; lanzar servicios desacoplados con salida redirigida a `.tmp/logs/` y preferir `npm run build && npm run start`. Scripts estables: `scripts/start_local_stack.cmd` y `scripts/stop_local_stack.cmd`.
- **2026-03-09 — Borradores de mensajes legacy contaminando CRM:** Cambiar la logica de copy sin limpiar previews persistidos deja mensajes viejos visibles aunque el generador nuevo ya este corregido. **Causa:** `last_message_preview` guardado en SQLite con frases prohibidas como `vi tu perfil desde...`, `me dio contexto tu bio...`, followers o metadata del source. **Accion correctiva:** en startup limpiar previews legacy y devolver el lead a `Pendiente` si todavia no se habia enviado nada; nunca asumir que el dato guardado refleja la ultima version del generador.
- **2026-03-09 — Copy de outreach no debe salir de templates concatenados:** Si el borrador se arma pegando el prompt del operador debajo de una frase fija, el resultado suena artificial y revela la automatizacion. **Accion correctiva:** usar LLM real con prompt de sistema estricto, rationale corto para revision humana y guardrails que bloqueen frases como `hay fit`, `vi tu perfil desde`, `vi tu bio` o metadata literal del scraping.
- **2026-03-09 — Prompting separado por etapa comercial:** Primer contacto y follow-ups no deben compartir exactamente el mismo prompt. **Accion correctiva:** mantener prompts diferenciados para `first_contact`, `follow_up_1` y `follow_up_2`, y permitir regeneracion puntual por lead con IA real antes de enviar.
- **2026-03-09 — Cadencia stealth por perfil de cuenta:** La mensajeria no puede operar con una sola cadencia universal. **Accion correctiva:** `personal` arranca en 20 DMs/dia y escala +5 cada 3 dias hasta 50, sin warmup de sesion obligatorio; `new` arranca en 10 y escala +5 hasta 30 con warmup 15-25 min; `rehab` arranca en 8 y escala +3 hasta 20 con warmup obligatorio y pausas mas conservadoras. Bloques maximos: 10 DMs; pausa post-bloque: 60-90 min.
- **2026-03-09 — Runtime local estable desacoplado del TTY:** Para evitar corrupcion de la terminal de OpenCode, el stack debe arrancar con launchers ocultos (`scripts/run_hidden.vbs`, `scripts/start_local_stack.cmd`) y chequearse via `scripts/healthcheck_local.py`. **Accion correctiva:** nunca reiniciar backend/frontend de operacion desde la consola interactiva; usar healthchecks + logs. Migracion frontend completada a Next.js 16.1.6 con React 19 y ESLint flat config.
- **2026-03-09 — Launcher oculto anterior rompía assets de Next en producción local:** El frontend podia responder HTML `200` pero devolver CSS/chunks con `500`, dejando la UI "pelada" aunque el servidor pareciera vivo. **Causa:** el launcher basado en `Start-Process`/VBS para `next start` introducia un runtime inconsistente en Windows. **Accion correctiva:** reemplazarlo por `scripts/start_local_stack.py` usando `subprocess.Popen` desacoplado con `DETACHED_PROCESS`; validar siempre el asset CSS principal con healthcheck HTTP real, no solo la home.
- **2026-03-09 — UX ambigua entre `Cuentas` y `CRM`:** Si `Cuentas` muestra acciones de calentamiento de sesión como CTA principal, el usuario interpreta que se está "warmapeando leads" desde la vista equivocada. **Accion correctiva:** `Cuentas` debe gestionar solo la cuenta emisora (perfil, salud, límite, calentamiento de cuenta a largo plazo). El calentamiento previo al envío debe vivir en `CRM`, dentro del flujo de mensajes.
- **2026-03-09 — Naming de leads no debe usar nombres de empresa como saludo:** Usar el `full_name` crudo para abrir un DM produce saludos incorrectos tipo empresa/marca (`Hús Realty`, `CLASS PROPIEDADES`). **Accion correctiva:** detectar nombres empresariales o ambiguos y caer a saludo genérico; solo usar nombre propio cuando sea claramente humano.
- **2026-03-10 — Warmup de sesión puede quedar en falso positivo "lanzado":** Responder `queued` sin preflight de sesión hace que el frontend muestre toast verde aunque la tarea falle al iniciar (sesión ausente o error temprano), y el operador percibe que "no hace nada". **Accion correctiva:** validar sesión antes de encolar (`session_exists`), setear estado `running/queued` en DB antes de crear la tarea y revalidar desde frontend que el estado efectivamente pasó a `running`; si no, mostrar error explícito con `last_error`.
- **2026-03-10 — Core warmer no debe tragar errores silenciosos:** Si `run_warmeo` detecta `/accounts/login` o falla internamente pero retorna sin excepción, el backend puede marcar warmup como `ready` aunque no hizo actividad real. **Accion correctiva:** cuando la sesión no está activa lanzar `RuntimeError` y re-propagar excepciones para que `_run_account_warmup` marque `warmup_status=error` con causa real y no reporte éxito falso.
- **2026-03-10 — Warmup lanzado por subprocess debe resolver imports absolutos:** Ejecutar `scripts/core_warmer.py` como proceso independiente rompía imports tipo `scripts.session_manager` (`ModuleNotFoundError`) y el warmup se cortaba a los 1-2 segundos. **Accion correctiva:** inyectar `PROJECT_ROOT` en `sys.path` dentro de `core_warmer.py` y registrar logs por cuenta en `.tmp/logs/warmup_account_{id}.log` para diagnóstico inmediato.
- **2026-03-10 — Secuencia de follow-up debe ser "mensaje siguiente" y no reenvío del mismo borrador:** Si el envío usa siempre `last_message_preview`, al reenviar desde `Primer contacto` puede repetir copy anterior en vez de avanzar a follow-up. **Accion correctiva:** mapear estado actual a variante de envío (`Listo->first_contact`, `Primer contacto->follow_up_1`, `Follow-up 1->follow_up_2`), generar mensaje runtime para esa variante y bloquear envíos automáticos cuando ya está en `Follow-up 2`/`Completado`.
- **2026-03-10 — Scraper real no debe ocultar fallos tempranos ni sobrescribir `error` con `done`:** Si `lead_scraper.run_scraper` captura excepción y hace `pass`, el backend recibe errores vacíos (`Error al iniciar extractor real:`) y el status puede quedar engañoso. **Accion correctiva:** eliminar swallowing de excepciones, propagar traceback, no escribir `done` en `finally` cuando falla, cerrar browser solo si existe, y enriquecer `current_action` de campaña con detalle real (`str/repr` + mensaje de `scraper_status.json`).
- **2026-03-10 — Scraper via FastAPI en Windows debe correr en loop aislado Proactor:** Ejecutar `run_scraper` directamente dentro del loop principal de Uvicorn puede disparar `NotImplementedError()` al iniciar Patchright (subprocess no soportado en loop Selector). **Accion correctiva:** correr scraper en `asyncio.to_thread(...)` con `new_event_loop()` + `WindowsProactorEventLoopPolicy`, manteniendo el polling de `scraper_status.json` en el loop principal para progreso en vivo.
- **2026-03-10 — Hashtags deben validarse antes de scrapear (y con variantes):** Un hashtag sugerido por IA puede no existir o tener volumen inutil (`esteticaargentina`) mientras su variante si existe (`esteticasargentina`). **Accion correctiva:** agregar precheck por source en explore, probar variantes singular/plural, abortar source con motivo explicito (`hashtag_no_encontrado` / `hashtag_muy_reducido`) y mostrar guidance de operador para ajustar hashtags antes de relanzar.
- **2026-03-10 — La UI operativa no debe exponer errores tecnicos crudos:** Mostrar `RuntimeError`, trazas o texto interno en tarjetas confunde y baja confianza operativa. **Accion correctiva:** transformar errores a mensajes humanos antes de renderizar (`cleanOperatorMessage`), usar estado de campana `needs_review` cuando las fuentes no son viables (en vez de `ready`), y presentar eventos con jerarquia visual (titulo + detalle) para mejorar lectura.
- **2026-03-10 — Precheck de hashtag no debe depender solo de `/explore/tags/...`:** En algunas sesiones IG muestra resultados al buscar en pestaña `Hashtags` pero la carga directa del tag devuelve 0 visibles temporalmente. **Accion correctiva:** validar primero contra `web/search/topsearch`, luego contrastar con DOM visible y clasificar `no_encontrado` vs `encontrado_sin_posts`. Tambien preservar diagnosticos (`posts_seen`, `authors_seen`, `profile_errors`) en estado final para evitar lecturas falsas de 0.
- **2026-03-10 — Fallback obligatorio: abrir hashtag desde flujo de búsqueda cuando falle carga directa:** Si el hashtag existe por búsqueda pero la URL directa no muestra posts, la navegación debe intentar `explore/search/keyword` y entrar al tag desde ese resultado. **Accion correctiva:** introducir `open_mode=search` en precheck y reutilizarlo en ejecución para abrir hashtags vía búsqueda antes de extraer autores.
- **2026-03-10 — `require_keyword_match` no debe bloquear hashtags/location:** En exploración por hashtag, exigir match textual estricto de nicho rechaza perfiles válidos que sí cumplen followers/posts/identidad. **Accion correctiva:** forzar `require_keyword_match=False` para `hashtag` y `location` en `_filters_for_source`; dejar la exigencia semántica dura solo para `followers` cuando corresponda.
- **2026-03-10 — Hashtag/location deben validarse por criterios operativos, no por `sin_senales`:** Aunque se quite `require_keyword_match`, una regla residual de señales puede seguir descartando masivamente (`sin_senales`) y provocar 0 leads falsos. **Accion correctiva:** en `_is_valid_lead`, para `hashtag/location` aceptar por mínimos duros (`min_followers`, `min_posts`, `require_identity`) y no bloquear por matching semántico. La UI debe ocultar selectores de "perfil de filtro" y "match de nicho" cuando no aplican al flujo.
- **2026-03-10 — Parseo de audiencia debe soportar formatos locales (`1.234`):** Instagram puede devolver conteos con punto de miles y textos en minúscula; si se parsea como decimal, cuentas de 1k+ caen en `baja_audiencia`. **Accion correctiva:** normalizar parseo locale-aware para `k/m`, separadores de miles y coma decimal; regex case-insensitive para OG; fallback a lectura de `main header li` cuando OG no trae counts confiables.
- **2026-03-10 — `sin_posts_visibles` intermitente requiere verificación de contexto, no solo URL de tag:** Instagram puede dejar la sesión en `explore/search/keyword` mostrando grilla válida de posts del hashtag. Si se exige únicamente `/explore/tags/...`, se generan falsos negativos. **Accion correctiva:** agregar diagnóstico de contexto (`is_tag_url`, `is_search_keyword_url`, `is_hashtag_context`, `selector_counts`) y permitir extracción cuando el contexto de hashtag está verificado aunque no sea URL de tag exacta.
- **2026-03-10 — Regresión de hashtags debe cubrirse con smoke suite dedicada:** Cuando se tocan precheck/navegación/filtros, la validación manual aislada no alcanza. **Accion correctiva:** usar `scripts/smoke_hashtag_suite.py` con 1-3 hashtags de referencia y revisar `.tmp/hashtag_smoke_report.json` en cada iteración. Esto reduce ciclos de "arregla y rompe" y detecta rápido `low_posts_seen` vs `low_accepted`.
- **2026-03-10 — Anti-ruido global sin volver a filtro duro:** Para `hashtag/location`, reactivar match estricto de nicho vuelve a 0 leads. **Accion correctiva:** mantener filtros operativos (followers/posts/identidad) y agregar descarte suave por coherencia (`perfil_fuera_nicho`) solo cuando no hay señales positivas y el perfil tiene señales fuertes de rubro ajeno (ej. medios/noticias/agregadores).
- **2026-03-10 — Anti-ruido debe poder togglearse desde UI:** En nichos con ruido variable, conviene controlar el filtro de coherencia sin tocar código. **Accion correctiva:** exponer `require_coherence` en el panel operativo (default ON) y persistirlo en `campaign.filters`; en backend aplicarlo solo a `hashtag/location` dentro de `_is_valid_lead`.
- **2026-03-10 — MagicBox no debe generar variantes geograficas truncadas:** Las variantes automaticas por quitar `s/es` pueden romper topónimos (`buenosaire`, `buenosair`) y degradar la ruta sugerida. **Accion correctiva:** reemplazar morfologia ciega por reemplazos seguros + alias geograficos reales (`bsas`, `caba`, `baires`) y filtrar variantes sospechosas antes de devolver `sources`.
- **2026-03-11 — Pause/reanudar de campañas debe preservar progreso real:** Cambiar `pause` a `ready` induce CTA incorrecto (`Iniciar`) y barra que parece reiniciarse. **Accion correctiva:** usar estado `paused`, conservar `progress`, mostrar CTA `Reanudar Scraping` y mantener campañas activas arriba con vista colapsable para operabilidad.
- **2026-03-11 — Error al abrir un post individual no debe invalidar toda la fuente:** `Page.goto ERR_HTTP_RESPONSE_CODE_FAILURE` puede ocurrir en posts aislados (borrados/restringidos). **Accion correctiva:** capturar excepción por post, sumar `post_no_legible`, continuar iteración y humanizar mensajes para evitar ruido técnico en UI.
- **2026-03-11 — Las campañas no deben quedar huérfanas en UI tras borrado o reinicio local:** `Message Studio` no puede listar `campaign_id` históricos desde leads si la campaña ya no existe como entidad viva en la sesión. **Accion correctiva:** usar `botStatus.campaigns` como única fuente de campañas seleccionables en filtros/dropdowns, limpiar `campaign_id` de leads al borrar campaña y renombrar la vista a `Campañas` (no `Campañas Activas`).
- **2026-03-11 — Algunos hashtags terminan en `search/keyword` con posts visibles pero apertura individual bloqueada:** En esos casos la grilla existe, pero abrir cada `/p/...` puede terminar en `chrome-error://chromewebdata/` y producir `post_no_legible` masivo. **Accion correctiva:** mantener la page principal estable, usar `detail_page` separada para posts individuales, reintentar apertura y fallback por click en grid. Si aun falla, humanizar el mensaje como bloqueo de apertura de posts, no como ausencia de contenido.
- **2026-03-11 — Fallback por click en grid debe ejecutarse incluso si `locator.click()` falla:** En resultados `search/keyword`, Patchright puede detectar anchors de posts pero fallar al hacer click “accionable”. **Accion correctiva:** si `locator.click()` tira timeout, NO abortar; hacer fallback inmediato a `page.evaluate(...click())` sobre el anchor del post. Esto recupera autores y evita `post_no_legible` masivo.
- **2026-03-11 — Hashtags con `search/keyword` requieren ritmo mas humano por rate-limit:** Si IG deja ver la grilla pero devuelve muchos `post_no_legible`, suele ser bloqueo por demasiadas aperturas seguidas, no falta de contenido. **Accion correctiva:** priorizar modal/grid, ampliar pool de posts y aplicar `adaptive_cooldown` con pausas crecientes tras rachas de fallos para bajar 429 y recuperar mas autores útiles.
- **2026-03-11 — En hashtags, el post no debe abrirse por URL separada como camino principal:** Si la grilla ya existe, navegar a `/p/...` agrega fricción y dispara mas bloqueos. **Accion correctiva:** usar flujo modal-first para leer autor directamente desde la grilla y reservar una página aparte solo para abrir el perfil del autor y leer métricas.
