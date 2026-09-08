"""
Logging centralizado y zona horaria Colombia
============================================
Punto único de configuración de logging para todos los módulos del proyecto.
También expone TZ_COLOMBIA y ahora_colombia() para eliminar duplicación.

Uso:
    from logging_config import setup_logging, ahora_colombia
    logger = setup_logging(__name__)
"""

import os
import logging
from datetime import datetime

import pytz

TZ_COLOMBIA = pytz.timezone("America/Bogota")


def ahora_colombia() -> datetime:
    """Devuelve la hora actual en zona horaria Colombia."""
    return datetime.now(TZ_COLOMBIA)


def setup_logging(name: str = "budget") -> logging.Logger:
    """
    Configura y devuelve un logger con formato estandarizado.

    Si la variable de entorno BUDGET_LOG_FILE está definida, escribe
    también a ese archivo además de la consola.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    log_file = os.getenv("BUDGET_LOG_FILE")
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger
