# SOP: Routing de Modelos LLM en Botardium

## Objetivo

Dejar explicito que modelo se usa en cada funcionalidad para optimizar costo sin perder robustez.

## Routing actual

- `MagicBox / Strategy`:
  - Proveedor principal: OpenAI
  - Modelo recomendado: `gpt-4o-mini`
  - Motivo: salida JSON estricta y estable.

- `Message Studio / borradores de outreach`:
  - Proveedor principal: Google Gemini
  - Modelo requerido: `gemini-3-flash`
  - Fallback 1: OpenAI (`gpt-4o-mini` o `OPENAI_MESSAGE_MODEL`)
  - Fallback 2: generador local seguro

- `Filtro inteligente de nicho en scraping`:
  - Base: reglas locales + contexto de intent de MagicBox
  - Clasificador auxiliar: Gemini `gemini-3-flash` para casos ambiguos
  - Fallback: reglas locales solamente

## Variables de entorno relevantes

- `OPENAI_API_KEY`
- `GOOGLE_API_KEY`
- `GOOGLE_FLASH_MODEL=gemini-3-flash`
- `OPENAI_MESSAGE_MODEL=gpt-4o-mini`

## Regla

- No mover `MagicBox` fuera de OpenAI sin validar antes la estabilidad del JSON.
- Priorizar Gemini en tareas frecuentes/baratas de copy o clasificacion.
