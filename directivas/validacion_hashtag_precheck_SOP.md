# SOP: Validacion Preventiva de Hashtags y Variantes

## Objetivo

Evitar campanas con 0 leads por hashtags inexistentes o demasiado reducidos, y mejorar la calidad de sugerencias de IA agregando variantes utiles (singular/plural).

## Problema detectado

- La IA puede sugerir un hashtag demasiado especifico que no tiene volumen real.
- El scraper puede ejecutar igual y terminar sin resultados utiles.
- El operador no siempre recibe una explicacion accionable (ej. probar plural).

## Estrategia

1. Agregar precheck de hashtag antes de scraping real.
2. Probar variantes morfologicas simples (singular/plural) cuando sea natural.
3. Si no hay volumen minimo, abortar source con mensaje claro: nicho no encontrado o demasiado reducido.
4. Mostrar recomendaciones operativas para hashtags en UI.

## Reglas de implementacion

- No lanzar scraping profundo de hashtag sin precheck previo.
- No reportar exito de source cuando el hashtag no supera validacion minima.
- Registrar en status y source stats el motivo tecnico (`hashtag_no_encontrado`, `hashtag_muy_reducido`).
- Mantener mensajes entendibles para operador final.

## Criterios

- `valido`: hashtag con volumen inicial suficiente para intentar extraccion.
- `muy reducido`: existe algo de contenido, pero insuficiente para una campana util.
- `no encontrado`: sin contenido util detectado.
