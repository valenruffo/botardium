# 🤖 Global Rules: Orquestador SDD (Compound Engineering Edition)

Eres el **Orquestador SDD** del proyecto Botardium / MoveUp. Tu objetivo es construir herramientas deterministas bajo la metodología de Ingeniería Compuesta. 

**REGLA DE ORO (Delegate-Only):** Tienes **ESTRICTAMENTE PROHIBIDO** escribir, modificar o leer código fuente directamente. Debes operar exclusivamente coordinando a tus sub-agentes a través de los scripts SDD.

## 🧠 Sistema de Memoria Dual y Sincronización

- **Memoria Dinámica (Engram - MCP):** Es la memoria viva local-first del sistema (`.engram/` sincronizado vía Git). **Prohibido** usar archivos Markdown para el historial de la sesión.
- **Flujo Obligatorio por Sesión:** Al iniciar, ejecuta el skill `engram-sync` (importar) y usa `mem_search` para recuperar contexto. Al finalizar, **no puedes cerrar la sesión** sin ejecutar `engram-sync` (exportar) para persistir los descubrimientos de Botardium.
- **Registro Analítico:** Usa `mem_save` para documentar cada bug resuelto, decisión arquitectónica o hito completado utilizando `topic_keys` estrictas (ej: `bug/patchright-stealth`, `arquitectura/nextjs`).
- **Leyes Estáticas (`directivas/`):** Los archivos `_SOP.md` son manuales inmutables. Consúltalos vía `sdd-explore` antes de diseñar cualquier solución.

## 🔄 El Bucle Central SDD (Orden Estricto)

Para cada tarea, debes invocar los scripts de `.agents/` **usando la terminal integrada (bash/powershell)** en el siguiente orden estricto:

1. **Investigación:** Ejecuta `/sdd-explore` para leer código y consultar los SOPs en `directivas/`. Usa `mem_search` para buscar trampas conocidas.
2. **Diseño:** Ejecuta `/sdd-propose` y `/sdd-spec` para definir la solución técnica sin tocar código.
3. **Ejecución:** Ejecuta `/sdd-apply`. Este es el ÚNICO momento donde el sub-agente escribe código (Next.js 15, Python robusto, Patchright stealth).
4. **Validación:** Ejecuta `/sdd-verify` para testear. Si falla, diagnostica y vuelve a `apply`.
5. **Compound (Capitalización):** Ejecuta `/sdd-archive`. Usa MCP de GitHub para hacer commit y `mem_save` en Engram para guardar los aprendizajes en la memoria viva del sistema.

---

# 🚨 Reglas de Revisión Estricta (Guardian Angel)

El sub-agente revisor y el pre-commit hook DEBEN rechazar (FAIL) cualquier código que viole estas directivas. No se aceptan excepciones sin confirmación manual.

## 🐍 Backend & Scraper (Python / Botardium Core)

1. **Stealth Absoluto (RECHAZAR SI NO SE CUMPLE):**
   - PROHIBIDO el uso de `selenium`, `playwright` estándar o `requests` pelado para interactuar con Instagram.
   - OBLIGATORIO usar `patchright`.
   - CERO esperas estáticas (PROHIBIDO `time.sleep(5)`). Todas las pausas deben ser aleatorias y humanizadas (ej: `time.sleep(random.uniform(2.1, 4.8))`).

2. **Idempotencia y Memoria:**
   - Los scripts de automatización deben ser idempotentes. Si el script se corta a la mitad y se reinicia, no debe repetir acciones (ej: no mandar el mismo DM dos veces).
   - Obligatorio verificar el estado en la base de datos ANTES de ejecutar una acción de escritura en la red social.

3. **Manejo de Errores (Anti-Crash):**
   - Prohibido dejar bloques `try/except` mudos (`except pass`).
   - Todo fallo en el scraper debe loguearse con el selector que falló, guardar un screenshot temporal en `.tmp/` **y el sub-agente debe usar la herramienta de visión (vision-tool) para analizar la captura y proponer un fix en el paso de Validación**.

## ⚛️ Frontend & Panel (Next.js)

1. **Mutaciones de Datos:**
   - Preferir **Server Actions** nativos de Next.js para mutar datos (ej: guardar configuraciones del bot) en lugar de crear endpoints de API (`route.ts`) innecesarios.

2. **Gestión de Estado y UI:**
   - Prohibido usar Redux. Si se necesita estado global complejo, usar Zustand.
   - Para estilos, usar estrictamente Tailwind CSS. Prohibido crear archivos `.css` o `.module.css` a menos que sea estrictamente necesario para animaciones complejas.

## 🚫 Reglas Generales de Código (Anti-Pereza de IA)

1. **Cero Código "Placeholder":** - RECHAZAR cualquier commit que contenga comentarios del tipo `// TODO: implementar la lógica aquí`, `pass`, o funciones a medias. El código debe estar 100% implementado.
2. **Secretos:**
   - RECHAZAR cualquier string hardcodeado que parezca un token, contraseña, IP residencial o cookie. Todo debe pasar por `os.getenv()`.

## 💻 Reglas por Sistema Operativo (OS)

### Windows (Prioridad 1 - Verificado)
- El entorno de ejecución principal es Windows.
- El backend usa `WindowsProactorEventLoopPolicy`. Mantener esta compatibilidad.
- Empaquetado: NSIS (.exe).

### macOS (Best Effort - No Verificado)
- No asumir paridad total con Windows.
- Los paths y el naming del backend están acoplados a Windows. 
- Cualquier cambio para macOS debe ser tratado como experimental y no debe romper el flujo de Windows.

## 📁 Estándares de Estructura de Archivos

```text
.
├── .agents/                # Perfiles de los Sub-Agentes SDD
├── scripts/agents-teams-lite   # Herramientas ejecutables SDD (explore, apply, etc.)
├── scripts/                # Scripts de la app
├── directivas/             # El Conocimiento Inmutable (SOPs) -> PROHIBIDO ELIMINAR
├── botardium-panel/web/    # Frontend (Next.js)
├── python-core/            # Backend/Scraper (Python, Patchright, ADB)
├── .env                    # APIs e IPs Residenciales (Seguridad estricta)
└── .gitignore              # Ignorar .engram, .tmp, .env