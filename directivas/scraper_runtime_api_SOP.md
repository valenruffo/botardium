# SOP: Estabilizar Scraper Real en Runtime API

## Objetivo

Corregir el fallo temprano del scraper real cuando se ejecuta desde FastAPI (`NotImplementedError()` al iniciar navegador) sin degradar el flujo CLI que ya funciona.

## Diagnostico actual

- El scraper via campaña falla casi inmediato con progreso 10% -> 0%.
- El mismo `run_scraper(...)` ejecutado por CLI completa sin ese crash temprano.
- La diferencia principal es el contexto de loop async (servidor vs proceso aislado).

## Hipotesis operativa

En Windows, el loop activo de Uvicorn/FastAPI puede ser `SelectorEventLoop`; Patchright necesita operaciones de subprocess que en ese loop lanzan `NotImplementedError`.

## Plan de ejecucion

1. Mantener `_run_campaign_scraping` como orquestador (status/progress/logs).
2. Ejecutar `run_scraper(...)` en un hilo aislado con su propio `ProactorEventLoop`.
3. Conservar lectura de `scraper_status.json` para progreso en vivo.
4. Mejorar detalle de error final incluyendo tipo de excepcion cuando `str(exc)` venga vacio.
5. Verificar con compilacion Python y prueba de endpoint de campaña.

## Reglas y trampas conocidas

- NO cambiar el prompt/sistema ni la logica de filtrado de leads para este fix.
- NO revertir mejoras previas de status/error en `lead_scraper.py`.
- NO bloquear el event loop principal de FastAPI; el scraper debe correr desacoplado.
- Si hay nuevos hallazgos de runtime Windows, documentarlos en `memoria_maestra.md`.
