# SOP: Account DNA — Onboarding Determinante

## Objetivo
Clasificar cada cuenta Instagram antes de operar para definir el perfil de agresividad y las skills habilitadas.

## Perfiles de Cuenta

### 1. Personal / Agencia (Alta Confianza)
**Criterio:** Cuenta con >500 followers, >6 meses de antigüedad, actividad orgánica previa.

| Parámetro          | Valor                |
|-------------------|:--------------------:|
| `max_dms`          | 20-30/día            |
| `max_follows`      | 20-30/día            |
| `warmup_duration`  | 20 min               |
| `ip_rotation`      | **DESACTIVADA**       |
| `action_delay`     | 2-8 min (DMs)        |
| `proxy_type`       | Residencial fija     |

**Razón:** La consistencia de IP y comportamiento genera confianza en el algoritmo de IG.

### 2. Nueva / Prospectora
**Criterio:** Cuenta con <500 followers, <6 meses, o cuenta de testeo.

| Parámetro          | Valor                     |
|-------------------|:-------------------------:|
| `max_dms`          | 10 (escalar +5/día)       |
| `max_follows`      | 10-15/día                 |
| `warmup_duration`  | 25 min                    |
| `ip_rotation`      | **Cada 5 acciones** (ADB) |
| `action_delay`     | 4-10 min (DMs)            |
| `proxy_type`       | Móvil 4G/5G               |

**Razón:** Cuentas nuevas están bajo mayor escrutinio. La rotación de IP y el bajo volumen reducen el riesgo.

## Output
El script `account_check.py` genera `account_profile.json` en `.tmp/` con la configuración específica. Todos los scripts de negocio DEBEN leer este archivo antes de ejecutar.

## Trampas Conocidas
- **No escalar demasiado rápido:** Incrementar máximo +5 DMs cada 48h para cuentas nuevas.
- **No mezclar perfiles:** Una cuenta definida como "personal" NUNCA debe rotar IP.
