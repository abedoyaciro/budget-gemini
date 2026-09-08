# Comandos Docker — Referencia Rápida

## 🏗️ Construir la imagen

Solo necesario la primera vez o cuando cambies código / `requirements.txt` / `Dockerfile`:

```bash
docker-compose build
```

Equivalente manual:
```bash
docker build -t budget-gemini-app .
```

---

## 🚀 Servicios disponibles (docker-compose)

### Extracción con histórico — uso normal

```bash
# Extrae datos y guarda en output/snapshots/ con timestamp y detección de cambios
docker-compose up budget-snapshot

# Reconstruir imagen y ejecutar snapshot
docker-compose up --build budget-snapshot
```

### Ver historial de snapshots

```bash
docker-compose up budget-historial
```

### Extracción simple (sin histórico)

```bash
# Sobreescribe output/snapshot_wallet.json directamente
docker-compose up budget-extractor
```

### Análisis con Gemini AI

```bash
# Requiere output/snapshot_wallet.json — ejecutar snapshot primero
docker-compose up budget-analyzer
```

### Prueba de conectividad Gemini

```bash
docker-compose --profile test run --rm gemini-test
```

---

## ⚙️ Parámetros configurables (sin rebuild)

### Vía variables de entorno en `.env` o `-e`

```bash
# Últimos 30 días, máx 150 registros
DAYS_BACK=30 RECORDS_LIMIT=150 docker-compose up budget-snapshot
```

### Vía argumentos CLI al contenedor

```bash
# Extracción completa (sin filtro de fecha)
docker-compose run --rm budget-snapshot python src/gestor_snapshots.py --full

# Últimos 7 días
docker-compose run --rm budget-snapshot python src/gestor_snapshots.py --days 7

# Últimos 14 días, máx 100 registros
docker-compose run --rm budget-snapshot python src/gestor_snapshots.py --days 14 --limit 100
```

---

## 🐳 Equivalentes con docker run

```bash
# Snapshot con histórico
docker run --rm --env-file .env -v ${PWD}/output:/app/output budget-gemini-app \
  python src/gestor_snapshots.py --days 90

# Extracción simple
docker run --rm --env-file .env -v ${PWD}/output:/app/output budget-gemini-app \
  python src/extractor_wallet.py

# Análisis con Gemini
docker run --rm --env-file .env -v ${PWD}/output:/app/output budget-gemini-app \
  python src/analizador_finanzas.py

# Historial de snapshots
docker run --rm --env-file .env -v ${PWD}/output:/app/output budget-gemini-app \
  python src/gestor_snapshots.py --historial

# Prueba de Gemini
docker run --rm --env-file .env budget-gemini-app python tests/prueba_gemini.py
```

**Windows PowerShell:** sustituye `\` por `` ` ``.

---

## 📝 Descripción de módulos

### `src/gestor_snapshots.py` ⭐ Principal

Extrae datos de la API y gestiona el histórico de snapshots con detección de cambios.

```text
Argumentos:
  --days N      Días hacia atrás (default: $DAYS_BACK o 90)
  --limit N     Máx registros (default: $RECORDS_LIMIT o 200)
  --full        Sin filtro de fecha (toda la historia)
  --historial   Solo muestra snapshots guardados y sale
```

### `src/extractor_wallet.py`

Extracción directa, sin gestión de histórico. Útil para pruebas rápidas.

### `src/analizador_finanzas.py`

Genera diagnóstico financiero con Gemini AI (Structured Outputs). Lee `output/snapshot_wallet.json`.

### `tests/prueba_gemini.py`

Verifica la conexión con la Interactions API de Gemini.

---

## 🔧 Comandos útiles

```bash
# Ver logs de un servicio en tiempo real
docker-compose logs -f budget-snapshot

# Abrir shell dentro del contenedor (debug)
docker run -it --rm --env-file .env -v ${PWD}/output:/app/output budget-gemini-app /bin/bash

# Ver imágenes disponibles
docker images

# Limpiar imágenes sin usar
docker image prune -a

# Limpiar todo (imágenes, contenedores, volúmenes)
docker system prune -a --volumes

# Verificar que .env se carga correctamente
docker run --rm --env-file .env budget-gemini-app env | grep -E "GEMINI|WALLET|RECORDS|DAYS"
# Windows PowerShell:
docker run --rm --env-file .env budget-gemini-app env | Select-String -Pattern "GEMINI|WALLET|RECORDS|DAYS"
```

---

## 🔍 Ver modelos de Gemini disponibles

```python
# Crea un archivo temporal modelos.py
from google import genai
client = genai.Client()
for model in client.models.list():
    print(model.name)
```

```bash
docker run --rm --env-file .env -v ${PWD}:/app budget-gemini-app python modelos.py
```
