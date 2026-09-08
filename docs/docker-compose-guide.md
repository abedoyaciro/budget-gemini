# 🐳 Guía de Docker Compose - Despliegue de Aplicaciones

## 🎯 ¿Por qué Docker Compose?

Docker Compose simplifica la gestión de contenedores mediante un archivo de configuración declarativo (`docker-compose.yml`).

### Ventajas sobre `docker run`

| Aspecto | docker run | docker-compose |
|---------|-----------|----------------|
| Comando | `docker run --rm --env-file .env -v ${PWD}/output:/app/output budget-gemini-app` | `docker-compose up` |
| Configuración | En línea de comandos | En archivo YAML |
| Reproducibilidad | Manual | Automática |
| Múltiples servicios | Múltiples comandos | Un solo comando |
| Volúmenes | Especificar cada vez | Configurado una vez |

---

## 📋 Estructura del docker-compose.yml

```yaml
version: '3.8'

services:
  budget-extractor:          # Servicio principal
    build: .                 # Construir desde Dockerfile
    image: budget-gemini-app:latest
    container_name: budget-extractor
    env_file:
      - .env                 # Cargar variables de entorno
    volumes:
      - ./output:/app/output # Montar directorio de salida
    command: python src/extractor_wallet.py
    restart: "no"            # No reiniciar automáticamente

  gemini-test:               # Servicio de prueba (opcional)
    build: .
    image: budget-gemini-app:latest
    container_name: gemini-test
    env_file:
      - .env
    command: python tests/prueba_gemini.py
    restart: "no"
    profiles:
      - test                 # Solo se ejecuta con --profile test
```

---

## 🚀 Comandos Básicos

### Ejecutar el extractor (servicio principal)
```bash
docker-compose up budget-extractor
```

### Ejecutar en segundo plano (detached)
```bash
docker-compose up -d budget-extractor
```

### Ver logs
```bash
docker-compose logs budget-extractor
```

### Ejecutar prueba de Gemini
```bash
docker-compose run --rm gemini-test
```

### Detener servicios
```bash
docker-compose down
```

### Reconstruir después de cambios en código
```bash
docker-compose build
docker-compose up budget-extractor
```

### Reconstruir y ejecutar en un solo comando
```bash
docker-compose up --build budget-extractor
```

---

## 🔄 Flujo de Trabajo Típico

### Primera vez
```bash
# 1. Construir imagen
docker-compose build

# 2. Ejecutar extractor
docker-compose up budget-extractor

# 3. Ver resultados en output/snapshot_wallet.json
```

### Ejecuciones posteriores (sin cambios en código)
```bash
# Solo ejecutar (reutiliza imagen existente)
docker-compose up budget-extractor
```

### Después de cambiar código
```bash
# Reconstruir y ejecutar
docker-compose up --build budget-extractor
```

---

## 🎨 Personalización

### Cambiar límite de registros

Edita `docker-compose.yml`:
```yaml
services:
  budget-extractor:
    environment:
      - RECORDS_LIMIT=200  # Agregar variable de entorno
    command: python src/extractor_wallet.py
```

Luego modifica `src/extractor_wallet.py` para leer esta variable:
```python
records_limit = int(os.getenv('RECORDS_LIMIT', 100))
snapshot_data = extractor.get_context_snapshot(records_limit=records_limit)
```

### Agregar más servicios

```yaml
services:
  budget-extractor:
    # ... configuración existente

  database:
    image: postgres:15
    environment:
      POSTGRES_DB: budget
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

---

## 🧹 Limpieza

### Eliminar contenedores y redes
```bash
docker-compose down
```

### Eliminar contenedores, redes y volúmenes
```bash
docker-compose down -v
```

### Eliminar imágenes también
```bash
docker-compose down --rmi all
```

---

## 🔍 Debugging

### Ver logs en tiempo real
```bash
docker-compose logs -f budget-extractor
```

### Ejecutar comando dentro del contenedor
```bash
docker-compose run --rm budget-extractor bash
```

### Ver estado de servicios
```bash
docker-compose ps
```

---

## 💡 Mejores Prácticas

### 1. Usar perfiles para servicios opcionales
```yaml
services:
  gemini-test:
    profiles:
      - test  # Solo se ejecuta con: docker-compose --profile test up
```

### 2. Separar configuraciones por entorno
```bash
# Desarrollo
docker-compose -f docker-compose.yml up

# Producción
docker-compose -f docker-compose.prod.yml up
```

### 3. Usar variables de entorno
```yaml
services:
  budget-extractor:
    image: budget-gemini-app:${VERSION:-latest}
```

### 4. Healthchecks para servicios persistentes
```yaml
services:
  api:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

---

## 📊 Comparación: docker run vs docker-compose

### Escenario 1: Ejecutar extractor una vez

**docker run:**
```bash
docker run --rm --env-file .env -v ${PWD}/output:/app/output budget-gemini-app
```

**docker-compose:**
```bash
docker-compose up budget-extractor
```

**Ganador:** docker-compose (más corto y claro)

---

### Escenario 2: Desarrollo con cambios frecuentes

**docker run:**
```bash
# Cada vez que cambias código:
docker build -t budget-gemini-app .
docker run --rm --env-file .env -v ${PWD}/output:/app/output budget-gemini-app
```

**docker-compose:**
```bash
# Cada vez que cambias código:
docker-compose up --build budget-extractor
```

**Ganador:** docker-compose (un solo comando)

---

### Escenario 3: Múltiples servicios (extractor + base de datos + API)

**docker run:**
```bash
# Crear red
docker network create budget-network

# Iniciar base de datos
docker run -d --name postgres --network budget-network \
  -e POSTGRES_DB=budget postgres:15

# Iniciar API
docker run -d --name api --network budget-network \
  -e DATABASE_URL=postgres://postgres:5432/budget \
  budget-api

# Ejecutar extractor
docker run --rm --network budget-network \
  --env-file .env -v ${PWD}/output:/app/output \
  budget-gemini-app
```

**docker-compose:**
```bash
docker-compose up
```

**Ganador:** docker-compose (dramáticamente más simple)

---

## 🎓 Conclusión

### Usa `docker run` si:
- ✅ Solo tienes un servicio simple
- ✅ Ejecutas el script ocasionalmente
- ✅ Prefieres comandos explícitos

### Usa `docker-compose` si:
- ✅ Ejecutas el script frecuentemente
- ✅ Tienes múltiples servicios
- ✅ Trabajas en equipo
- ✅ Quieres configuración reproducible
- ✅ Planeas escalar el proyecto

### Para esta app:
**Recomendación:** Empieza con `docker run` para familiarizarte, luego migra a `docker-compose` cuando te sientas cómodo. Ambos métodos están documentados y funcionan perfectamente.