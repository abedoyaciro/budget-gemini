"""
Confirmador de Reglas Contables — Paso 4
=========================================
Sistema de confirmación interactiva para las reglas propuestas por Gemini.

Flujo por cada regla pendiente:
  1. Muestra la regla con su justificación y ejemplos.
  2. El usuario elige: [S]í / [N]o / [M]odificar
  3. Si S → estado = "confirmada", se guarda.
  4. Si N → estado = "rechazada", se registra el rechazo para que Gemini
            aprenda del patrón rechazado en futuras sesiones.
  5. Si M → se envía una nueva interacción a Gemini con
            previous_interaction_id apuntando a la interacción de análisis,
            para que ajuste la regla según las instrucciones del usuario.
            El resultado modificado se guarda como "confirmada".

Usa la Interactions API con previous_interaction_id para mantener el
contexto de la sesión sin repetir todo el historial de transacciones.

Autor: Anderson Bedoya Ciro
Versión: 1.0
"""

import os
import json
import logging
import argparse
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors

from logging_config import setup_logging, ahora_colombia

logger = setup_logging(__name__)

load_dotenv()

# ── Rutas ─────────────────────────────────────────────────────────────────────
OUTPUT_DIR          = "output"
REGLAS_PATH         = os.path.join(OUTPUT_DIR, "reglas_aprendidas.json")
HISTORIAL_INTER_DIR = os.path.join(OUTPUT_DIR, "historial_interacciones")

# ── Modelo ────────────────────────────────────────────────────────────────────
from config_modelos import modelo_confirmador, temperatura_global, guardar_config_activa

MODELO_DEFAULT      = modelo_confirmador()
TEMPERATURA_DEFAULT = temperatura_global()

# System instruction de respaldo para el modo fallback de reconstrucción de contexto
SYSTEM_INSTRUCTION_FALLBACK = (
    "Eres un Analista Contable Experto en finanzas personales colombianas. "
    "Modifica la regla contable según las instrucciones del usuario, "
    "manteniendo el mismo ID y formato JSON estructurado."
)

# ── JSON Schema para la respuesta de modificación ────────────────────────────
# Gemini devuelve la regla ajustada con el mismo esquema que la propuesta original.
SCHEMA_REGLA_MODIFICADA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "patron": {"type": "string"},
        "palabras_clave": {
            "type": "array",
            "items": {"type": "string"},
        },
        "accion": {
            "type": "object",
            "properties": {
                "categoria": {"type": "string"},
                "etiqueta":  {"type": "string"},
            },
            "required": ["categoria"],
        },
        "tipo_registro": {
            "type": "string",
            "enum": ["expense", "income", "any"],
        },
        "confianza":          {"type": "number"},
        "ejemplos":           {"type": "integer"},
        "monto_promedio_cop": {"type": "number"},
        "justificacion":      {"type": "string"},
        "explicacion_cambio": {
            "type": "string",
            "description": "Breve explicación de qué se cambió respecto a la propuesta original.",
        },
    },
    "required": [
        "id", "patron", "palabras_clave", "accion",
        "tipo_registro", "confianza", "ejemplos", "justificacion",
        "explicacion_cambio",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# PERSISTENCIA
# ─────────────────────────────────────────────────────────────────────────────

def _cargar_reglas() -> Dict[str, Any]:
    """Carga el archivo de reglas aprendidas. Devuelve estructura vacía si falla."""
    if os.path.exists(REGLAS_PATH):
        try:
            with open(REGLAS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("No se pudo leer reglas_aprendidas.json: %s", exc)
    return {"reglas": [], "historial_sesiones": []}


def _guardar_reglas(datos: Dict[str, Any]) -> None:
    """Persiste el archivo de reglas aprendidas."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(REGLAS_PATH, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)


def _guardar_historial(
    interaction_id: str,
    tipo: str,
    detalle: str,
) -> None:
    """Guarda un registro de auditoría de la sesión de confirmación."""
    os.makedirs(HISTORIAL_INTER_DIR, exist_ok=True)
    ts = ahora_colombia().strftime("%Y-%m-%d_%H-%M-%S")
    ruta = os.path.join(HISTORIAL_INTER_DIR, f"confirmacion_{ts}_{tipo}.json")
    registro = {
        "interaction_id": interaction_id,
        "tipo": tipo,
        "timestamp": ahora_colombia().isoformat(),
        "detalle": detalle,
    }
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(registro, f, indent=4, ensure_ascii=False)
    logger.debug("Historial de confirmación guardado: %s", ruta)


# ─────────────────────────────────────────────────────────────────────────────
# RECUPERACIÓN DE CONTEXTO LOCAL (fallback ante expiración del servidor)
# ─────────────────────────────────────────────────────────────────────────────

def _cargar_contexto_local(interaction_id: str) -> Optional[Dict]:
    """
    Busca en output/historial_interacciones/ el registro completo de una
    interacción por su ID. Devuelve el dict con prompt_completo y
    output_completo, o None si no existe localmente.

    Se usa como fallback cuando previous_interaction_id falla con 404
    (interacción expirada en el servidor de Gemini).
    """
    if not os.path.isdir(HISTORIAL_INTER_DIR):
        return None
    for nombre in os.listdir(HISTORIAL_INTER_DIR):
        if not nombre.endswith(".json"):
            continue
        ruta = os.path.join(HISTORIAL_INTER_DIR, nombre)
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
            if datos.get("interaction_id") == interaction_id:
                return datos
        except Exception:
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# MODIFICACIÓN CON GEMINI (previous_interaction_id)
# ─────────────────────────────────────────────────────────────────────────────

def _modificar_regla_con_gemini(
    regla_original: Dict[str, Any],
    instruccion_usuario: str,
    previous_interaction_id: str,
    modelo: str,
    temperatura: float,
) -> Dict[str, Any]:
    """
    Envía una nueva interacción a Gemini usando previous_interaction_id para
    mantener el contexto del análisis original y ajustar una regla específica.

    Args:
        regla_original:          La regla tal como fue propuesta por Gemini.
        instruccion_usuario:     Qué quiere cambiar el usuario (texto libre).
        previous_interaction_id: ID de la interacción de análisis original.
        modelo:                  Modelo Gemini a usar.
        temperatura:             Temperatura de generación.

    Returns:
        Diccionario con la regla ajustada.

    Raises:
        RuntimeError: Si la interacción no completa o el JSON es inválido.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY no configurada en .env")

    client = genai.Client(api_key=api_key)

    prompt = f"""La regla que propusiste anteriormente fue:

ID: {regla_original.get('id')}
Patrón: {regla_original.get('patron')}
Palabras clave: {regla_original.get('palabras_clave')}
Acción: categoría="{regla_original.get('accion', {}).get('categoria')}", etiqueta="{regla_original.get('accion', {}).get('etiqueta', '')}"
Tipo: {regla_original.get('tipo_registro')}
Confianza: {regla_original.get('confianza')}
Ejemplos: {regla_original.get('ejemplos')}
Justificación: {regla_original.get('justificacion')}

El usuario pide el siguiente ajuste:
{instruccion_usuario}

Devuelve la regla completa con los cambios solicitados. Mantén el mismo ID.
En el campo "explicacion_cambio" describe brevemente qué modificaste."""

    # ── Intentar con previous_interaction_id (contexto en servidor Gemini) ───
    # Si falla con 404, el servidor ya expiró la interacción (Free Tier: 1 día;
    # Paid Tier: 55 días). En ese caso reconstruimos el contexto localmente.
    usar_previous_id = bool(previous_interaction_id)
    interaction = None

    if usar_previous_id:
        logger.info(
            "   🔄 Enviando modificación con contexto remoto (id=%s…)…",
            previous_interaction_id[:20],
        )
        try:
            interaction = client.interactions.create(
                model=modelo,
                input=prompt,
                previous_interaction_id=previous_interaction_id,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": SCHEMA_REGLA_MODIFICADA,
                },
                generation_config={"temperature": temperatura},
            )
        except Exception as exc:
            # NotFoundError o cualquier error 404 → interacción expirada
            es_404 = "404" in str(exc) or "not_found" in str(exc).lower() or "not found" in str(exc).lower()
            if es_404:
                logger.warning(
                    "   ⚠️  Interacción %s expirada en servidor Gemini. "
                    "Reconstruyendo contexto desde historial local…",
                    previous_interaction_id[:20],
                )
                usar_previous_id = False
            else:
                raise

    if not usar_previous_id:
        # ── Fallback: reconstruir contexto desde el historial local ──────────
        contexto_local = _cargar_contexto_local(previous_interaction_id or "")
        if contexto_local:
            prompt_original = contexto_local.get("prompt_completo", "")
            output_original = contexto_local.get("output_completo", "")
            sistema_original = contexto_local.get("system_instruction", SYSTEM_INSTRUCTION_FALLBACK)
            # Reconstruir la conversación como texto: turno 1 + turno 2
            nl = "\n"
            prompt_reconstruido = (
                "CONTEXTO DE LA SESIÓN ANTERIOR (reconstruido localmente):" + nl + nl
                + "PROMPT ORIGINAL:" + nl + prompt_original + nl + nl
                + "RESPUESTA ORIGINAL DE GEMINI:" + nl + output_original + nl + nl
                + "AHORA EL USUARIO PIDE ESTE AJUSTE:" + nl + prompt
            )
            logger.info("   🔁 Contexto reconstruido desde historial local (%d chars)",
                        len(prompt_reconstruido))
        else:
            # Sin historial local: enviar solo la regla con el ajuste
            logger.warning(
                "   ⚠️  Sin historial local para %s — enviando solo la regla",
                previous_interaction_id,
            )
            prompt_reconstruido = prompt

        interaction = client.interactions.create(
            model=modelo,
            input=prompt_reconstruido,
            store=False,   # stateless: no tiene sentido cachear este fallback
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": SCHEMA_REGLA_MODIFICADA,
            },
            generation_config={"temperature": temperatura},
        )

    if interaction is None or interaction.status != "completed":
        raise RuntimeError(
            f"Interacción de modificación no completada. Estado: {getattr(interaction, 'status', 'None')}"
        )

    output_text = interaction.output_text or ""
    logger.info("   ✅ Modificación completada. ID: %s", interaction.id)

    try:
        regla_modificada = json.loads(output_text)
    except json.JSONDecodeError as exc:
        logger.error("Error al parsear JSON de modificación: %s", exc)
        raise

    _guardar_historial(
        interaction_id=interaction.id,
        tipo="modificacion",
        detalle=f"Regla {regla_original.get('id')} modificada. Instrucción: {instruccion_usuario}",
    )

    return regla_modificada, interaction.id


# ─────────────────────────────────────────────────────────────────────────────
# BUCLE DE CONFIRMACIÓN INTERACTIVO
# ─────────────────────────────────────────────────────────────────────────────

def confirmar_reglas(
    modelo: str = MODELO_DEFAULT,
    temperatura: float = TEMPERATURA_DEFAULT,
    solo_pendientes: bool = True,
) -> Dict[str, int]:
    """
    Presenta al usuario cada regla pendiente de confirmación y procesa su
    respuesta: Sí / No / Modificar.

    Args:
        modelo:          Modelo Gemini para solicitudes de modificación.
        temperatura:     Temperatura para solicitudes de modificación.
        solo_pendientes: Si True (default), solo muestra reglas con estado
                         "pendiente_confirmacion". Si False, muestra todas.

    Returns:
        Resumen: {"confirmadas": N, "rechazadas": N, "modificadas": N, "omitidas": N}
    """
    reglas_file = _cargar_reglas()
    reglas = reglas_file.get("reglas", [])

    pendientes = [
        r for r in reglas
        if not solo_pendientes or r.get("estado") == "pendiente_confirmacion"
    ]

    if not pendientes:
        print("✅ No hay reglas pendientes de confirmación.")
        return {"confirmadas": 0, "rechazadas": 0, "modificadas": 0, "omitidas": 0}

    print(f"\n{'═' * 62}")
    print(f"  CONFIRMACIÓN DE REGLAS CONTABLES — {len(pendientes)} pendientes")
    print(f"{'═' * 62}")
    print("  Para cada regla elige: [S]í confirmar / [N]o rechazar / [M]odificar")
    print(f"{'─' * 62}\n")

    resumen = {"confirmadas": 0, "rechazadas": 0, "modificadas": 0, "omitidas": 0}

    # Mapa id → índice en reglas para actualización in-place
    indice_por_id = {r["id"]: i for i, r in enumerate(reglas)}

    for regla in pendientes:
        _imprimir_regla(regla)

        respuesta = _leer_respuesta("[S/N/M]: ").strip().upper()

        if respuesta == "S":
            # ── Confirmar ─────────────────────────────────────────────────
            reglas[indice_por_id[regla["id"]]]["estado"] = "confirmada"
            reglas[indice_por_id[regla["id"]]]["confirmada_en"] = ahora_colombia().isoformat()
            resumen["confirmadas"] += 1
            print("  ✅ Regla confirmada.\n")
            _guardar_historial(
                interaction_id=regla.get("interaction_id_origen", ""),
                tipo="confirmacion",
                detalle=f"Regla {regla['id']} confirmada por el usuario.",
            )

        elif respuesta == "N":
            # ── Rechazar ──────────────────────────────────────────────────
            motivo = _leer_respuesta("  Motivo del rechazo (opcional, Enter para omitir): ").strip()
            reglas[indice_por_id[regla["id"]]]["estado"] = "rechazada"
            reglas[indice_por_id[regla["id"]]]["rechazada_en"] = ahora_colombia().isoformat()
            if motivo:
                reglas[indice_por_id[regla["id"]]]["motivo_rechazo"] = motivo
            resumen["rechazadas"] += 1
            print("  ❌ Regla rechazada.\n")
            _guardar_historial(
                interaction_id=regla.get("interaction_id_origen", ""),
                tipo="rechazo",
                detalle=f"Regla {regla['id']} rechazada. Motivo: {motivo or 'sin especificar'}",
            )

        elif respuesta == "M":
            # ── Modificar con Gemini ───────────────────────────────────────
            prev_id = regla.get("interaction_id_origen")
            if not prev_id:
                print("  ⚠️  Sin interaction_id_origen — no se puede enlazar contexto.")
                print("  Se usará una interacción sin contexto previo.\n")

            instruccion = _leer_respuesta("  ¿Qué cambiar? (describe el ajuste): ").strip()
            if not instruccion:
                print("  ⏭️  Sin instrucción — regla omitida.\n")
                resumen["omitidas"] += 1
                continue

            try:
                regla_mod, nuevo_id = _modificar_regla_con_gemini(
                    regla_original=regla,
                    instruccion_usuario=instruccion,
                    previous_interaction_id=prev_id or "",
                    modelo=modelo,
                    temperatura=temperatura,
                )
            except Exception as exc:
                print(f"  ⚠️  Error al modificar con Gemini: {exc}")
                print("  Regla omitida.\n")
                resumen["omitidas"] += 1
                continue

            print(f"\n  🔧 Regla modificada:")
            _imprimir_regla(regla_mod, prefijo="  ")
            print(f"  💬 Cambio: {regla_mod.get('explicacion_cambio', '')}\n")

            aceptar = _leer_respuesta("  ¿Aceptar la versión modificada? [S/N]: ").strip().upper()
            if aceptar == "S":
                # Preservar metadatos de trazabilidad
                regla_mod["aprendida_en"] = regla.get("aprendida_en")
                regla_mod["interaction_id_origen"] = prev_id
                regla_mod["interaction_id_modificacion"] = nuevo_id
                regla_mod["estado"] = "confirmada"
                regla_mod["confirmada_en"] = ahora_colombia().isoformat()
                reglas[indice_por_id[regla["id"]]] = regla_mod
                resumen["modificadas"] += 1
                print("  ✅ Versión modificada aceptada.\n")
            else:
                print("  ⏭️  Modificación descartada — regla queda pendiente.\n")
                resumen["omitidas"] += 1
        else:
            print("  ⏭️  Opción no reconocida — regla omitida.\n")
            resumen["omitidas"] += 1

        # Persistir después de cada decisión para no perder progreso
        reglas_file["reglas"] = reglas
        reglas_file["ultima_actualizacion"] = ahora_colombia().isoformat()
        _guardar_reglas(reglas_file)

    return resumen


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS DE PRESENTACIÓN
# ─────────────────────────────────────────────────────────────────────────────

def _imprimir_regla(regla: Dict[str, Any], prefijo: str = "") -> None:
    """Imprime una regla de forma legible en la consola."""
    accion = regla.get("accion", {})
    etq = f" + etiqueta '{accion.get('etiqueta')}'" if accion.get("etiqueta") else ""
    print(f"{prefijo}[{regla.get('id')}] {regla.get('patron')}")
    print(f"{prefijo}  → Categoría : {accion.get('categoria')}{etq}")
    print(f"{prefijo}  → Tipo      : {regla.get('tipo_registro', '?')}")
    print(f"{prefijo}  → Confianza : {regla.get('confianza', 0):.0%} ({regla.get('ejemplos', 0)} ejemplos)")
    if regla.get("monto_promedio_cop"):
        print(f"{prefijo}  → Monto avg : ${regla['monto_promedio_cop']:,.0f} COP")
    print(f"{prefijo}  → Palabras  : {regla.get('palabras_clave', [])}")
    print(f"{prefijo}  → Razón     : {regla.get('justificacion', '')}")


def _leer_respuesta(prompt: str) -> str:
    """Lee una línea de stdin con manejo de EOF (modo no interactivo)."""
    try:
        return input(prompt)
    except EOFError:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Confirma, rechaza o modifica reglas contables propuestas por Gemini AI."
    )
    parser.add_argument(
        "--todas",
        action="store_true",
        help="Procesa todas las reglas, no solo las pendientes.",
    )
    parser.add_argument(
        "--modelo",
        type=str,
        default=MODELO_DEFAULT,
        help=f"Modelo Gemini para modificaciones (default: {MODELO_DEFAULT}).",
    )
    parser.add_argument(
        "--temperatura",
        type=float,
        default=TEMPERATURA_DEFAULT,
        help=f"Temperatura para modificaciones (default: {TEMPERATURA_DEFAULT}).",
    )
    args = parser.parse_args()

    guardar_config_activa()
    logger.info("✍️  CONFIRMACIÓN DE REGLAS CONTABLES")
    logger.info("   Modelo para modificaciones: %s", args.modelo)

    resumen = confirmar_reglas(
        modelo=args.modelo,
        temperatura=args.temperatura,
        solo_pendientes=not args.todas,
    )

    print(f"\n{'═' * 62}")
    print(f"  RESUMEN DE SESIÓN")
    print(f"{'─' * 62}")
    print(f"  ✅ Confirmadas  : {resumen['confirmadas']}")
    print(f"  ❌ Rechazadas   : {resumen['rechazadas']}")
    print(f"  🔧 Modificadas  : {resumen['modificadas']}")
    print(f"  ⏭️  Omitidas     : {resumen['omitidas']}")
    print(f"{'═' * 62}")
    print(f"\n  Reglas actualizadas en: {REGLAS_PATH}")
