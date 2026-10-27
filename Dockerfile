FROM python:3.11-slim

# PYTHONUTF8 evita que print() con emoji/box-drawing reviente con
# UnicodeEncodeError en locales no UTF-8 (síntoma clásico en Windows: una
# extracción exitosa terminaba con exit code 1).
ENV PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# src/ en el path de importación para que los módulos se importen entre sí
ENV PYTHONPATH=/app/src

# Comando por defecto: gestor de snapshots (extrae + guarda histórico)
# Otros puntos de entrada:
#   python -m analizador_finanzas
#   python -m conciliar_cuenta --plan plan.json
#   python -m ajustar_saldo_cuenta --cuenta X --initial-balance N --explicacion "..."
CMD ["python", "-m", "gestor_snapshots"]
