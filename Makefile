# Makefile — Wallet + Knowledge Base
#
# Solo herramientas deterministas. El uso diario (registrar, consultar,
# informes) va por el MCP de Wallet dentro del agente.
#
# En Windows `make` no viene instalado. Usa el runner equivalente:
#   .\scripts\budget.ps1 help
#
# Nunca requiere Docker: si esta instalado, `make docker-shell` lo usa.

PY      := PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONPATH=tools python
DAYS    ?= 0
PLAN    ?=
CUENTA  ?=
INITIAL ?=
DELTA   ?=
EXPLICACION ?=
DESDE   ?=
HASTA   ?=
POR     ?= categoria

.PHONY: help doctor backup bootstrap reconcile ajustar agregar sync-skills test clean

help:
	@echo ""
	@echo "  WALLET + KNOWLEDGE BASE"
	@echo "  ======================="
	@echo "  make doctor        -> comprueba entorno, MCP y KB"
	@echo "  make backup        -> respaldo completo a output/"
	@echo "  make bootstrap     -> (re)genera rules/*.md  [DAYS=0]"
	@echo "  make agregar DESDE=YYYY-MM-DD [HASTA=...] [POR=categoria|mes|cuenta|etiqueta]"
	@echo "  make sync-skills   -> copia la skill de OpenCode a Hermes"
	@echo "  make reconcile PLAN=plans/x.json [DRY=1] [YES=1]"
	@echo "  make ajustar CUENTA=X INITIAL=N DELTA=N EXPLICACION='...' [DRY=1]"
	@echo "  make test          -> suite de tests"
	@echo "  make clean         -> borra caches y respaldos"
	@echo ""

doctor:
	@echo "Python:" && $(PY) --version
	@printf "tools/    : " && test -d tools && echo ok || echo FALTA
	@printf "rules/    : " && test -d rules && echo ok || echo FALTA
	@printf ".env      : " && test -f .env && echo presente || echo FALTA
	@printf "MCP       : " && (grep -q '"wallet"' opencode.json 2>/dev/null && echo configurado || echo FALTA)

backup:
	$(PY) tools/backup_wallet.py

bootstrap:
	$(PY) tools/bootstrap_rules.py --days $(DAYS) $(if $(DRY),--dry-run)

reconcile:
	@if [ -z "$(PLAN)" ]; then echo "Uso: make reconcile PLAN=plans/x.json [DRY=1] [YES=1]"; exit 1; fi
	$(PY) tools/conciliar_cuenta.py --plan "$(PLAN)" \
		$(if $(DRY),--dry-run) $(if $(YES),--yes)

ajustar:
	@if [ -z "$(CUENTA)" ] || [ -z "$(INITIAL)" ] || [ -z "$(EXPLICACION)" ]; then \
		echo "Uso: make ajustar CUENTA=X INITIAL=N DELTA=N EXPLICACION='texto' [DRY=1]"; exit 1; fi
	$(PY) tools/ajustar_saldo_cuenta.py \
		--cuenta "$(CUENTA)" \
		--initial-balance "$(INITIAL)" \
		$(if $(DELTA),--delta "$(DELTA)") \
		--explicacion "$(EXPLICACION)" \
		$(if $(DRY),--dry-run)

agregar:
	@if [ -z "$(DESDE)" ]; then echo "Uso: make agregar DESDE=YYYY-MM-DD [HASTA=...] [POR=categoria]"; exit 1; fi
	$(PY) tools/agregar_periodo.py --desde "$(DESDE)" $(if $(HASTA),--hasta "$(HASTA)") --por "$(POR)"

sync-skills:
	$(PY) tools/sync_skills.py

test:
	PYTHONUTF8=1 python -m pytest tests -q

clean:
	@echo "Limpiando caches y respaldos..."
	@rm -rf .pytest_cache tools/__pycache__ tests/__pycache__
	@rm -f output/backup_*.json output/backup_test.json
	@echo "Listo."
