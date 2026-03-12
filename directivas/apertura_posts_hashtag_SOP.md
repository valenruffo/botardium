# SOP: Apertura Robusta de Posts desde Hashtag

## Objetivo

Reducir rechazos `post_no_legible` al procesar hashtags cuando Instagram muestra la grilla pero falla la apertura de posts individuales.

## Problema

- Navegar cada post en la misma page del grid puede terminar en `chrome-error://chromewebdata/`.
- Eso corta la lectura de autores aunque existan posts válidos en la fuente.

## Regla

1. Mantener la page principal estable para el grid.
2. Abrir el post solo desde modal/grid; no navegar a `/p/...` como flujo principal.
3. Usar página aparte solo para abrir el perfil del autor, no el post.
4. Si aparece patrón de rate-limit (`post_no_legible` repetido), enfriar el ritmo con pausas progresivas.
5. Si el modal abre pero no se puede leer autor, contabilizar `autor_no_detectado`.
6. No invalidar toda la fuente por fallos puntuales de posts.

## Resultado esperado

- Menos `post_no_legible` masivo.
- Menos errores finales ruidosos por navegación interrumpida.
- Mayor tasa de autores leídos por hashtag.
