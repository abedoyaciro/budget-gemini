"""
Aprendizaje de Reglas Contables con Gemini Interactions API
============================================================
Analiza snapshots históricos para detectar patrones recurrentes en las
transacciones y propone reglas contables automáticas (categoría, etiqueta).

Usa la Interactions API de Gemini (NO generate_content) con:
- system_instruction: rol de analista contable
- response_format: TextResponseFormat con JSON schema
- generation_config: temperatura configurable

Las reglas propuestas se guardan en output/reglas_aprendidas.json con
estado "pendiente_confirmacion". Para confirmar/rechazar/modificar, usa:
    docker-compose run --rm budget-confirmar-reglas
El confirmador usa previous_interaction_id para mantener el contexto
de la sesión al solicitar ajustes a Gemini (ver confirmador_reglas.py).

Autor: Anderson Bedoya Ciro
Versión: 1.1
"""

import os
import json
import logging
import argparse
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from google import genai

from logging_config import setup_logging, ahora_colombia

logger = setup_logging(__name__)

load_dotenv()

# ── Rutas ─────────────────────────────────────────────────────────────────────
OUTPUT_DIR          = "output"
SNAPSHOTS_DIR       = os.path.join(OUTPUT_DIR, "snapshots")
REGLAS_PATH         = os.path.join(OUTPUT_DIR, "reglas_aprendidas.json")
SNAPSHOT_LATEST     = os.path.join(OUTPUT_DIR, "snapshot_wallet.json")
HISTORIAL_INTER_DIR = os.path.join(OUTPUT_DIR, "historial_interacciones")

# ── Modelo e hiperparámetros ──────────────────────────────────────────────────
from config_modelos import modelo_aprendizaje, temperatura_global, guardar_config_activa

MODELO_DEFAULT      = modelo_aprendizaje()
TEMPERATURA_DEFAULT = temperatura_global()
MAX_REGISTROS       = int(os.getenv("APRENDIZAJE_MAX_REGISTROS", "150"))


# ─────────────────────────────────────────────────────────────────────────────
# JSON SCHEMA para structured output de la Interactions API
# (TextResponseFormat con mime_type=application/json)
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_REGLAS = {
    "type": "object",
    "properties": {
        "reglas": {
            "type": "array",
            "description": "Lista de reglas contables detectadas",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Identificador único de la regla, formato rule_NNN"
                    },
                    "patron": {
                        "type": "string",
                        "description": "Descripción textual del patrón detectado, ej: 'nota contiene EDS o Terpel'"
                    },
                    "palabras_clave": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Palabras o fragmentos que identifican el patrón en la nota o contraparte"
                    },
                    "accion": {
                        "type": "object",
                        "properties": {
                            "categoria": {
                                "type": "string",
                                "description": "Nombre de categoría sugerida, ej: 'Vehicle > Fuel'"
                            },
                            "etiqueta": {
                                "type": "string",
                                "description": "Nombre de etiqueta sugerida, ej: 'Moto'. Vacío si no aplica."
                            }
                        },
                        "required": ["categoria"]
                    },
                    "tipo_registro": {
                        "type": "string",
                        "enum": ["expense", "income", "any"],
                        "description": "Tipo de registro al que aplica la regla"
                    },
                    "confianza": {
                        "type": "number",
                        "description": "Nivel de confianza entre 0.0 y 1.0"
                    },
                    "ejemplos": {
                        "type": "integer",
                        "description": "Número de transacciones que validan este patrón"
                    },
                    "monto_promedio_cop": {
                        "type": "number",
                        "description": "Monto promedio en COP de las transacciones que generaron esta regla. Null si es multidivisa."
                    },
                    "justificacion": {
                        "type": "string",
                        "description": "Explicación breve de por qué se propone esta regla"
                    }
                },
                "required": ["id", "patron", "palabras_clave", "accion", "tipo_registro", "confianza", "ejemplos", "justificacion"]
            }
        },
        "resumen_analisis": {
            "type": "string",
            "description": "Resumen breve del análisis realizado: patrones dominantes, calidad de categorización, observaciones"
        },
        "registros_analizados": {
            "type": "integer",
            "description": "Total de registros procesados en este análisis"
        }
    },
    "required": ["reglas", "resumen_analisis", "registros_analizados"]
}

SYSTEM_INSTRUCTION = """Eres un Analista Contable Experto especializado en finanzas personales colombianas.
Tu misión es analizar transacciones financieras reales y detectar patrones recurrentes
para proponer reglas contables automáticas.

PRINCIPIOS DE ANÁLISIS:
1. Agrupa transacciones por similitud en nota, contraparte o monto recurrente
2. Solo propón una regla si hay al menos 2 ejemplos claros del patrón
3. Prioriza patrones con alta frecuencia y confianza ≥ 0.7
4. Detecta específicamente:
   - Combustible/gasolina (EDS, Terpel, Primax) → Vehicle > Fuel + etiqueta Moto si hay moto
   - Plataformas de transporte (Uber, Didi, inDrive) → Vehicle > Rentals + etiqueta correspondiente
   - Transferencias recurrentes a personas → etiqueta con el nombre
   - Supermercados y tiendas (ARA, Éxito, D1, Justo&Bueno) → Food & Drinks > Groceries
   - Servicios de streaming/suscripciones → Life & Entertainment > Books, audio, subscription
   - Nómina / salario → Income > Wage, invoices + etiqueta IBM si aplica
5. Para cada regla, especifica palabras clave exactas que aparecen en las notas
6. Sé conservador con la confianza: 0.95+ solo si el patrón es inequívoco"""


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES DE PERSISTENCIA
# ─────────────────────────────────────────────────────────────────────────────

def _cargar_reglas_existentes() -> Dict[str, Any]:
    """Carga el archivo de reglas aprendidas o devuelve estructura vacía."""
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


def _guardar_historial_interaccion(
    interaction_id: str,
    tipo: str,
    entrada: str,
    salida: str,
    modelo: str = "",
    sistema: str = "",
) -> None:
    """
    Guarda el registro completo de una interacción en output/historial_interacciones/.

    Guarda prompt y output COMPLETOS (sin truncar) para poder reconstruir el
    contexto cuando el servidor de Gemini ya no retenga la interacción:
      - Free Tier:  1 día de retención
      - Paid Tier: 55 días de retención
    Si previous_interaction_id falla con 404, confirmador_reglas.py carga este
    archivo y reconstruye el contexto de forma local (modo fallback).
    """
    os.makedirs(HISTORIAL_INTER_DIR, exist_ok=True)
    ts = ahora_colombia().strftime("%Y-%m-%d_%H-%M-%S")
    ruta = os.path.join(HISTORIAL_INTER_DIR, f"interaccion_{ts}_{tipo}.json")
    registro = {
        "interaction_id": interaction_id,
        "tipo": tipo,
        "timestamp": ahora_colombia().isoformat(),
        "modelo": modelo,
        # Completos — necesarios para fallback cuando el servidor expire
        "prompt_completo": entrada,
        "output_completo": salida,
        # Resúmenes cortos para lectura humana rápida
        "entrada_resumen": entrada[:300],
        "salida_resumen": salida[:300],
    }
    if sistema:
        registro["system_instruction"] = sistema
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(registro, f, indent=4, ensure_ascii=False)
    logger.debug("Historial guardado: %s", ruta)


# ─────────────────────────────────────────────────────────────────────────────
# PREPARACIÓN DEL CONTEXTO
# ─────────────────────────────────────────────────────────────────────────────

def _cargar_snapshot_datos() -> Optional[Dict[str, Any]]:
    """
    Carga el snapshot más reciente disponible.
    Primero intenta el snapshot_wallet.json raíz (siempre es el más reciente);
    si no existe, busca en la carpeta snapshots/.
    """
    if os.path.exists(SNAPSHOT_LATEST):
        try:
            with open(SNAPSHOT_LATEST, "r", encoding="utf-8") as f:
                datos = json.load(f)
            # Puede ser un snapshot plano (data directa) o con envelope
            return datos.get("data", datos)
        except Exception as exc:
            logger.warning("No se pudo leer snapshot_wallet.json: %s", exc)

    # Fallback: último snapshot en carpeta
    if os.path.isdir(SNAPSHOTS_DIR):
        archivos = sorted([
            f for f in os.listdir(SNAPSHOTS_DIR)
            if f.startswith("snapshot_") and f.endswith(".json")
        ])
        if archivos:
            ruta = os.path.join(SNAPSHOTS_DIR, archivos[-1])
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    envelope = json.load(f)
                return envelope.get("data", envelope)
            except Exception as exc:
                logger.warning("No se pudo leer %s: %s", ruta, exc)

    return None


def _construir_contexto_registros(datos: Dict[str, Any], max_registros: int) -> str:
    """
    Construye el bloque de texto con los registros para el prompt.
    Omite campos innecesarios para reducir tokens.
    Solo incluye los más informativos: fecha, tipo, monto, nota, contraparte,
    cuenta, categoria, etiquetas.
    """
    registros = datos.get("registros", [])[:max_registros]

    # Resumen compacto de cuentas y categorías para contexto
    cuentas = {c["id"]: c["nombre"] for c in datos.get("cuentas", []) if c.get("id")}
    etiquetas_disponibles = [e["nombre"] for e in datos.get("etiquetas", []) if e.get("nombre")]
    categorias_disponibles = [
        f"{c['nombre']} (grupo: {c.get('grupo', {}).get('nombre', '?')})"
        for c in datos.get("categorias", [])
        if c.get("nombre") and not c.get("archivada", False)
    ]

    lineas_registros = []
    for r in registros:
        monto = r.get("monto", {})
        cat = r.get("categoria", {})
        etqs = [e.get("nombre", "") for e in r.get("etiquetas", [])]
        linea = (
            f"[{r.get('fecha', '')[:10]}] "
            f"{r.get('tipo', '?').upper()} "
            f"{monto.get('valor', 0):+.0f} {monto.get('moneda', 'COP')} | "
            f"nota='{r.get('nota', '')}' | "
            f"contraparte='{r.get('contraparte', '')}' | "
            f"cuenta='{r.get('cuenta', {}).get('nombre', '')}' | "
            f"categoria='{cat.get('nombre', 'Sin categoría')}' | "
            f"etiquetas={etqs}"
        )
        lineas_registros.append(linea)

    contexto = f"""ETIQUETAS DISPONIBLES EN EL SISTEMA: {', '.join(etiquetas_disponibles)}

CATEGORÍAS DISPONIBLES (resumen): {'; '.join(categorias_disponibles[:40])}
[... y más categorías disponibles en el sistema]

REGISTROS A ANALIZAR ({len(lineas_registros)} de {len(datos.get('registros', []))} total):
{chr(10).join(lineas_registros)}"""

    return contexto


def _construir_prompt_analisis(contexto_registros: str, reglas_existentes: List[Dict]) -> str:
    """Construye el prompt completo para la primera interacción de análisis."""
    reglas_ids_existentes = [r.get("id") for r in reglas_existentes]
    hay_reglas = len(reglas_existentes) > 0

    if hay_reglas:
        reglas_str = "\n".join([
            f"  - {r.get('id')}: '{r.get('patron')}' → {r.get('accion', {}).get('categoria')}"
            for r in reglas_existentes
        ])
        contexto_reglas = f"""REGLAS YA APRENDIDAS (NO duplicar, solo proponer nuevas o mejoradas):
{reglas_str}

IDs de reglas existentes a NO repetir: {reglas_ids_existentes}

"""
    else:
        contexto_reglas = "No hay reglas previas. Este es el primer análisis.\n\n"

    return f"""{contexto_reglas}{contexto_registros}

TAREA:
Analiza los registros anteriores y detecta patrones recurrentes para proponer reglas contables.
Genera reglas que permitan categorizar automáticamente futuras transacciones similares.
Enfócate en patrones con al menos 2 ocurrencias y alta confianza.
Asigna IDs secuenciales comenzando en rule_{len(reglas_existentes) + 1:03d}."""


# ─────────────────────────────────────────────────────────────────────────────
# MOTOR DE APRENDIZAJE
# ─────────────────────────────────────────────────────────────────────────────

def aprender_reglas(
    temperatura: float = TEMPERATURA_DEFAULT,
    max_registros: int = MAX_REGISTROS,
    modelo: str = MODELO_DEFAULT,
) -> Dict[str, Any]:
    """
    Analiza el snapshot actual con la Interactions API de Gemini y propone
    reglas contables nuevas. Devuelve el resultado parseado del JSON.

    Args:
        temperatura:   Temperatura de generación (0.2=preciso, 0.5=creativo).
        max_registros: Número máximo de registros a enviar al modelo.
        modelo:        Nombre del modelo Gemini a usar.

    Returns:
        Diccionario con {reglas, resumen_analisis, registros_analizados,
                         interaction_id, previous_interaction_id}
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY no configurada en .env")

    # ── Cargar datos ─────────────────────────────────────────────────────────
    datos = _cargar_snapshot_datos()
    if not datos:
        raise FileNotFoundError(
            "No se encontró ningún snapshot. Ejecuta budget-snapshot primero."
        )

    reglas_file = _cargar_reglas_existentes()
    reglas_existentes = reglas_file.get("reglas", [])
    logger.info("   📚 Reglas existentes: %d", len(reglas_existentes))

    total_registros = len(datos.get("registros", []))
    logger.info("   📊 Registros en snapshot: %d (usando %d)", total_registros, min(max_registros, total_registros))

    # ── Construir prompt ─────────────────────────────────────────────────────
    contexto = _construir_contexto_registros(datos, max_registros)
    prompt = _construir_prompt_analisis(contexto, reglas_existentes)

    # ── Llamada a la Interactions API ────────────────────────────────────────
    client = genai.Client(api_key=api_key)
    logger.info("   🤖 Enviando a Interactions API (modelo=%s, temp=%.1f)…", modelo, temperatura)

    interaction = client.interactions.create(
        model=modelo,
        system_instruction=SYSTEM_INSTRUCTION,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": SCHEMA_REGLAS,
        },
        generation_config={
            "temperature": temperatura,
        },
    )

    if interaction.status != "completed":
        raise RuntimeError(
            f"Interacción no completada. Estado: {interaction.status}"
        )

    interaction_id = interaction.id
    output_text = interaction.output_text or ""
    logger.info("   ✅ Interacción completada. ID: %s", interaction_id)

    # ── Parsear respuesta ─────────────────────────────────────────────────────
    try:
        resultado = json.loads(output_text)
    except json.JSONDecodeError as exc:
        logger.error("Error al parsear respuesta JSON de Gemini: %s", exc)
        logger.error("Respuesta recibida (primeros 500 chars): %s", output_text[:500])
        raise

    resultado["interaction_id"] = interaction_id
    resultado["previous_interaction_id"] = None  # primera interacción de la sesión

    # Guardar historial completo para fallback ante expiración del servidor
    _guardar_historial_interaccion(
        interaction_id=interaction_id,
        tipo="analisis",
        entrada=prompt,           # completo — necesario para reconstruir contexto
        salida=output_text,       # completo — la respuesta original de Gemini
        modelo=modelo,
        sistema=SYSTEM_INSTRUCTION,
    )

    return resultado


def guardar_reglas_nuevas(
    resultado: Dict[str, Any],
    solo_confirmadas: bool = False,
) -> int:
    """
    Fusiona las reglas propuestas por Gemini con las reglas existentes en disco.
    Evita duplicados por ID.

    Args:
        resultado:        Salida de aprender_reglas().
        solo_confirmadas: Si True, solo guarda reglas con estado='confirmada'.
                          Si False (default), guarda todas las propuestas.

    Returns:
        Número de reglas nuevas guardadas.
    """
    reglas_file = _cargar_reglas_existentes()
    reglas_actuales = reglas_file.get("reglas", [])
    ids_actuales = {r["id"] for r in reglas_actuales}

    nuevas_reglas = resultado.get("reglas", [])
    agregadas = 0

    for regla in nuevas_reglas:
        if solo_confirmadas and regla.get("estado") != "confirmada":
            continue
        if regla.get("id") in ids_actuales:
            logger.debug("Regla %s ya existe, omitiendo", regla.get("id"))
            continue

        # Enriquecer con metadatos de aprendizaje
        regla["aprendida_en"] = ahora_colombia().isoformat()
        regla["estado"] = regla.get("estado", "pendiente_confirmacion")
        regla["interaction_id_origen"] = resultado.get("interaction_id")

        reglas_actuales.append(regla)
        ids_actuales.add(regla["id"])
        agregadas += 1

    reglas_file["reglas"] = reglas_actuales
    reglas_file["ultima_actualizacion"] = ahora_colombia().isoformat()

    # Registrar sesión en historial
    sesion = {
        "timestamp": ahora_colombia().isoformat(),
        "interaction_id": resultado.get("interaction_id"),
        "registros_analizados": resultado.get("registros_analizados", 0),
        "reglas_propuestas": len(nuevas_reglas),
        "reglas_guardadas": agregadas,
        "resumen": resultado.get("resumen_analisis", ""),
    }
    reglas_file.setdefault("historial_sesiones", []).append(sesion)

    _guardar_reglas(reglas_file)
    logger.info("   💾 Reglas guardadas: %d nuevas (total: %d)", agregadas, len(reglas_actuales))
    return agregadas


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Aprende reglas contables automáticas analizando transacciones con Gemini AI."
    )
    parser.add_argument(
        "--temperatura",
        type=float,
        default=TEMPERATURA_DEFAULT,
        help=f"Temperatura de Gemini: 0.2=preciso, 0.5=creativo (default: {TEMPERATURA_DEFAULT}).",
    )
    parser.add_argument(
        "--max-registros",
        type=int,
        default=MAX_REGISTROS,
        help=f"Número máximo de registros a analizar (default: {MAX_REGISTROS}).",
    )
    parser.add_argument(
        "--modelo",
        type=str,
        default=MODELO_DEFAULT,
        help=f"Modelo Gemini a usar (default: {MODELO_DEFAULT}).",
    )
    parser.add_argument(
        "--mostrar-reglas",
        action="store_true",
        help="Muestra las reglas guardadas actualmente y sale.",
    )
    args = parser.parse_args()

    # ── Modo mostrar reglas ───────────────────────────────────────────────────
    if args.mostrar_reglas:
        reglas_file = _cargar_reglas_existentes()
        reglas = reglas_file.get("reglas", [])
        if not reglas:
            print("📭 No hay reglas aprendidas todavía.")
        else:
            print(f"\n📋 REGLAS APRENDIDAS ({len(reglas)} total)")
            print("   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for r in reglas:
                accion = r.get("accion", {})
                etq = f" + etiqueta '{accion.get('etiqueta')}'" if accion.get("etiqueta") else ""
                estado = r.get("estado", "?")
                emoji = "✅" if estado == "confirmada" else "⏳" if estado == "pendiente_confirmacion" else "❌"
                print(f"   {emoji} [{r.get('id')}] {r.get('patron')}")
                print(f"      → {accion.get('categoria')}{etq}")
                print(f"      Confianza: {r.get('confianza', 0):.0%} | Ejemplos: {r.get('ejemplos', 0)} | Estado: {estado}")
        raise SystemExit(0)

    # ── Aprendizaje ───────────────────────────────────────────────────────────
    guardar_config_activa()
    logger.info("🧠 APRENDIZAJE DE REGLAS CONTABLES")
    logger.info("   Modelo: %s | Temperatura: %.1f | Max registros: %d",
                args.modelo, args.temperatura, args.max_registros)

    resultado = aprender_reglas(
        temperatura=args.temperatura,
        max_registros=args.max_registros,
        modelo=args.modelo,
    )

    reglas_propuestas = resultado.get("reglas", [])

    print(f"\n🔍 ANÁLISIS COMPLETADO")
    print(f"   Registros analizados : {resultado.get('registros_analizados', 0)}")
    print(f"   Reglas propuestas    : {len(reglas_propuestas)}")
    print(f"   Interaction ID       : {resultado.get('interaction_id')}")
    print(f"\n📋 RESUMEN: {resultado.get('resumen_analisis', '')}\n")

    if reglas_propuestas:
        print("─" * 60)
        for r in reglas_propuestas:
            accion = r.get("accion", {})
            etq = f" + '{accion.get('etiqueta')}'" if accion.get("etiqueta") else ""
            print(f"\n[{r.get('id')}] {r.get('patron')}")
            print(f"  → Categoría: {accion.get('categoria')}{etq}")
            print(f"  → Confianza: {r.get('confianza', 0):.0%} ({r.get('ejemplos', 0)} ejemplos)")
            print(f"  → {r.get('justificacion', '')}")
        print("─" * 60)

    # Guardar todas las reglas como pendientes de confirmación
    guardadas = guardar_reglas_nuevas(resultado, solo_confirmadas=False)

    print(f"\n💾 {guardadas} reglas nuevas guardadas en output/reglas_aprendidas.json")
    print(f"   Estado: pendiente_confirmacion")
    print(f"\n💡 Para confirmar/rechazar reglas, ejecuta:")
    print(f"   docker-compose up budget-confirmar-reglas")
