# SOP: Campañas - Pause/Resume y UX compacta

## Objetivo

Evitar inconsistencias de estado/progreso al pausar scraping y mejorar la operabilidad del listado de campañas.

## Reglas

1. `pause` debe dejar estado `paused` y conservar `progress`.
2. El CTA al volver debe ser `Reanudar Scraping`, no `Iniciar` desde cero.
3. Las campañas más recientes y activas deben aparecer arriba.
4. El listado debe ser colapsable para reducir ruido visual.
5. `limit` de campaña nunca puede ser menor a 5 (UI + backend).

## Integridad de métricas

- En errores de apertura de post individual, no abortar la fuente completa.
- Contabilizar como `post_no_legible` y seguir.
- El resumen final debe priorizar conteo por `campaign_id` para evitar desalineaciones.
