# SOP: Mensajeria IA para outreach en Instagram

## Objetivo

Generar mensajes de primer contacto y follow-up usando LLM real, evitando plantillas rigidas, concatenacion cruda del prompt del usuario o menciones explicitas a fuentes internas del scraping.

## Reglas duras

- El mensaje final debe salir de un modelo LLM real cuando `OPENAI_API_KEY` este disponible.
- Nunca concatenar el prompt del operador debajo de un template fijo como si fuera el mensaje final.
- Nunca mencionar en el copy final:
  - hashtags
  - source interno
  - followers/posts numericos
  - frases tipo `vi tu bio`, `vi tu perfil desde`, `hay fit`
- El modelo puede usar bio/nombre/source como contexto interno, pero no debe filtrarlos de forma literal.
- El tono debe sonar humano, breve y comercialmente natural.

## Variantes

- `first_contact`: abre conversacion con CTA suave.
- `follow_up_1`: retoma sin sonar robotico ni insistente.
- `follow_up_2`: cierre amable y corto.

## Guardrails

- Limitar longitud del mensaje.
- Si el mensaje contiene terminos prohibidos, regenerar o caer a fallback seguro.
- Guardar `rationale` corto para revision humana en CRM.
- Permitir edicion manual antes de enviar.

## Cadencia stealth

- `Personal`: sin warmup de sesion obligatorio; asumir uso organico diario.
- `Nueva/Rehab`: warmup de sesion obligatorio de 15-25 min antes de outreach.
- Delay entre DMs: 2-8 min.
- Tipeo: 50-200 ms por caracter.
- Movimiento de mouse: 100-500 ms.
- Bloques maximos: 10 DMs.
- Pausa post-bloque: 60-90 min.
- Staircase:
  - Personal: iniciar 20, subir +5 cada 3 dias, tope 50.
  - Nueva: iniciar 10, subir +5 cada 3 dias, tope 30.
  - Rehabilitacion: iniciar 8, subir +3 cada 3 dias, tope 20.

## Aprendizajes clave

- Cambiar la logica de copy sin limpiar previews persistidos deja datos legacy peligrosos.
- El CRM siempre debe permitir revisar el borrador completo antes de outreach.
- El prompt del usuario es insumo estrategico, no texto que deba pegarse tal cual en el mensaje final.
