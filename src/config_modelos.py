"""
Manejador de Modelos Gemini
============================
Punto único de configuración para todos los modelos Gemini del sistema.
Cada servicio tiene su propia variable de entorno para poder cambiar el
modelo sin tocar código.

Variables de entorno reconocidas (todas opcionales, tienen fallback):
  GEMINI_MODEL_ANALIZADOR    → modelo para analizador_finanzas.py
  GEMINI_MODEL_APRENDIZAJE   → modelo para aprendizaje_reglas.py
  GEMINI_MODEL_CONFIRMADOR   → modelo para confirmador_reglas.py (modificaciones)
  GEMINI_TEMPERATURA         → temperatura global (puede sobreescribirse por servicio)

Si se define GEMINI_MODEL (variable legacy), se usa como fallback para los
tres servicios antes de caer al hardcoded default.

El catálogo MODELOS_DISPONIBLES documenta los modelos soportados por la
Interactions API y generate_content. Se usa en el futuro dashboard para
poblar el selector de modelos sin hardcodear HTML.

Autor: Anderson Bedoya Ciro
Versión: 1.0
"""

import os
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Catálogo de modelos disponibles ──────────────────────────────────────────
# Cada entrada documenta: id de API, nombre legible, capacidades y si soporta
# Interactions API (vs solo generate_content).

@dataclass
class ModeloInfo:
    """Metadatos de un modelo Gemini."""
    id: str                          # Nombre exacto que acepta la API
    nombre: str                      # Nombre legible para UI
    descripcion: str                 # Descripción corta
    velocidad: str                   # "rapido" | "medio" | "lento"
    costo: str                       # "bajo" | "medio" | "alto"
    soporta_interactions: bool       # Soporta Interactions API
    soporta_generate_content: bool   # Soporta generate_content (models.generate_content)
    contexto_tokens: int             # Ventana de contexto en tokens
    recomendado_para: List[str]      # Servicios recomendados


MODELOS_DISPONIBLES: Dict[str, ModeloInfo] = {
    "gemini-3.1-flash-lite": ModeloInfo(
        id="gemini-3.1-flash-lite",
        nombre="Gemini 3.1 Flash Lite",
        descripcion="Modelo más ligero y rápido. Ideal para tareas repetitivas y económicas.",
        velocidad="rapido",
        costo="bajo",
        soporta_interactions=True,
        soporta_generate_content=True,
        contexto_tokens=1_000_000,
        recomendado_para=["analizador", "aprendizaje", "confirmador"],
    ),
    "gemini-3.5-flash": ModeloInfo(
        id="gemini-3.5-flash",
        nombre="Gemini 3.5 Flash",
        descripcion="Balance óptimo entre velocidad y capacidad de razonamiento.",
        velocidad="medio",
        costo="medio",
        soporta_interactions=True,
        soporta_generate_content=True,
        contexto_tokens=1_000_000,
        recomendado_para=["analizador", "aprendizaje", "confirmador"],
    ),
    "gemini-3.5-pro": ModeloInfo(
        id="gemini-3.5-pro",
        nombre="Gemini 3.5 Pro",
        descripcion="Mayor capacidad de análisis. Ideal para diagnósticos complejos.",
        velocidad="lento",
        costo="alto",
        soporta_interactions=True,
        soporta_generate_content=True,
        contexto_tokens=2_000_000,
        recomendado_para=["analizador"],
    ),
}

# ── Defaults por servicio ─────────────────────────────────────────────────────
_DEFAULT_GLOBAL        = "gemini-3.1-flash-lite"
_DEFAULT_ANALIZADOR    = "gemini-3.1-flash-lite"
_DEFAULT_APRENDIZAJE   = "gemini-3.1-flash-lite"
_DEFAULT_CONFIRMADOR   = "gemini-3.1-flash-lite"
_DEFAULT_TEMPERATURA   = 0.3


# ─────────────────────────────────────────────────────────────────────────────
# API PÚBLICA
# ─────────────────────────────────────────────────────────────────────────────

def modelo_analizador() -> str:
    """Devuelve el modelo configurado para analizador_finanzas.py."""
    return (
        os.getenv("GEMINI_MODEL_ANALIZADOR")
        or os.getenv("GEMINI_MODEL")
        or _DEFAULT_ANALIZADOR
    )


def modelo_aprendizaje() -> str:
    """Devuelve el modelo configurado para aprendizaje_reglas.py."""
    return (
        os.getenv("GEMINI_MODEL_APRENDIZAJE")
        or os.getenv("GEMINI_MODEL")
        or _DEFAULT_APRENDIZAJE
    )


def modelo_confirmador() -> str:
    """Devuelve el modelo configurado para confirmador_reglas.py (modificaciones)."""
    return (
        os.getenv("GEMINI_MODEL_CONFIRMADOR")
        or os.getenv("GEMINI_MODEL")
        or _DEFAULT_CONFIRMADOR
    )


def temperatura_global() -> float:
    """Devuelve la temperatura global configurada."""
    try:
        return float(os.getenv("GEMINI_TEMPERATURA", str(_DEFAULT_TEMPERATURA)))
    except ValueError:
        logger.warning("GEMINI_TEMPERATURA inválida, usando %.1f", _DEFAULT_TEMPERATURA)
        return _DEFAULT_TEMPERATURA


def config_activa() -> Dict:
    """
    Devuelve un diccionario con la configuración activa de todos los servicios.
    Útil para logging al inicio y para que el dashboard lea el estado actual.
    """
    return {
        "analizador":  modelo_analizador(),
        "aprendizaje": modelo_aprendizaje(),
        "confirmador": modelo_confirmador(),
        "temperatura": temperatura_global(),
    }


def guardar_config_activa(output_dir: str = "output") -> None:
    """
    Persiste la configuración activa en output/config_modelos_activa.json.
    El dashboard lo lee para mostrar qué modelo está en uso sin consultar
    variables de entorno directamente.
    """
    os.makedirs(output_dir, exist_ok=True)
    ruta = os.path.join(output_dir, "config_modelos_activa.json")
    data = {
        "config_activa": config_activa(),
        "catalogo": {k: asdict(v) for k, v in MODELOS_DISPONIBLES.items()},
    }
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    logger.debug("Configuración de modelos guardada en %s", ruta)


def info_modelo(model_id: str) -> Optional[ModeloInfo]:
    """Devuelve los metadatos de un modelo, o None si no está en el catálogo."""
    return MODELOS_DISPONIBLES.get(model_id)
