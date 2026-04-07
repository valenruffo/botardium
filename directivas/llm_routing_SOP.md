# SOP: Routing de Modelos LLM en Botardium

## Objetivo

Dejar explicito que modelo se usa en cada funcionalidad para optimizar costo sin perder robustez.

## Routing actual

- `MagicBox / Strategy`:
  - Proveedor principal: Google Gemini
  - Modelo requerido: `gemini-3-flash`
  - Fallback: inferencia local segura si Gemini falla.

- `Message Studio / borradores de outreach`:
  - Proveedor principal: Google Gemini
  - Modelo requerido: `gemini-3-flash`
  - Fallback: generador local seguro

- `Filtro inteligente de nicho en scraping`:
  - Base: reglas locales + contexto de intent de MagicBox
  - Clasificador auxiliar: Gemini `gemini-3-flash` para casos ambiguos
  - Fallback: reglas locales solamente

## Variables de entorno relevantes

- `GOOGLE_API_KEY`
- `GOOGLE_FLASH_MODEL=gemini-3-flash`

## Regla

- `MagicBox` y `Message Studio` deben mantener una sola fuente LLM en runtime: Gemini.
- Si Gemini no responde o devuelve salida invalida, caer a fallback local seguro.
