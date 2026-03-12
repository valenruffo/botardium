# SOP: Variantes de Hashtag en MagicBox (sin truncados)

## Objetivo

Evitar que MagicBox genere hashtags mutilados o antinaturales (ej. `buenosaire`, `buenosair`) al expandir variantes.

## Problema detectado

- La expansión morfológica ciega (`-s`, `-es`) rompe topónimos y compuestos.
- El usuario recibe rutas con hashtags de baja calidad aunque el primero sea correcto.

## Regla

1. Nunca truncar por defecto `s/es` de hashtags compuestos.
2. Usar variantes controladas por diccionario (singular/plural útil y alias geográficos reales).
3. Filtrar variantes sospechosas de truncado antes de devolver al frontend.

## Ejemplo esperado

- Input válido: `constructorasbuenosaires`
- Variantes aceptables: `constructorasbsas`, `constructorascaba`, `constructorasbaires`
- Variantes prohibidas: `constructorasbuenosaire`, `constructorasbuenosair`
