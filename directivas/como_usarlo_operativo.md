# Como usar Botardium (Guia Operativa)

## 1) Objetivo del sistema

Botardium separa tres capas que no deben mezclarse:

- **Scraping (Dashboard/Campanas):** traer leads al CRM.
- **Message Studio:** definir estilo y prompts para cada etapa de mensaje.
- **CRM de Leads:** operar estados, preparar cuenta emisora y ejecutar envios.

## 2) Flujo recomendado

1. Conecta una cuenta emisora.
2. Define tipo de cuenta (`mature`, `new`, `rehab`).
3. Si requiere calentamiento de cuenta, completa dias antes de outreach.
4. Lanza scraping desde Dashboard para poblar CRM.
5. En Message Studio define Prompt Maestro y prompts por etapa.
6. Actualiza borradores segun alcance (todos/campana + estados elegidos).
7. En CRM selecciona leads validos y envia.

## 3) Estados del CRM y reglas de envio

Estados activos para secuencia:

- `Listo para contactar`
- `Primer contacto`
- `Follow-up 1`
- `Follow-up 2` (ultimo toque)

Estados no enviables en lote:

- `Pendiente` (primero pasar a `Listo para contactar`)
- `Completado`
- `Respondio`
- `Calificado`
- `No responde`
- `No interesado`

Transicion de secuencia al enviar:

- `Listo para contactar` -> `Primer contacto`
- `Primer contacto` -> `Follow-up 1`
- `Follow-up 1` -> `Follow-up 2`
- `Follow-up 2` -> `Completado`

## 4) Message Studio

### 4.1 Prompt Maestro

El Prompt Maestro define tono global de la secuencia.

- **Prompt inicial:** usa configuracion base recomendada.
- **Prompt personalizado:** permite ajustar estilo propio.

Importante:

- El **system prompt duro** (seguridad/calidad) permanece fijo en backend.
- No se expone para edicion en UI.

### 4.2 Prompts por etapa

- **Primer contacto:** apertura inicial.
- **Follow-up 1:** continuidad natural.
- **Follow-up 2:** cierre final elegante.

### 4.3 Actualizacion masiva

Message Studio actualiza borradores de acuerdo a:

- Estados seleccionados.
- Campana seleccionada (o todas).

No depende de seleccion temporal del CRM.

## 5) Calentamientos (diferencia critica)

- **Calentamiento de cuenta:** proceso de dias para cuentas nuevas o en rehabilitacion.
- **Preparar cuenta emisora (sesion):** warmup corto previo al bloque de envio.

Preparar sesion no "calienta leads". Solo prepara la cuenta emisora para enviar mejor.

## 6) Follow-ups

- El sistema guarda `follow_up_due_at` como referencia de fecha.
- El envio sigue siendo **manual** para control operativo.
- Recomendacion: filtrar por estados activos y ejecutar lotes diarios controlados.

## 7) Limites diarios y seguridad

- Respetar cupo diario de cada cuenta.
- Evitar bloques agresivos en cuentas nuevas.
- Si hay error de sesion, re-loguear cuenta y reintentar warmup corto.

## 8) Troubleshooting rapido

1. **No deja enviar:** revisar seleccion (no incluir `Pendiente` ni estados cerrados).
2. **Warmup se corta:** usar `Re-loguear cuenta` y repetir `Preparar cuenta emisora`.
3. **Borradores no cambian:** validar alcance en Message Studio (estado/campana).
4. **Cuenta nueva muy limitada:** continuar plan de calentamiento de cuenta.
