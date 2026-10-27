"""
Pipeline de Análisis Financiero Inteligente
============================================
Orquesta todos los servicios del sistema en secuencia, con logging
detallado, manejo de errores y resumen final.

Modos de ejecución:
  python run_pipeline.py                  → pipeline estándar (snapshot + analyze)
  python run_pipeline.py --full           → pipeline completo (+ learn + enrich)
  python run_pipeline.py --only snapshot  → solo un paso específico
  python run_pipeline.py --skip analyze   → saltarse un paso

Pasos disponibles (en orden):
  snapshot   → Extrae datos de Wallet y guarda snapshot histórico
  analyze    → Genera diagnóstico financiero con Gemini AI
  learn      → Aprende reglas contables desde el snapshot
  enrich     → Sugiere mejoras de notas/etiquetas/categorías (modo auto)

Uso con Docker (recomendado):
  docker-compose run --rm budget-pipeline
  docker-compose run --rm budget-pipeline --full
  docker-compose run --rm budget-pipeline --only snapshot

Autor: Anderson Bedoya Ciro
Versión: 1.0
"""

import os
import sys
import json
import time
import logging
import argparse
import subprocess
from datetime import datetime
from typing import List, Optional

import pytz
from dotenv import load_dotenv

load_dotenv()

# ── Zona horaria Colombia ─────────────────────────────────────────────────────
TZ_COLOMBIA = pytz.timezone("America/Bogota")


def _ahora() -> datetime:
    return datetime.now(TZ_COLOMBIA)


def _ts() -> str:
    return _ahora().strftime("%Y-%m-%d_%H-%M-%S")


# ── Rutas ─────────────────────────────────────────────────────────────────────
OUTPUT_DIR   = "output"
LOGS_DIR     = os.path.join(OUTPUT_DIR, "logs")

# ── Definición de pasos ───────────────────────────────────────────────────────
# Cada paso define: nombre legible, script a ejecutar y si es interactivo
PASOS = {
    "snapshot": {
        "nombre":      "Extracción de Snapshot",
        "script":      "src/gestor_snapshots.py",
        # RECORDS_LIMIT=0 -> sin tope: se pagina completo y luego se trunca
        "args_env":    ["--days", os.getenv("DAYS_BACK", "90"),
                        "--limit", os.getenv("RECORDS_LIMIT", "0") or "0"],
        "interactivo": False,
        "en_standard": True,
        "en_full":     True,
    },
    "analyze": {
        "nombre":      "Análisis Financiero con Gemini",
        "script":      "src/analizador_finanzas.py",
        "args_env":    [],
        "interactivo": False,
        "en_standard": True,
        "en_full":     True,
    },
    "learn": {
        "nombre":      "Aprendizaje de Reglas Contables",
        "script":      "src/aprendizaje_reglas.py",
        "args_env":    ["--max-registros", os.getenv("APRENDIZAJE_MAX_REGISTROS", "150"),
                        "--temperatura",   os.getenv("GEMINI_TEMPERATURA", "0.3")],
        "interactivo": False,
        "en_standard": False,
        "en_full":     True,
    },
    "enrich": {
        "nombre":      "Enriquecimiento de Registros",
        "script":      "src/asistente_enriquecimiento.py",
        "args_env":    ["--auto"],
        "interactivo": False,
        "en_standard": False,
        "en_full":     True,
    },
    "dashboard": {
        "nombre":      "Generación de Dashboard HTML",
        "script":      "src/generar_dashboard.py",
        "args_env":    [],
        "interactivo": False,
        "en_standard": True,
        "en_full":     True,
    },
}

ORDEN_PASOS = ["snapshot", "analyze", "learn", "enrich", "dashboard"]


# ─────────────────────────────────────────────────────────────────────────────
# LOGGING AL ARCHIVO Y CONSOLA
# ─────────────────────────────────────────────────────────────────────────────

def _configurar_logging(ts: str) -> str:
    """Configura logging a consola + archivo. Devuelve la ruta del log."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_path = os.path.join(LOGS_DIR, f"pipeline_{ts}.log")

    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt=date_fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )
    return log_path


logger = logging.getLogger("pipeline")


# ─────────────────────────────────────────────────────────────────────────────
# EJECUCIÓN DE UN PASO
# ─────────────────────────────────────────────────────────────────────────────

def ejecutar_paso(
    paso_id: str,
    extra_args: Optional[List[str]] = None,
) -> bool:
    """
    Ejecuta un paso del pipeline como subproceso Python.
    Devuelve True si tuvo éxito, False si falló.
    """
    paso = PASOS[paso_id]
    script = paso["script"]
    args = list(paso["args_env"]) + (extra_args or [])
    cmd = [sys.executable, script] + args

    logger.info("━" * 58)
    logger.info("▶  %s", paso["nombre"].upper())
    logger.info("   Comando: python %s %s", script, " ".join(str(a) for a in args))

    inicio = time.time()
    try:
        resultado = subprocess.run(
            cmd,
            check=False,      # manejamos el código de salida manualmente
            text=True,
            encoding="utf-8",
        )
        duracion = time.time() - inicio

        if resultado.returncode == 0:
            logger.info("   ✅ Completado en %.1fs", duracion)
            return True
        else:
            logger.error(
                "   ❌ Falló con código %d (%.1fs)",
                resultado.returncode, duracion,
            )
            return False

    except Exception as exc:
        duracion = time.time() - inicio
        logger.error("   ❌ Excepción inesperada (%.1fs): %s", duracion, exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def ejecutar_pipeline(
    pasos_a_ejecutar: List[str],
    continuar_en_error: bool = False,
) -> dict:
    """
    Ejecuta la lista de pasos en orden.

    Args:
        pasos_a_ejecutar:   Lista ordenada de IDs de pasos a correr.
        continuar_en_error: Si True, continúa aunque un paso falle.

    Returns:
        Resumen: {exitosos, fallidos, saltados, duracion_total_seg}
    """
    resumen = {
        "pasos": pasos_a_ejecutar,
        "resultados": {},
        "exitosos": 0,
        "fallidos":  0,
        "saltados":  0,
        "inicio":    _ahora().isoformat(),
    }

    t0_total = time.time()
    bloqueado = False

    for paso_id in pasos_a_ejecutar:
        if bloqueado:
            logger.warning("   ⏭️  Paso '%s' saltado por fallo anterior.", paso_id)
            resumen["resultados"][paso_id] = "saltado"
            resumen["saltados"] += 1
            continue

        exito = ejecutar_paso(paso_id)
        resumen["resultados"][paso_id] = "ok" if exito else "error"

        if exito:
            resumen["exitosos"] += 1
        else:
            resumen["fallidos"] += 1
            if not continuar_en_error:
                bloqueado = True

    resumen["duracion_total_seg"] = round(time.time() - t0_total, 1)
    resumen["fin"] = _ahora().isoformat()
    return resumen


# ─────────────────────────────────────────────────────────────────────────────
# GUARDAR RESUMEN
# ─────────────────────────────────────────────────────────────────────────────

def _guardar_resumen(resumen: dict, ts: str) -> str:
    """Persiste el resumen de ejecución en output/logs/."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    ruta = os.path.join(LOGS_DIR, f"pipeline_{ts}_resumen.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=4, ensure_ascii=False)
    return ruta


# ─────────────────────────────────────────────────────────────────────────────
# IMPRIMIR RESUMEN FINAL
# ─────────────────────────────────────────────────────────────────────────────

def _imprimir_resumen(resumen: dict, log_path: str, resumen_path: str) -> None:
    logger.info("━" * 58)
    logger.info("  RESUMEN DEL PIPELINE")
    logger.info("━" * 58)
    for paso_id, estado in resumen["resultados"].items():
        emoji = {"ok": "✅", "error": "❌", "saltado": "⏭️ "}.get(estado, "?")
        nombre = PASOS[paso_id]["nombre"]
        logger.info("  %s  %-35s → %s", emoji, nombre, estado.upper())
    logger.info("━" * 58)
    logger.info("  ✔  Exitosos  : %d", resumen["exitosos"])
    logger.info("  ✖  Fallidos  : %d", resumen["fallidos"])
    logger.info("  ⏭  Saltados  : %d", resumen["saltados"])
    logger.info("  ⏱  Duración  : %.1fs", resumen["duracion_total_seg"])
    logger.info("━" * 58)
    logger.info("  Log completo : %s", log_path)
    logger.info("  Resumen JSON : %s", resumen_path)


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pipeline de Análisis Financiero Inteligente.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python run_pipeline.py                      # snapshot + analyze
  python run_pipeline.py --full               # snapshot + analyze + learn + enrich
  python run_pipeline.py --only snapshot      # solo extracción
  python run_pipeline.py --only learn enrich  # solo aprendizaje y enriquecimiento
  python run_pipeline.py --skip enrich        # todo excepto enriquecimiento
  python run_pipeline.py --full --continuar   # no parar ante errores
        """,
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Ejecutar pipeline completo: snapshot + analyze + learn + enrich.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=ORDEN_PASOS,
        metavar="PASO",
        help=f"Ejecutar solo estos pasos. Opciones: {', '.join(ORDEN_PASOS)}",
    )
    parser.add_argument(
        "--skip",
        nargs="+",
        choices=ORDEN_PASOS,
        metavar="PASO",
        help="Saltarse estos pasos del pipeline seleccionado.",
    )
    parser.add_argument(
        "--continuar",
        action="store_true",
        help="Continuar el pipeline aunque un paso falle.",
    )
    args = parser.parse_args()

    ts = _ts()
    log_path = _configurar_logging(ts)

    logger.info("═" * 58)
    logger.info("  PIPELINE DE ANÁLISIS FINANCIERO INTELIGENTE")
    logger.info("  %s", _ahora().strftime("%Y-%m-%d %H:%M:%S %Z"))
    logger.info("═" * 58)

    # ── Determinar qué pasos ejecutar ────────────────────────────────────────
    if args.only:
        # Mantener orden canónico aunque el usuario los pida en otro orden
        pasos = [p for p in ORDEN_PASOS if p in args.only]
    elif args.full:
        pasos = [p for p in ORDEN_PASOS if PASOS[p]["en_full"]]
    else:
        pasos = [p for p in ORDEN_PASOS if PASOS[p]["en_standard"]]

    if args.skip:
        pasos = [p for p in pasos if p not in args.skip]

    if not pasos:
        logger.error("No hay pasos a ejecutar con los parámetros indicados.")
        sys.exit(1)

    logger.info("  Modo     : %s", "FULL" if args.full else ("CUSTOM" if args.only else "STANDARD"))
    logger.info("  Pasos    : %s", " → ".join(pasos))
    logger.info("  En error : %s", "continuar" if args.continuar else "detener")

    # ── Ejecutar ──────────────────────────────────────────────────────────────
    resumen = ejecutar_pipeline(pasos, continuar_en_error=args.continuar)

    # ── Guardar y mostrar resultado ───────────────────────────────────────────
    resumen_path = _guardar_resumen(resumen, ts)
    _imprimir_resumen(resumen, log_path, resumen_path)

    # Código de salida: 0 si todo bien, 1 si hubo fallos
    sys.exit(0 if resumen["fallidos"] == 0 else 1)
