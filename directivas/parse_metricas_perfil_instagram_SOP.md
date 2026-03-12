# SOP: Parseo Robusto de Metricas de Perfil Instagram

## Objetivo

Evitar falsos descartes por `baja_audiencia` o `baja_actividad` cuando Instagram devuelve formatos locales de numeros (ej. `1.234`) o textos en minuscula.

## Problema

- El parser de followers/posts puede leer mal miles con punto (`1.234` => `1`).
- Regex sensible a mayusculas/minusculas reduce deteccion de `followers/seguidores/posts/publicaciones`.

## Accion

1. Hacer parser numerico locale-aware para `k/m`, coma decimal y separadores de miles.
2. Hacer regex case-insensitive para metadatos OG.
3. Agregar fallback de lectura desde header visible del perfil cuando OG no trae datos claros.

## Criterio de exito

- Cuentas con `1.000+` followers no deben caer masivamente en `baja_audiencia` por parseo.
- `posts_seen` y `authors_seen` pueden mantenerse iguales, pero deben subir `accepted` cuando cumplan minimos.
