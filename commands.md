# Comandos Docker

## 🏗️ Construir la imagen

```bash
docker build -t budget-gemini-app .
```

## 🚀 Ejecutar contenedores

### Ejecutar prueba de Gemini (por defecto)

```bash
docker run --rm --env-file .env budget-gemini-app
```

### Ejecutar extractor de Wallet

```bash
docker run --rm --env-file .env budget-gemini-app python src/extractor_wallet.py
```

### Ejecutar con variables de entorno individuales (alternativa)

```bash
docker run --rm -e GEMINI_API_KEY="TU_API_KEY" -e WALLET_API_TOKEN="TU_TOKEN" budget-gemini-app
```

## Cómo ver los modelos disponibles

Para listar los modelos que tu API Key tiene permitidos, crea un archivo `modelos.py`:

```python
from google import genai

client = genai.Client()
for model in client.models.list():
    print(model.name)
```

Luego ejecuta con Docker:

```bash
docker run --rm --env-file .env -v ${PWD}:/app budget-gemini-app python modelos.py
```

O en Windows PowerShell:

```powershell
docker run --rm --env-file .env -v ${PWD}:/app budget-gemini-app python modelos.py
```


## 📝 Descripción de los scripts

### `src/prueba_gemini.py`

Verifica la conexión con Google Gemini AI usando la nueva Interactions API.

**Ejecutar:**
```bash
# Local
python src/prueba_gemini.py

# Docker (comando por defecto)
docker run --rm --env-file .env budget-gemini-app
```

### `src/extractor_wallet.py`

Extrae datos financieros desde BudgetBakers Wallet API:
- Cuentas activas
- Categorías de gastos/ingresos
- Etiquetas
- Últimas 20 transacciones
- Guarda todo en `snapshot_wallet.json`

**Ejecutar:**
```bash
# Local
python src/extractor_wallet.py

# Docker
docker run --rm --env-file .env budget-gemini-app python src/extractor_wallet.py
```


## 🔧 Comandos útiles adicionales

### Ver logs del contenedor

```bash
docker logs <container_id>
```

### Ejecutar en modo interactivo

```bash
docker run -it --rm --env-file .env budget-gemini-app /bin/bash
```

### Limpiar imágenes antiguas

```bash
docker image prune -a
```

### Ver imágenes disponibles

```bash
docker images
```

## 📦 Gestión de volúmenes

### Montar directorio local para guardar archivos de salida

```bash
docker run --rm --env-file .env -v ${PWD}:/app budget-gemini-app python src/extractor_wallet.py
```

En Windows PowerShell:
```powershell
docker run --rm --env-file .env -v ${PWD}:/app budget-gemini-app python src/extractor_wallet.py
```

Esto permite que `snapshot_wallet.json` se guarde en tu directorio local.

## 🐛 Solución de problemas

### Reconstruir imagen después de cambios

Después de modificar código o dependencias:

```bash
docker build -t budget-gemini-app .
```

### Verificar que .env se está cargando

```bash
docker run --rm --env-file .env budget-gemini-app env | grep -E "GEMINI|WALLET"
```

En Windows PowerShell:
```powershell
docker run --rm --env-file .env budget-gemini-app env | Select-String -Pattern "GEMINI|WALLET"
```
