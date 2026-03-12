# SOP: Reestructura de botardium-panel

## Objetivo

Eliminar la carpeta `botardium-panel/apps/` y dejar el frontend solo en `botardium-panel/web/`, porque la logica Python vive en `scripts/` y en la raiz del proyecto.

## Regla operativa

- El frontend de Next.js debe residir en `botardium-panel/web/`.
- No volver a crear `botardium-panel/apps/api/` para backend local.
- Las referencias de documentacion, comandos y memoria deben apuntar a `botardium-panel/web/`.
- Los scripts Python siguen viviendo fuera de `botardium-panel/`.

## Riesgos conocidos

- Rutas viejas en docs o AGENTS pueden seguir apuntando a `botardium-panel/web` incorrectamente si la reestructura no se refleja en todo el repo.
- Builds locales pueden dejar `.next/` y `node_modules/` grandes dentro del frontend consolidado.
- Cualquier automatizacion que use paths hardcodeados a la estructura previa debe actualizarse.

## Solucion definitiva

- Mantener el frontend en `botardium-panel/web`.
- No recrear `botardium-panel/apps/api` ni `botardium-panel/apps/web`.
- Mantener la logica Python en `scripts/` y en la raiz del proyecto.
- Actualizar memoria/documentacion para consolidar la nueva estructura.
