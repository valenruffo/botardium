# SOP: Smoke Suite de Hashtags (Regresion)

## Objetivo

Validar rapidamente que el flujo de scraping por hashtag sigue operativo despues de cambios en navegacion, precheck, parseo de metricas o filtros.

## Script

- `scripts/smoke_hashtag_suite.py`

## Comando base

```bash
python scripts/smoke_hashtag_suite.py --hashtags esteticasargentina --limit 8 --min-posts-seen 6 --min-accepted 1
```

## Que valida

1. El scraper termina sin error de ejecucion.
2. Hay posts visibles (`posts_seen >= min-posts-seen`).
3. Hay candidatos validos (`accepted_count + duplicado >= min-qualified`).
4. Opcional: exigir nuevos aceptados (`accepted_count >= min-accepted`).

## Artefacto

- Reporte JSON: `.tmp/hashtag_smoke_report.json`

## Criterio operativo

- Si falla, revisar primero `reason` y `rejected` del reporte.
- Si vuelve `low_posts_seen`, inspeccionar `page_diagnostics` en `.tmp/scraper_status.json`.
- Si vuelve `low_accepted`, revisar minimos operativos (`min_followers`, `min_posts`, `require_identity`) antes de tocar selectores.
