FROM python:3.11-slim

# Establecer el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar el archivo de dependencias e instalarlas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código fuente
COPY . .

# Agregar src/ al PYTHONPATH para que los módulos se importen entre sí
ENV PYTHONPATH=/app/src

# Comando por defecto: gestor de snapshots (extrae + guarda histórico)
# Para extractor simple:  docker run ... python src/extractor_wallet.py
# Para análisis:          docker run ... python src/analizador_finanzas.py
CMD ["python", "src/gestor_snapshots.py"]