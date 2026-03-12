# SOP: Filtro Global de Coherencia de Perfil

## Objetivo

Reducir falsos positivos en scraping (cuentas fuera de rubro) sin volver al filtro estricto que bloquea resultados.

## Alcance

- Aplicable a cualquier nicho (`hashtag` y `location`), no solo estetica.
- Mantiene criterios operativos como base: followers, posts, identidad.

## Regla de Coherencia

1. Calcular señales positivas de nicho:
   - Match con tokens del source.
   - Match con keywords objetivo generales.
2. Calcular señales negativas fuertes (medios/noticias, agregadores, etc.).
3. Solo descartar por coherencia cuando:
   - no hay señales positivas,
   - y hay señales negativas suficientes.

## Principio

- **No volver a filtro duro por keyword exacta.**
- **Sí bloquear outliers evidentes** para limpiar ruido operativo.

## Resultado esperado

- Mantener volumen de leads.
- Reducir cuentas claramente fuera del nicho detectado en el post fuente.
