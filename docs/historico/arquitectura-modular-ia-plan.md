# Plan de arquitectura modular e integración multi proveedor IA

## Overview

Objetivo: rediseñar progresivamente el repositorio para separar responsabilidades por capas y módulos, de forma que la lógica de Wallet, el procesamiento financiero, la visualización y la integración con IA evolucionen de manera independiente. El alcance incluye una estrategia explícita para soportar Gemini Interactions y una futura integración con Nvidia más RAG como proveedores intercambiables, además de una estrategia de ramas Git para desarrollar estas líneas en paralelo sin bloquear el repo principal. El plan también debe validar la ubicación de los archivos y carpetas existentes, proponer una estructura sana para artefactos fuera de la arquitectura de código y recomendar dónde debería vivir el índice RAG.

## Sub-tasks

### [ ] Sub-task 1: Definir la arquitectura objetivo por capas y módulos
- **Intent** — Establecer una estructura destino clara para el repositorio, separando transporte, dominio, persistencia, presentación y proveedores de IA, de modo que el refactor posterior tenga una guía consistente.
- **Expected Outcomes** — Existe una arquitectura objetivo documentada con responsabilidades por módulo, dependencias permitidas entre capas y ubicación prevista de los archivos actuales dentro de la nueva estructura.
- **Todo List**
  1. Mapear los módulos actuales del repo a dominios funcionales: Wallet API, snapshots, análisis, reglas, enriquecimiento, dashboard y pipeline.
  2. Definir capas objetivo y reglas de dependencia entre ellas.
  3. Proponer una estructura de directorios destino que preserve el comportamiento actual mientras reduce el acoplamiento.
  4. Identificar qué utilidades transversales deben centralizarse primero: configuración, logging, tiempo, serialización, errores y modelos compartidos.
  5. Auditar la ubicación actual de archivos no funcionales del código de dominio, como comandos, documentación, ayudas operativas y artefactos temporales, y definir dónde deberían vivir.
- **Relevant Context** — [`README.md`](README.md), [`src/extractor_wallet.py`](src/extractor_wallet.py), [`src/gestor_snapshots.py`](src/gestor_snapshots.py), [`src/analizador_finanzas.py`](src/analizador_finanzas.py), [`src/aprendizaje_reglas.py`](src/aprendizaje_reglas.py), [`src/confirmador_reglas.py`](src/confirmador_reglas.py), [`src/asistente_enriquecimiento.py`](src/asistente_enriquecimiento.py), [`src/generar_dashboard.py`](src/generar_dashboard.py), [`run_pipeline.py`](run_pipeline.py), [`commands.md`](commands.md), [`docs/commands.md`](docs/commands.md)
- **Status** — `[ ] pending`

### [ ] Sub-task 2: Diseñar contratos estables para proveedores externos y persistencia
- **Intent** — Aislar la dependencia de Wallet API, Gemini SDK, Interactions API y almacenamiento JSON detrás de interfaces y adaptadores, para que el dominio no dependa de implementaciones concretas.
- **Expected Outcomes** — Quedan definidos los contratos de cliente Wallet, proveedor IA, memoria conversacional o RAG y repositorios de persistencia; además se aclara qué datos cruzan cada frontera.
- **Todo List**
  1. Definir interfaces para acceso a Wallet, proveedor de generación, proveedor de interacción, repositorio de snapshots, repositorio de reglas y repositorio de diagnósticos.
  2. Delimitar los DTO o modelos compartidos entre capas para evitar pasar JSON crudo por todo el sistema.
  3. Identificar puntos donde hoy hay inicialización duplicada de SDKs, acceso directo a archivos o URLs hardcodeadas.
  4. Proponer adaptadores iniciales que envuelvan la implementación actual sin cambiar comportamiento.
- **Relevant Context** — [`src/extractor_wallet.py`](src/extractor_wallet.py), [`src/asistente_enriquecimiento.py`](src/asistente_enriquecimiento.py), [`src/confirmador_reglas.py`](src/confirmador_reglas.py), [`src/config_modelos.py`](src/config_modelos.py), [`output/enriquecimiento_log.json`](output/enriquecimiento_log.json)
- **Status** — `[ ] pending`

### [ ] Sub-task 3: Diseñar la estrategia de compatibilidad entre Gemini Interactions y Nvidia más RAG
- **Intent** — Definir cómo convivirán múltiples backends de IA sin duplicar la lógica del dominio, preservando Gemini como implementación de referencia y habilitando Nvidia más RAG como proveedor alternativo.
- **Expected Outcomes** — Existe una estrategia clara para desacoplar prompts, schemas, memoria, interacción y recuperación de contexto; se describen las diferencias entre Interactions y un flujo basado en RAG y cómo resolverlas sin romper compatibilidad.
- **Todo List**
  1. Separar conceptualmente los casos de uso de IA: análisis financiero, aprendizaje de reglas, modificación de reglas y enriquecimiento.
  2. Definir una interfaz común de proveedor IA y resolver qué capacidades son obligatorias y cuáles opcionales.
  3. Diseñar una abstracción de memoria portable que permita usar previous interaction cuando exista o reconstrucción con RAG e historial local cuando no exista.
  4. Determinar qué artefactos actuales pueden servir de base al RAG: snapshots, reglas confirmadas, historial de interacciones, diagnósticos y logs de enriquecimiento.
  5. Recomendar dónde debe vivir el índice RAG, diferenciando entre almacenamiento local inicial y una posible evolución futura, y justificar la opción elegida para este repo.
  6. Proponer cómo seleccionar proveedor activo por configuración sin alterar el resto del pipeline.
- **Relevant Context** — [`src/analizador_finanzas.py`](src/analizador_finanzas.py), [`src/aprendizaje_reglas.py`](src/aprendizaje_reglas.py), [`src/confirmador_reglas.py`](src/confirmador_reglas.py), [`src/asistente_enriquecimiento.py`](src/asistente_enriquecimiento.py), [`output/historial_interacciones`](output/historial_interacciones), [`output/reglas_aprendidas.json`](output/reglas_aprendidas.json)
- **Status** — `[ ] pending`

### [ ] Sub-task 4: Planear la migración incremental sin romper el pipeline actual
- **Intent** — Ordenar el refactor en etapas pequeñas y verificables, de manera que el sistema siga funcionando durante la transición y cada cambio sea revisable.
- **Expected Outcomes** — Existe una secuencia de migración por fases que prioriza fundaciones, adaptadores, dominio, presentación y pruebas, con validaciones claras entre etapas.
- **Todo List**
  1. Definir la primera fase de refactor sin cambios de comportamiento visibles.
  2. Identificar qué archivos pueden convertirse primero en wrappers o fachadas.
  3. Establecer criterios de validación por etapa: compatibilidad de salidas, build Docker, pipeline, dashboard y persistencia.
  4. Definir qué deudas técnicas no se deben mezclar en la misma fase para no ampliar riesgo.
- **Relevant Context** — [`run_pipeline.py`](run_pipeline.py), [`Makefile`](Makefile), [`Dockerfile`](Dockerfile), [`README.md`](README.md)
- **Status** — `[ ] pending`

### [ ] Sub-task 5: Diseñar la estrategia de ramas y flujo Git para refactor y proveedores IA
- **Intent** — Permitir que el refactor arquitectónico, la línea Gemini y la línea Nvidia más RAG avancen en paralelo con bajo costo de integración.
- **Expected Outcomes** — Se documenta un flujo Git recomendado con ramas base, ramas de integración, reglas de merge y puntos de sincronización entre iniciativas.
- **Todo List**
  1. Definir el rol de `main` como línea estable y el rol de una rama base de refactor.
  2. Proponer ramas de trabajo separadas para compatibilidad Gemini y para Nvidia más RAG, apoyadas sobre la base refactorizada.
  3. Determinar cuándo conviene fusionar cambios horizontales a la rama base y cuándo mantenerlos aislados por proveedor.
  4. Establecer una política para evitar divergencia larga entre las ramas de proveedor y la rama de arquitectura.
  5. Definir qué validaciones mínimas deben pasar antes de integrar cambios entre ramas.
- **Relevant Context** — [`README.md`](README.md), [`run_pipeline.py`](run_pipeline.py), [`src/config_modelos.py`](src/config_modelos.py), [`commands.md`](commands.md), [`docs/commands.md`](docs/commands.md)
- **Status** — `[ ] pending`

### [ ] Sub-task 6: Validar la estructura completa del proyecto y reubicar artefactos fuera de la arquitectura
- **Intent** — Revisar todo lo existente en el repo para determinar si cada archivo vive en el lugar correcto y proponer una estructura ordenada también para documentación, comandos, ayudas operativas, temporales y salidas.
- **Expected Outcomes** — Existe un criterio explícito para decidir qué debe vivir en raíz, qué debe ir a `docs`, qué debe quedar en `output`, qué debe ir a carpetas de tooling o soporte y qué elementos sobran o están duplicados.
- **Todo List**
  1. Inventariar archivos y carpetas relevantes que no pertenecen directamente al código de dominio o aplicación.
  2. Evaluar si su ubicación actual es correcta o si conviene moverlos.
  3. Proponer una estructura objetivo para raíz, documentación, scripts operativos, artefactos temporales y salidas generadas.
  4. Identificar duplicidades actuales, como comandos operativos presentes tanto en raíz como en documentación.
  5. Definir reglas para evitar que vuelvan a aparecer archivos operativos desordenados en la raíz.
- **Relevant Context** — [`README.md`](README.md), [`commands.md`](commands.md), [`docs/commands.md`](docs/commands.md), [`output`](output), [`Dockerfile`](Dockerfile), [`docker-compose.yml`](docker-compose.yml), [`Makefile`](Makefile)
- **Status** — `[ ] pending`

### [ ] Sub-task 7: Preparar la base para implementación y validación futura
- **Intent** — Asegurar que el plan produzca una guía accionable para implementación posterior, incluyendo riesgos, decisiones abiertas y dependencias entre subtareas.
- **Expected Outcomes** — El plan deja claros los supuestos, riesgos, decisiones que habrá que confirmar durante implementación y el orden recomendado de ejecución en modo agente.
- **Todo List**
  1. Resumir riesgos de acoplamiento actuales que justifican el refactor.
  2. Identificar decisiones abiertas que impactan la implementación, como almacenamiento para RAG, nivel de abstracción de DTOs y manejo de memoria conversacional.
  3. Definir puntos de control donde conviene detenerse para revisión antes de avanzar a la siguiente fase.
  4. Alinear las subtareas para que puedan ejecutarse una por una con cambios acotados.
- **Relevant Context** — [`src/asistente_enriquecimiento.py`](src/asistente_enriquecimiento.py), [`src/confirmador_reglas.py`](src/confirmador_reglas.py), [`output/enriquecimiento_log.json`](output/enriquecimiento_log.json), [`output/snapshot_wallet.json`](output/snapshot_wallet.json)
- **Status** — `[ ] pending`
