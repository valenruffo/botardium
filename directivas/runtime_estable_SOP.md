# SOP: Runtime estable local y anti-corrupcion de terminal

## Objetivo

Levantar Botardium localmente en Windows sin corromper la terminal de OpenCode ni compartir stdout/stderr de procesos largos con el TTY interactivo.

## Regla dura

- Nunca ejecutar `next dev`, `next start` o `uvicorn` pegados a la consola de OpenCode para operacion normal.
- Todo proceso largo debe iniciarse desacoplado, con logs en `.tmp/logs/`.
- La verificacion del stack debe hacerse por healthchecks y logs, no mirando la consola interactiva.

## Modo estable obligatorio

1. Backend con `uvicorn` desacoplado y log a archivo.
2. Frontend con `next build && next start`, no `next dev`.
3. Healthchecks en puertos `8000` y `3000`.
4. Scripts de arranque/parada dedicados.

## Riesgos conocidos

- Windows + PowerShell + procesos hijos largos + ANSI = consola contaminada.
- Reinicios repetidos desde OpenCode pueden dejar secuencias VT crudas y `digit-argument`.
- Si el frontend muere silenciosamente, `localhost:3000` rechaza la conexion aunque el build previo haya sido correcto.

## Solucion definitiva

- Usar launchers estables que no escriban al TTY.
- Redirigir todo a `.tmp/logs/api.log`, `.tmp/logs/web.log`, `.tmp/logs/launcher.log`.
- Tener un healthcheck local rapido para saber si el stack vive.
- Tratar cualquier reincidencia como incidente de runtime, no como bug del producto.
