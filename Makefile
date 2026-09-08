# ═══════════════════════════════════════════════════════════════════════════
#  Makefile — Pipeline de Análisis Financiero Inteligente
#  Autor: Anderson Bedoya Ciro
#
#  Uso:
#    make                  → muestra esta ayuda
#    make build            → construye la imagen Docker
#    make snapshot         → extrae datos de Wallet
#    make analyze          → genera diagnóstico financiero
#    make learn            → aprende reglas contables
#    make enrich           → enriquece notas/etiquetas (automático)
#    make confirm          → confirmar/rechazar/modificar reglas (interactivo)
#    make pipeline         → snapshot + analyze  (uso semanal recomendado)
#    make full             → snapshot + analyze + learn + enrich
#    make historial        → muestra historial de snapshots
#    make reglas           → muestra reglas aprendidas
#    make logs             → muestra los logs del último pipeline
# ═══════════════════════════════════════════════════════════════════════════

.PHONY: help build snapshot analyze learn enrich confirm pipeline full \
        historial reglas logs clean

# Imagen Docker
IMAGE := budget-gemini-app:latest

# Variables configurables desde la línea de comando
DAYS        ?= $(or $(DAYS_BACK),90)
LIMIT       ?= $(or $(RECORDS_LIMIT),200)
MAX_REG     ?= $(or $(APRENDIZAJE_MAX_REGISTROS),150)
TEMPERATURA ?= $(or $(GEMINI_TEMPERATURA),0.3)

# Flags base de docker run
DOCKER_RUN := docker run --rm --dns 8.8.8.8 --env-file .env \
               -e PYTHONPATH=/app/src \
               -e DAYS_BACK=$(DAYS) \
               -e RECORDS_LIMIT=$(LIMIT) \
               -e APRENDIZAJE_MAX_REGISTROS=$(MAX_REG) \
               -e GEMINI_TEMPERATURA=$(TEMPERATURA) \
               -v "$(CURDIR)/output:/app/output" \
               -v "$(CURDIR)/run_pipeline.py:/app/run_pipeline.py"

# Flags para servicios interactivos (necesitan TTY)
DOCKER_RUN_TTY := docker run --rm -it --dns 8.8.8.8 --env-file .env \
                   -e PYTHONPATH=/app/src \
                   -v "$(CURDIR)/output:/app/output"

# ─────────────────────────────────────────────────────────────────────────────

## Muestra esta ayuda
help:
	@echo ""
	@echo "  ╔══════════════════════════════════════════════════════════╗"
	@echo "  ║   PIPELINE DE ANÁLISIS FINANCIERO INTELIGENTE            ║"
	@echo "  ╠══════════════════════════════════════════════════════════╣"
	@echo "  ║  make build      → construir imagen Docker               ║"
	@echo "  ║  make snapshot   → extraer datos de Wallet               ║"
	@echo "  ║  make analyze    → diagnóstico financiero con Gemini     ║"
	@echo "  ║  make learn      → aprender reglas contables             ║"
	@echo "  ║  make enrich     → enriquecer notas y etiquetas          ║"
	@echo "  ║  make confirm    → confirmar/modificar reglas            ║"
	@echo "  ║  make pipeline   → snapshot + analyze  (estándar)        ║"
	@echo "  ║  make full       → pipeline completo + learn + enrich    ║"
	@echo "  ║  make historial  → historial de snapshots                ║"
	@echo "  ║  make reglas     → reglas aprendidas                     ║"
	@echo "  ║  make logs       → último log del pipeline               ║"
	@echo "  ║  make clean      → borrar logs y archivos temporales     ║"
	@echo "  ╚══════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "  Variables: DAYS=90 LIMIT=200 TEMPERATURA=0.3"
	@echo "  Ejemplo:   make pipeline DAYS=30"
	@echo ""

## Construir imagen Docker
build:
	docker build -t $(IMAGE) .

## Extraer snapshot de Wallet API
snapshot:
	$(DOCKER_RUN) $(IMAGE) python src/gestor_snapshots.py \
	  --days $(DAYS) --limit $(LIMIT)

## Generar diagnóstico financiero con Gemini
analyze:
	$(DOCKER_RUN) $(IMAGE) python src/analizador_finanzas.py

## Aprender reglas contables desde el snapshot
learn:
	$(DOCKER_RUN) $(IMAGE) python src/aprendizaje_reglas.py \
	  --max-registros $(MAX_REG) --temperatura $(TEMPERATURA)

## Enriquecer notas, etiquetas y categorías (modo automático)
enrich:
	$(DOCKER_RUN) $(IMAGE) python src/asistente_enriquecimiento.py --auto

## Confirmar/rechazar/modificar reglas (interactivo, requiere TTY)
confirm:
	$(DOCKER_RUN_TTY) -e PYTHONPATH=/app/src $(IMAGE) python src/confirmador_reglas.py

## Pipeline estándar: snapshot + analyze
pipeline:
	$(DOCKER_RUN) \
	  -v $(CURDIR)/run_pipeline.py:/app/run_pipeline.py \
	  $(IMAGE) python run_pipeline.py

## Pipeline completo: snapshot + analyze + learn + enrich
full:
	$(DOCKER_RUN) \
	  -v $(CURDIR)/run_pipeline.py:/app/run_pipeline.py \
	  $(IMAGE) python run_pipeline.py --full

## Generar dashboard HTML desde los JSONs de output/
dashboard:
	$(DOCKER_RUN) $(IMAGE) python src/generar_dashboard.py

## Mostrar historial de snapshots
historial:
	$(DOCKER_RUN) $(IMAGE) python src/gestor_snapshots.py --historial

## Mostrar reglas aprendidas
reglas:
	$(DOCKER_RUN) $(IMAGE) python src/aprendizaje_reglas.py --mostrar-reglas

## Mostrar el log del último pipeline ejecutado
logs:
	@LAST=$$(ls -t output/logs/pipeline_*.log 2>/dev/null | head -1); \
	if [ -z "$$LAST" ]; then \
	  echo "No hay logs disponibles todavía."; \
	else \
	  echo "=== $$LAST ==="; cat "$$LAST"; \
	fi

## Borrar logs y archivos temporales
clean:
	@echo "Limpiando logs..."
	@rm -f output/logs/pipeline_*.log output/logs/pipeline_*_resumen.json
	@echo "Listo."
