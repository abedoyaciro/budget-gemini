# Análisis Financiero Inteligente — Gemini AI + BudgetBakers Wallet

> **⚠️ WORK IN PROGRESS (WIP)** — Proyecto personal en evolución.
> El pipeline funcionó de punta a punta con la suscripción activa de
> BudgetBakers Wallet; actualmente sin suscripción no se puede probar
> completo. Plan: evolucionar hacia un Cloud Support Lab (Docker +
> CI/CD + tests automatizados).

Sistema de análisis financiero personal que integra **Google Gemini AI** con la **API REST de BudgetBakers Wallet**. Extrae transacciones, mantiene un histórico de snapshots con detección de cambios, aprende reglas contables automáticamente y genera diagnósticos con **memoria de análisis previos**.

---

## 🏗️ Arquitectura del Sistema

```
budget-gemini/
├── src/
│   ├── extractor_wallet.py        # v3.0 — Extrae TODOS los campos (OpenAPI 1.3.0)
│   ├── gestor_snapshots.py        # v1.0 — Histórico + detección de cambios
│   ├── analizador_finanzas.py     # v3.0 — Diagnóstico con MEMORIA (reglas + histórico)
│   ├── aprendizaje_reglas.py      # v1.1 — Detecta patrones con Interactions API
│   ├── confirmador_reglas.py      # v1.0 — Confirmación S/N/M + previous_interaction_id
│   ├── asistente_enriquecimiento.py # v1.0 — Mejora notas/etiquetas/categorías en Wallet
│   ├── generar_dashboard.py       # v2.0 — Dashboard HTML con Chart.js + Tailwind
│   ├── config_modelos.py          # v1.0 — Gestión centralizada de modelos Gemini
│   └── __init__.py
├── tests/
│   └── prueba_gemini.py           # Prueba de conectividad con Interactions API
├── docs/
│   ├── budgetbakers.openapi.json  # OpenAPI 1.3.0 BudgetBakers Wallet
│   ├── interactions.openapi.json  # OpenAPI Gemini Interactions API
│   ├── commands.md                # Referencia rápida de comandos
│   ├── docker-guide.md
│   └── docker-compose-guide.md
├── output/
│   ├── snapshots/                 # snapshot_YYYY-MM-DD_HH-MM-SS.json (con envelope)
│   ├── diagnosticos/              # diagnostico_YYYY-MM-DD_HH-MM-SS.json + latest
│   ├── historial_interacciones/   # Auditoría de interacciones Gemini
│   ├── logs/                      # pipeline_TIMESTAMP.log + resumen.json
│   ├── snapshot_wallet.json       # Último snapshot (para analizador — compatibilidad)
│   ├── diagnostico_inteligente.json # Último diagnóstico (para dashboard)
│   ├── reglas_aprendidas.json     # Reglas confirmadas + historial de sesiones
│   ├── enriquecimiento_log.json   # Log de cambios aplicados a Wallet
│   └── dashboard.html             # Dashboard HTML auto-contenido
├── run_pipeline.py                # Orquestador del pipeline completo
├── .env                           # Credenciales (NO subir a Git)
├── .env.example                   # Plantilla de variables
├── Dockerfile
├── docker-compose.yml
├── Makefile
└── requirements.txt
```

---

## 🧠 Flujo de Memoria e Inteligencia

```
snapshot_wallet.json
        │
        ▼
analizador_finanzas.py v3.0
        │
        ├── Lee diagnóstico anterior (output/diagnosticos/diagnostico_latest.json)
        ├── Aplica reglas confirmadas (output/reglas_aprendidas.json)
        ├── Detecta cambios vs snapshot anterior (output/snapshots/)
        │
        ▼
DiagnosticoFinanciero (Pydantic v3.0)
        │
        ├── cambios_vs_periodo_anterior  → evolución comparada
        ├── reglas_aplicadas             → qué reglas se usaron
        ├── nuevos_patrones_sugeridos    → patrones sin regla aún
        └── proyeccion_mes_siguiente     → proyección basada en patrones
```

---

## ⚙️ Variables de Entorno

Crea `.env` en la raíz (copia desde `.env.example`):

```env
GEMINI_API_KEY=tu_api_key_de_gemini_aqui
WALLET_API_TOKEN=tu_token_de_wallet_aqui

# Extracción (opcionales)
RECORDS_LIMIT=200          # máx registros por extracción (default: 200)
DAYS_BACK=90               # ventana temporal en días (0 = sin límite, default: 90)

# Modelos Gemini (opcionales — tienen fallback a gemini-3.1-flash-lite)
GEMINI_MODEL_ANALIZADOR=gemini-3.1-flash-lite
GEMINI_MODEL_APRENDIZAJE=gemini-3.1-flash-lite
GEMINI_MODEL_CONFIRMADOR=gemini-3.1-flash-lite
GEMINI_TEMPERATURA=0.3

# Aprendizaje (opcional)
APRENDIZAJE_MAX_REGISTROS=150
```

> ⚠️ El archivo `.env` está en `.gitignore`. Nunca lo subas a Git.

---

## 🚀 Uso con Make (recomendado)

```bash
# Construir imagen Docker
make build

# Pipeline estándar semanal (snapshot + analyze + dashboard)
make pipeline

# Pipeline completo (+ learn + enrich)
make full

# Pasos individuales
make snapshot    # extraer datos de Wallet
make analyze     # diagnóstico con Gemini (usa memoria automáticamente)
make learn       # aprender reglas contables
make enrich      # mejorar notas/etiquetas (automático)
make confirm     # confirmar/rechazar/modificar reglas (interactivo)
make dashboard   # generar dashboard HTML

# Utilidades
make historial   # ver historial de snapshots
make reglas      # ver reglas aprendidas
make logs        # ver último log del pipeline
```

Variables configurables en línea de comando:
```bash
make pipeline DAYS=30 LIMIT=150
make learn TEMPERATURA=0.2
```

---

## 🐳 Uso con docker-compose

```bash
# Pipeline estándar
docker-compose run --rm budget-pipeline

# Pipeline completo
docker-compose run --rm budget-pipeline --full

# Solo un paso
docker-compose run --rm budget-pipeline --only snapshot
docker-compose run --rm budget-pipeline --only analyze

# Con parámetros
DAYS_BACK=30 docker-compose run --rm budget-pipeline

# Confirmación interactiva de reglas (requiere TTY)
docker-compose up budget-confirmar-reglas
```

---

## 🧩 Módulos

### [`src/extractor_wallet.py`](src/extractor_wallet.py) — v3.0

Extrae **todos los campos** de la API BudgetBakers Wallet (OpenAPI 1.3.0):

- **Cuentas**: `accountType`, `moneda` (desde `initialBalance.currencyCode`), `balance {currentBalance, rawCurrentBalance, formula}`, `recordStats`, `color`, `isBankSync`
- **Categorías**: `group {id, nombre}`, `parentId`, `cardinality`, `customCategory`, `systemId`
- **Etiquetas**: `archived`, `createdAt`, `updatedAt`
- **Registros**: `recordType`, `recordState`, `paymentType`, `source`, `counterParty`, `transferRecord`, `place`, `convertedAmount`, categoría embebida, etiquetas embebidas
- Paginación automática (`nextOffset`) — no se pierden registros
- Estadísticas enriquecidas: `registros_con_etiquetas`, `registros_transferencia`, etc.

### [`src/gestor_snapshots.py`](src/gestor_snapshots.py) — v1.0

- Guarda cada extracción en `output/snapshots/snapshot_YYYY-MM-DD_HH-MM-SS.json`
- Envelope de gestión: `{metadata_gestion, data}` con cambios detectados vs anterior
- Detecta: nuevos registros, modificados, nuevas categorías/etiquetas/cuentas
- Mantiene `output/snapshot_wallet.json` actualizado (compatibilidad con analizador)
- CLI: `--days N`, `--limit N`, `--full`, `--historial`

### [`src/analizador_finanzas.py`](src/analizador_finanzas.py) — v3.0 ⭐

Genera diagnóstico financiero con **memoria histórica**:

1. Lee snapshot actual
2. **Carga diagnóstico anterior** desde `output/diagnosticos/diagnostico_latest.json`
3. **Carga reglas confirmadas** desde `output/reglas_aprendidas.json`
4. **Detecta cambios** desde el último snapshot
5. Construye prompt con contexto histórico completo
6. Llama a Gemini con `generate_content` + Structured Outputs (Pydantic)
7. Guarda diagnóstico en `output/diagnosticos/diagnostico_TIMESTAMP.json` + actualiza `diagnostico_latest.json` y `diagnostico_inteligente.json`

**Campos nuevos en DiagnosticoFinanciero v3.0:**
- `cambios_vs_periodo_anterior` — lista comparativa con período previo
- `reglas_aplicadas` — IDs de reglas usadas en el análisis
- `nuevos_patrones_sugeridos` — patrones sin regla que Gemini detectó
- `proyeccion_mes_siguiente` — proyección del próximo mes

### [`src/aprendizaje_reglas.py`](src/aprendizaje_reglas.py) — v1.1

- Usa **Interactions API** de Gemini (con structured output JSON Schema)
- Detecta patrones en el snapshot y propone reglas contables
- Guarda en `output/reglas_aprendidas.json` con estado `pendiente_confirmacion`
- Guarda historial completo de interacciones para fallback ante expiración del servidor

### [`src/confirmador_reglas.py`](src/confirmador_reglas.py) — v1.0

- Flujo interactivo: [S]í / [N]o / [M]odificar por cada regla pendiente
- Usa `previous_interaction_id` para ajustes con contexto completo
- Fallback automático si la interacción expiró (reconstruye contexto desde historial local)
- Guarda historial de auditoría en `output/historial_interacciones/`

### [`src/asistente_enriquecimiento.py`](src/asistente_enriquecimiento.py) — v1.0

- Propone mejoras de notas, etiquetas y categorías en los registros existentes
- Aplica cambios vía `PATCH /records` de la API de Wallet (batch de 10)
- Modo `--auto`: aplica todo sin confirmación manual
- Log de sesión en `output/enriquecimiento_log.json`

### [`src/generar_dashboard.py`](src/generar_dashboard.py) — v2.0

Dashboard HTML auto-contenido con Tailwind CSS + Chart.js:

- **Métricas clave**: ingresos, gastos, balance neto, tasa de ahorro
- **Resumen ejecutivo** + Balance general de Gemini AI
- **Memoria IA**: Cambios vs período anterior, Proyección próximo mes, Reglas aplicadas, Nuevos patrones
- **Gráficos**: evolución mensual, gastos por categoría (doughnut), métodos de pago
- **Balance por cuenta** (COP)
- **Alertas** de Gemini
- **Reglas aprendidas** con estado (confirmada/pendiente/rechazada)
- **Configuración de modelos** activa

---

## 🗂️ Estructura del Output

```
output/
├── snapshots/
│   ├── snapshot_2026-06-25_14-07-07.json    ← envelope {metadata_gestion, data}
│   └── snapshot_2026-06-25_16-57-31.json
├── diagnosticos/
│   ├── diagnostico_2026-06-25_17-30-00.json ← diagnóstico v3.0 con memoria
│   └── diagnostico_latest.json              ← más reciente (leído en próximo análisis)
├── historial_interacciones/
│   ├── interaccion_2026-06-25_13-36-08_analisis.json
│   └── confirmacion_2026-06-25_14-41-49_confirmacion.json
├── logs/
│   ├── pipeline_2026-06-25_16-57-22.log
│   └── pipeline_2026-06-25_16-57-22_resumen.json
├── snapshot_wallet.json              ← último snapshot plano (compatibilidad)
├── diagnostico_inteligente.json      ← último diagnóstico (compatibilidad dashboard)
├── reglas_aprendidas.json            ← reglas con estado + historial de sesiones
├── enriquecimiento_log.json          ← cambios aplicados a Wallet
├── config_modelos_activa.json        ← configuración de modelos activa
└── dashboard.html                    ← dashboard auto-contenido
```

---

## 📦 Dependencias

| Paquete | Uso |
|---------|-----|
| `google-genai` | SDK Gemini AI (Interactions API + generate_content) |
| `python-dotenv` | Carga de variables desde `.env` |
| `requests` | HTTP client para Wallet API |
| `pydantic` | Structured Outputs con Gemini |
| `pytz` | Zona horaria Colombia |

---

## 🔐 Credenciales

Usa siempre el archivo `.env`:

```python
from dotenv import load_dotenv
load_dotenv()
token = os.getenv('WALLET_API_TOKEN')
```

> ❌ No uses `export VARIABLE=valor` — es temporal y no funciona con Docker.

---

## 🔍 Solución de Problemas

| Error | Causa probable | Solución |
|-------|---------------|----------|
| `WALLET_API_TOKEN no configurada` | Falta variable en `.env` | Verifica que `.env` existe y tiene el token |
| `401 Unauthorized` | Token expirado | Genera nuevo token en BudgetBakers |
| `No se encontró snapshot_wallet.json` | No se extrajo primero | Ejecuta `make snapshot` antes de `make analyze` |
| `Interacción no completada` | Problema de conectividad | Verifica `GEMINI_API_KEY` y reintenta |
| `404 Not Found` en previous_interaction_id | Interacción expirada en Gemini | El sistema usa fallback automático desde historial local |

---

## 📝 Documentación Adicional

- [`docs/commands.md`](docs/commands.md) — Referencia rápida de comandos Docker
- [`docs/docker-guide.md`](docs/docker-guide.md) — Conceptos Docker
- [`docs/docker-compose-guide.md`](docs/docker-compose-guide.md) — Guía Docker Compose
- [`docs/budgetbakers.openapi.json`](docs/budgetbakers.openapi.json) — API Wallet OpenAPI 1.3.0
- [`docs/interactions.openapi.json`](docs/interactions.openapi.json) — Gemini Interactions API

---

## 📄 Licencia

Proyecto privado

## 👤 Autor

Anderson Bedoya Ciro
