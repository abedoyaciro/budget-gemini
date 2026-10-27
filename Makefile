# Makefile — Pipeline de Análisis Financiero Inteligente
# Autor: Anderson Bedoya Ciro
#
# Este Makefile funciona con Docker y SIN Docker:
#   * Si el daemon de Docker responde -> ejecuta en contenedor.
#   * Si no -> ejecuta nativamente con Python (PYTHONPATH=src).
#
# En Windows, `make` no viene instalado por defecto. Usa el runner nativo:
#   .\scripts\budget.ps1 help
#   .\scripts\budget.ps1 snapshot -Days 0
#   .\scripts\budget.ps1 reconcile -Plan plan.json
#
# Todas las invocaciones nativas fuerzan PYTHONUTF8=1 (cp1252 rompía los
# print con emoji y convertía una extracción exitosa en exit code 1).

.PHONY: help build snapshot analyze learn enrich confirm pipeline full \
        dashboard historial reglas logs clean reconcile ajustar test doctor

IMAGE := budget-gemini-app:latest

# Variables configurables
DAYS        ?= $(or $(DAYS_BACK),90)
LIMIT       ?= 0
MAX_REG     ?= $(or $(APRENDIZAJE_MAX_REGISTROS),150)
TEMPERATURA ?= $(or $(GEMINI_TEMPERATURA),0.3)

# ── Detección de entorno ────────────────────────────────────────────────────
# Si `docker info` falla (daemon apagado o docker ausente) se usa modo nativo.
DOCKER_OK := $(shell docker info >/dev/null 2>&1 && echo yes || echo no)

ifeq ($(DOCKER_OK),yes)
  MODE := docker
  DOCKER_RUN := docker run --rm --dns 8.8.8.8 --env-file .env \
                  -e PYTHONUTF8=1 \
                  -e PYTHONPATH=/app/src \
                  -e DAYS_BACK=$(DAYS) \
                  -e RECORDS_LIMIT=$(LIMIT) \
                  -e APRENDIZAJE_MAX_REGISTROS=$(MAX_REG) \
                  -e GEMINI_TEMPERATURA=$(TEMPERATURA) \
                  -v "$(CURDIR)/output:/app/output"
  DOCKER_RUN_TTY := docker run --rm -it --dns 8.8.8.8 --env-file .env \
                      -e PYTHONUTF8=1 \
                      -e PYTHONPATH=/app/src \
                      -v "$(CURDIR)/output:/app/output"
  OUTFILE_MOUNT :=
  PY := $(DOCKER_RUN) $(IMAGE) python
  PYT := $(DOCKER_RUN_TTY) $(IMAGE) python
else
  MODE := native
  # Entorno nativo: UTF-8 + src/ en el path de importación
  NATIVE_ENV := PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONPATH=src
  PY := $(NATIVE_ENV) python
  PYT := $(NATIVE_ENV) python
endif

# ────────────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  PIPELINE DE ANALISIS FINANCIERO INTELIGENTE  (modo: $(MODE))"
	@echo "  ============================================================"
	@echo "  make doctor       -> comprueba entorno (python/docker/.env)"
	@echo "  make build        -> construye la imagen Docker"
	@echo "  make snapshot     -> extrae datos de Wallet"
	@echo "  make analyze      -> diagnostico financiero con Gemini"
	@echo "  make learn        -> aprender reglas contables"
	@echo "  make enrich       -> enriquecer notas y etiquetas"
	@echo "  make confirm      -> confirmar/modificar reglas (interactivo)"
	@echo "  make dashboard    -> genera dashboard HTML"
	@echo "  make pipeline     -> snapshot + analyze"
	@echo "  make full         -> snapshot + analyze + learn + enrich"
	@echo "  make reconcile    -> concilia cuenta con un plan JSON"
	@echo "  make ajustar      -> ajusta initialBalance (partida de apertura)"
	@echo "  make historial    -> historial de snapshots"
	@echo "  make reglas       -> reglas aprendidas"
	@echo "  make logs         -> ultimo log del pipeline"
	@echo "  make test         -> ejecuta la suite de tests"
	@echo "  make clean        -> borra logs y archivos temporales"
	@echo ""
	@echo "  Variables: DAYS=90 LIMIT=0 TEMPERATURA=0.3"
	@echo "  DAYS=0  -> historico completo   LIMIT=0 -> sin tope de registros"
	@echo ""
	@echo "  Sin make (Windows): .\\scripts\\budget.ps1 help"
	@echo ""

## Comprueba el entorno disponible
doctor:
	@echo "Modo            : $(MODE)"
	@echo "Docker          : $(DOCKER_OK)"
	@command -v python >/dev/null 2>&1 && python --version || echo "python        : NO ENCONTRADO"
	@test -f .env && echo ".env            : presente" || echo ".env            : FALTA"
	@test -f output/snapshot_wallet.json && echo "snapshot        : presente" || echo "snapshot        : sin snapshot"

build:
	docker build -t $(IMAGE) .

## Extrae snapshot de Wallet (DAYS=0 -> historico completo)
snapshot:
	$(PY) -m gestor_snapshots --days $(DAYS) --limit $(LIMIT)

analyze:
	$(PY) -m analizador_finanzas

learn:
	$(PY) -m aprendizaje_reglas --max-registros $(MAX_REG) --temperatura $(TEMPERATURA)

enrich:
	$(PY) -m asistente_enriquecimiento --auto

confirm:
	$(PYT) -m confirmador_reglas

pipeline:
	$(PY) -m run_pipeline

full:
	$(PY) -m run_pipeline --full

dashboard:
	$(PY) -m generar_dashboard

## Concilia una cuenta con un plan JSON (no toca initialBalance)
## Uso: make reconcile PLAN=plan.json [DRY=1] [YES=1]
reconcile:
	@if [ -z "$(PLAN)" ]; then \
		echo "Uso: make reconcile PLAN=plan.json [DRY=1] [YES=1]"; exit 1; fi
	$(PYT) -m conciliar_cuenta --plan "$(PLAN)" \
		$(if $(DRY),--dry-run) $(if $(YES),--yes)

## Ajusta initialBalance como partida de apertura (exige delta + explicacion)
## Uso: make ajustar CUENTA=Pibank INITIAL=2580398.47 DELTA=2580400.24 \
##                  EXPLICACION="Residual de apertura pre-ventana" [DRY=1]
ajustar:
	@if [ -z "$(CUENTA)" ] || [ -z "$(INITIAL)" ] || [ -z "$(EXPLICACION)" ]; then \
		echo "Uso: make ajustar CUENTA=X INITIAL=N DELTA=N EXPLICACION='texto' [DRY=1]"; exit 1; fi
	$(PYT) -m ajustar_saldo_cuenta \
		--cuenta "$(CUENTA)" \
		--initial-balance "$(INITIAL)" \
		$(if $(DELTA),--delta "$(DELTA)") \
		--explicacion "$(EXPLICACION)" \
		$(if $(DRY),--dry-run)

historial:
	$(PY) -m gestor_snapshots --historial

reglas:
	$(PY) -m aprendizaje_reglas --mostrar-reglas

logs:
	@LAST=$$(ls -t output/logs/pipeline_*.log 2>/dev/null | head -1); \
	if [ -z "$$LAST" ]; then echo "No hay logs todavia."; \
	else echo "=== $$LAST ==="; cat "$$LAST"; fi

test:
	$(PY) -m pytest tests -q

clean:
	@echo "Limpiando logs..."
	@rm -f output/logs/pipeline_*.log output/logs/pipeline_*_resumen.json
	@echo "Listo."
