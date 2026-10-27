FROM python:3.11-slim

# UTF-8 obligatorio: con locales cp1252 un print() con acentos falla y una
# operacion exitosa termina con exit code 1.
ENV PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/tools

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Docker es opcional. El uso diario va por el MCP de Wallet en el agente;
# este contenedor sirve para correr las herramientas deterministas:
#   docker compose run --rm wallet-tools python tools/bootstrap_rules.py
#   docker compose run --rm wallet-tools python tools/conciliar_cuenta.py --plan plans/x.json --dry-run
CMD ["python", "tools/backup_wallet.py"]
