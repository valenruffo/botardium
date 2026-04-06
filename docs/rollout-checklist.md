# Rollout Checklist

## Flags de rollout

- `BOTARDIUM_AUTH_ROLLOUT_MODE=enforce|shadow`
- `BOTARDIUM_PATH_CUTOVER_MODE=enforce|shadow`
- `BOTARDIUM_DURABLE_JOBS_MODE=enforce|shadow`
- `BOTARDIUM_REQUIRE_BACKUP_SNAPSHOT=true|false`

`enforce` activa el comportamiento endurecido completo.
`shadow` mantiene visibilidad operativa sin bloquear el flujo por esa capa de rollout.

## Orden recomendado de activacion

1. Crear snapshot de rollback de la DB antes del cutover de paths.
2. Dejar `BOTARDIUM_PATH_CUTOVER_MODE=shadow` y verificar `/health` + `/api/ops/rollout` hasta que no haya divergencias inesperadas.
3. Subir `BOTARDIUM_AUTH_ROLLOUT_MODE=shadow` solo si hace falta una ventana corta de compatibilidad sin token; volver a `enforce` apenas el panel confirme login y polling normales.
4. Activar `BOTARDIUM_DURABLE_JOBS_MODE=enforce` cuando los jobs persistidos y la recuperacion post-restart esten verificados.
5. Cambiar `BOTARDIUM_PATH_CUTOVER_MODE=enforce` una vez que exista snapshot reciente y la convergencia de paths sea estable.

## Smoke checks del operador

1. `python -m pytest tests/test_phase1_wiring.py tests/test_phase2_auth_scope.py tests/test_phase4_job_integration.py tests/test_phase5_operations_readiness.py tests/test_phase7_rollout_safeguards.py`
2. `python scripts/smoke_test.py`
3. `python scripts/rollout_smoke_check.py --workspace-id <workspace_id>`
4. Confirmar que `/health` devuelve `ready=true` y que `/api/ops/rollout` informa snapshot reciente si `BOTARDIUM_REQUIRE_BACKUP_SNAPSHOT=true`.
5. Iniciar sesion en el panel, refrescar la app y validar que la sesion persiste.
6. Verificar que la vista de jobs sigue actualizando estados cada 2 segundos.

## Triggers de rollback

- `/health` pasa a `ready=false` luego del cambio.
- `/api/ops/rollout` muestra `backup_ready=false` o `path_cutover_blocked`.
- El panel pierde sesion local al refrescar o deja de ver `/api/messages/jobs`.
- Los jobs quedan colgados tras reinicio o reaparecen duplicados.

## Monitoreo post-cambio

- Revisar `logs/launcher.log`, `api.log` y `web.log`.
- Confirmar que no aparecen denegaciones cross-workspace inesperadas en `audit_events`.
- Revisar que no crezca la cola de jobs pausados sin reanudacion esperada.
- Mantener el ultimo snapshot DB hasta cerrar la ventana de observacion.
