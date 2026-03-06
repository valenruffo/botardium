# Directiva: Instalación de Skills (SOP) [COMPLETED]

## Objetivo
Configurar el proyecto con las skins `frontend-design` y `marketingskills` para mejorar las capacidades de diseño y estrategia de marketing del agente.

## Proceso de Instalación

### Skill 1: marketingskills
- **Fuente:** `https://github.com/coreyhaines31/marketingskills.git`
- **Acción:** Clonar el repositorio en `skills/marketingskills`.
- **Requisito:** Cada carpeta en `skills/marketingskills` debe contener su propio `SKILL.md` si es tratado de forma individual, o el repositorio completo debe ser una skill con un `SKILL.md` raíz.

### Skill 2: frontend-design
- **Fuente:** `https://github.com/anthropics/claude-code/tree/da80366c484698e6370ad9e8abf121f33f8f79e0/plugins/frontend-design`
- **Acción:** Extraer la subcarpeta `plugins/frontend-design` y depositarla en `skills/frontend-design`.
- **Requisito:** Asegurar la existencia de un `SKILL.md` (o convertir su `README.md` a `SKILL.md` siguiendo el formato requerido).

## Verificación
- Confirmar la existencia de `SKILL.md` en cada carpeta de skill.
- Actualizar `memoria_maestra.md` tras completar la instalación.

## Trampas Conocidas
- **Rutas Relativas:** Asegurar que las skills sean referenciadas con rutas absolutas o relativas al root del proyecto.
- **Acceso Directo:** El agente debe revisar los `SKILL.md` antes de usarlas.
