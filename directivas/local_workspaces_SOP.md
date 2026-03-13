# SOP: Workspaces locales de Botardium

## Objetivo

Convertir Botardium Desktop en una app `local-first` donde cada operador o cliente use un workspace local aislado, sin mezclar CRM, campañas, cuentas IG ni sesiones entre operaciones distintas.

## Decisión de producto

- La unidad de aislamiento es el `workspace Botardium`, no la cuenta de Instagram.
- Un workspace puede tener una o varias cuentas IG emisoras.
- Leads, campañas, historial de outreach y sesiones se separan por workspace.
- Los datos viven en la computadora del usuario y no dependen de un login SaaS externo.

## Persistencia esperada

- DB local: `botardium.db`.
- Persistencia de campañas y jobs: cache local por workspace.
- Sesiones IG: guardadas por workspace para evitar cruces accidentales.
- API keys de IA: guardadas por workspace en storage local, no en `.env` como superficie de usuario.
- Cierre/reapertura de la app: debe conservar CRM, campañas y cuentas del workspace seleccionado.

## UX mínima

- Pantalla inicial: listar workspaces existentes + crear nuevo workspace.
- Mensaje claro: "Tus datos viven en esta computadora".
- Cerrar workspace no borra datos; solo vuelve al selector.
- Si faltan API keys, Botardium sigue operativo en modo manual y debe deshabilitar las funciones IA en vez de romper con errores backend.
- Debe existir export/import de workspace para migrar una operación completa entre PCs.

## Updates de la app

- El usuario puede chequear updates desde la UI.
- La detección de updates depende de `GitHub Releases`; hacer push no alcanza, hace falta publicar una nueva versión.
- El flujo mínimo aceptable es: detectar versión nueva, ofrecer descarga del instalador y pedir reinicio/reinstalación controlada.

## Reglas duras

- No usar auth SaaS tradicional para un runtime 100% local.
- No mezclar leads de dos workspaces distintos aunque usen cuentas IG parecidas.
- No marcar como duplicado un lead de otro workspace.
- No dejar `primebot.db`; el nombre oficial es `botardium.db`.

## Próximo paso ideal

- Agregar export/import de workspace como `.zip` con DB, sesiones y config para migrar de PC.
