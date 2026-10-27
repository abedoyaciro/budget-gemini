# 🐳 Guía Completa de Docker - Guía practica para desarrolladores

## 📚 Conceptos Fundamentales

### Imagen vs Contenedor

**IMAGEN:**
- Es una **plantilla inmutable** (como una clase en programación)
- Contiene el código, dependencias y configuración
- Se construye una vez y se reutiliza múltiples veces
- Ocupa espacio en disco pero se puede limpiar

**CONTENEDOR:**
- Es una **instancia en ejecución** de una imagen (como un objeto)
- Temporal y efímero (se destruye al terminar con `--rm`)
- Cada `docker run` crea un nuevo contenedor desde la imagen
- No acumula espacio si usas `--rm`

### Analogía
```
Imagen = Receta de cocina (se escribe una vez)
Contenedor = Plato preparado (se hace cada vez que cocinas)
```

---

## 🎯 ¿Cuál Método Usar?

### Método Actual: `docker run` (Bueno para desarrollo rápido)

**Ventajas:**
- ✅ Simple y directo
- ✅ Ideal para scripts que se ejecutan y terminan
- ✅ No deja contenedores residuales con `--rm`

**Desventajas:**
- ❌ Comando largo y repetitivo
- ❌ Fácil olvidar parámetros
- ❌ No ideal para servicios persistentes

**Cuándo usar:**
- Scripts de extracción de datos
- Tareas programadas (cron jobs)
- Ejecuciones puntuales

---

### Método Recomendado: `docker-compose` (Mejor para proyectos serios)

**Ventajas:**
- ✅ Configuración declarativa en archivo YAML
- ✅ Un solo comando: `docker-compose up`
- ✅ Gestión automática de volúmenes y redes
- ✅ Fácil de versionar y compartir
- ✅ Ideal para múltiples servicios

**Desventajas:**
- ❌ Requiere archivo adicional (docker-compose.yml)
- ❌ Curva de aprendizaje inicial

**Cuándo usar:**
- Proyectos en producción
- Desarrollo en equipo
- Aplicaciones con múltiples servicios

---

## 🔄 Gestión de Builds

### ¿Cuándo hacer `docker build`?

**SOLO cuando cambies:**
- ✅ Código fuente (archivos .py)
- ✅ Dependencias (requirements.txt)
- ✅ Dockerfile
- ✅ Archivos copiados al contenedor

**NO necesitas rebuild si cambias:**
- ❌ Variables en .env (se pasan en runtime)
- ❌ Archivos montados con volúmenes (-v)
- ❌ Documentación (.md)

### ¿Se acumulan los builds?

**SÍ, pero Docker es inteligente:**

1. **Caché de capas:** Docker reutiliza capas sin cambios
2. **Imágenes dangling:** Builds antiguos quedan como `<none>`
3. **Limpieza automática:** Docker limpia automáticamente (configurable)

**Comandos de limpieza:**
```bash
# Ver imágenes
docker images

# Limpiar imágenes sin usar
docker image prune -a

# Limpiar todo (imágenes, contenedores, volúmenes)
docker system prune -a --volumes
```

---

## 📊 Comparación de Métodos

| Aspecto | docker run | docker-compose |
|---------|-----------|----------------|
| Simplicidad inicial | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| Mantenibilidad | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| Escalabilidad | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| Reproducibilidad | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Ideal para scripts | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| Ideal para servicios | ⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## 🚀 Recomendación para la app

### Para tu caso específico: **Ambos métodos son válidos**

**Usa `docker run` si:**
- Solo ejecutas el script ocasionalmente
- Prefieres comandos simples
- No planeas agregar más servicios

**Usa `docker-compose` si:**
- Ejecutas el script frecuentemente
- Planeas agregar base de datos o API
- Trabajas en equipo
- Quieres una configuración más profesional

---

## 💡 Mejores Prácticas

### 1. Optimizar Dockerfile
```dockerfile
# Copiar requirements primero (mejor caché)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código después (cambia más frecuentemente)
COPY . .
```

### 2. Usar .dockerignore
Evita copiar archivos innecesarios (ya implementado ✅)

### 3. Tags de versión
```bash
# En lugar de 'latest'
docker build -t budget-gemini-app:1.0.0 .
docker build -t budget-gemini-app:latest .
```

### 4. Multi-stage builds (avanzado)
Para imágenes más pequeñas en producción

---

## 🎓 Respuestas a tus Preguntas

### ¿Es mejor usar contenedor o imagen?
**Ambos se usan juntos:**
- Construyes la **imagen** una vez
- Ejecutas **contenedores** desde esa imagen múltiples veces

### ¿Cada cuánto hacer build?
**Solo cuando cambies código o dependencias**
- Cambios en .py → rebuild
- Cambios en .env → NO rebuild
- Cambios en docs → NO rebuild

### ¿Se acumulan los builds?
**Sí, pero:**
- Docker usa caché inteligente
- Puedes limpiar con `docker image prune`
- No es un problema en desarrollo normal
- En producción, usa CI/CD con limpieza automática

### ¿Cuál es la mejor forma?
**Para app de Integración:**
1. **Desarrollo:** `docker run` (actual) está bien
2. **Producción:** Migrar a `docker-compose`
3. **Futuro:** Considerar Kubernetes si escala mucho

---

## 📝 Conclusión

Tu implementación actual con `docker run` es **correcta y apropiada** para un script de extracción de datos. No hay problema con hacer builds frecuentes durante desarrollo. Docker maneja eficientemente el caché y la limpieza.

**Recomendación:** Mantén `docker run` por ahora, pero considera `docker-compose` cuando:
- Agregues más servicios (base de datos, API)
- El equipo crezca
- Necesites despliegue en producción