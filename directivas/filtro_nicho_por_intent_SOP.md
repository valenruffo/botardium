# SOP: Filtro de Nicho guiado por Intent del Usuario

## Objetivo

Hacer que el scraping por hashtag entienda el pedido original del usuario (intent) y filtre perfiles por relevancia real de nicho antes de entrar al CRM.

## Principio

- El hashtag sirve para descubrir candidatos.
- La aceptacion final la define el intent del usuario + el perfil real del autor.
- No depender de match textual duro del hashtag exacto.

## Flujo

1. MagicBox genera hashtags.
2. MagicBox tambien genera contexto de nicho:
   - `include_terms`
   - `exclude_terms`
   - `intent_summary`
3. La campaña persiste ese contexto.
4. El scraper valida cada perfil contra ese contexto antes de insertar en CRM.

## Regla de aceptacion

- Para `hashtag/location`, un lead debe:
  1. pasar minimos operativos (followers/posts/identidad), y
  2. mostrar señales positivas del nicho pedido por el usuario.
- Si el perfil no tiene señales positivas y si tiene señales negativas, se rechaza.

## Regla de generalidad

- El sistema debe servir para cualquier nicho (`constructoras`, `noticieros de futbol`, `estetica`, etc.).
- Las señales positivas/negativas no se hardcodean por vertical en UI; se derivan del intent generado por IA.
