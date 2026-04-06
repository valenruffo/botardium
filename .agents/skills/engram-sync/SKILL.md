## Engram Sync Between Computers (MANDATORY)
Este proyecto usa **Engram como memoria local-first**, con sincronización por archivos del proyecto en `.engram/`.
### Regla base
- **Toda sesión debe empezar con import**
- **Toda sesión debe terminar con sync/export**
- No asumir que Engram se sincroniza solo.
- No asumir un servidor remoto administrado.
- El puente entre computadoras es la carpeta `.engram/` del proyecto + git (o el mecanismo de sync de archivos que use el operador).
---
### Qué vive dónde
- Base local de Engram: `~/.engram/engram.db`
- Estado exportado del proyecto: `.engram/`
  - `.engram/manifest.json`
  - `.engram/chunks/*.jsonl.gz`
**Importante:** la memoria viva está en la DB local, pero para mover contexto entre computadoras hay que exportar/importar `.engram/`.
---
## Workflow obligatorio por sesión
### Al iniciar una sesión (cualquier computadora)
1. Actualizar repo:
   ```bash
   git pull
2. Importar memoria del proyecto:
      engram sync --import
   3. Verificar estado si hace falta:
      engram sync --status
   
Durante la sesión
- Guardar decisiones, bugfixes, discoveries y resúmenes como memoria Engram.
- No esperar al final para guardar cosas importantes.
- Tratar Engram como parte del sistema operativo del proyecto, no como algo opcional.
Al cerrar una sesión
1. Exportar memoria del proyecto:
      engram sync --project bot_ig
   2. Si .engram/ cambió, versionarlo:
      git add .engram/
   git commit -m "chore(engram): sync project memory"
   git push
   
---
Workflow entre Windows y Mac
Si trabajaste en Windows y seguís en Mac
En Windows, al terminar:
engram sync --project bot_ig
git add .engram/
git commit -m "chore(engram): sync project memory"
git push
En Mac, al empezar:
git pull
engram sync --import
Si trabajaste en Mac y seguís en Windows
En Mac, al terminar:
engram sync --project bot_ig
git add .engram/
git commit -m "chore(engram): sync project memory"
git push
En Windows, al empezar:
git pull
engram sync --import
---
## Hard Rules
- **Nunca** cerrar una jornada sin correr:
  ```bash
  engram sync --project bot_ig
  ```
- **Nunca** empezar en otra máquina sin correr:
  ```bash
  engram sync --import
  ```
- Si `.engram/` cambió y querés continuidad real entre computadoras, **hay que subir esos cambios**.
- No asumir que la memoria de una máquina ya existe en la otra.
- Si hay dudas, correr:
  ```bash
  engram sync --status
  ```
---
Operational Notes
- engram sync --project bot_ig = exporta memoria local del proyecto hacia .engram/
- engram sync --import = importa a la máquina local lo que ya exista en .engram/
- engram sync --status = muestra estado local/import/export
- Si el operador usa git como transporte, .engram/ no debe estar ignorado
- Si no se versiona .engram/, la memoria no viaja entre computadoras