"""
Asistente de Enriquecimiento de Registros
==========================================
Analiza el snapshot con Gemini AI y propone mejoras sobre los registros
existentes en BudgetBakers Wallet:

  1. NOTAS / CONTRAPARTE — sugiere descripciones legibles para registros
     que tienen nota vacía o críptica (ej. "TIENDA D1 MED CAMPO VA" →
     "Compras D1 Campo Valdés").

  2. ETIQUETAS — tres tipos de sugerencia:
     a. Asignar etiquetas faltantes a registros que deberían tenerlas.
     b. Eliminar etiquetas obsoletas (0 usos en el período analizado).
     c. Crear etiqueta nueva si el patrón lo justifica.

  3. CATEGORÍAS — re-categorizar registros marcados como "Unknown expense"
     o con categoría claramente incorrecta.

Flujo interactivo (mismo patrón que confirmador_reglas.py):
  - Gemini genera propuestas via Interactions API → JSON estructurado
  - El usuario revisa cada propuesta: [S]í / [N]o / [M]odificar
  - Las aprobadas se aplican en lote a la API de Wallet (PATCH /records,
    máx 10 por request) y se registran en output/enriquecimiento_log.json

Autor: Anderson Bedoya Ciro
Versión: 1.0
"""

import os
import json
import logging
import argparse
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pytz
import requests
from dotenv import load_dotenv
from google import genai

from config_modelos import modelo_aprendizaje, temperatura_global, guardar_config_activa
from logging_config import setup_logging, ahora_colombia

logger = setup_logging(__name__)

load_dotenv()

# ── Rutas ─────────────────────────────────────────────────────────────────────
OUTPUT_DIR       = "output"
SNAPSHOT_LATEST  = os.path.join(OUTPUT_DIR, "snapshot_wallet.json")
ENRIQ_LOG_PATH   = os.path.join(OUTPUT_DIR, "enriquecimiento_log.json")

# ── Config ────────────────────────────────────────────────────────────────────
MODELO_DEFAULT      = modelo_aprendizaje()
TEMPERATURA_DEFAULT = temperatura_global()
WALLET_BASE_URL     = "https://rest.budgetbakers.com/wallet/v1/api"
PATCH_BATCH_SIZE    = 10   # límite de la API


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA GEMINI — propuestas de enriquecimiento
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_PROPUESTAS = {
    "type": "object",
    "properties": {
        "propuestas": {
            "type": "array",
            "description": "Lista de propuestas de enriquecimiento sobre registros individuales",
            "items": {
                "type": "object",
                "properties": {
                    "record_id": {
                        "type": "string",
                        "description": "ID del registro a modificar"
                    },
                    "tipo": {
                        "type": "string",
                        "enum": ["nota", "etiqueta_agregar", "etiqueta_quitar", "categoria"],
                        "description": "Tipo de cambio propuesto"
                    },
                    "valor_actual": {
                        "type": "string",
                        "description": "Valor actual del campo (puede ser vacío)"
                    },
                    "valor_propuesto": {
                        "type": "string",
                        "description": "Nuevo valor sugerido para nota/categoría, o nombre del label para etiquetas"
                    },
                    "label_id": {
                        "type": "string",
                        "description": "ID del label cuando tipo=etiqueta_agregar o etiqueta_quitar. Vacío si es label nuevo a crear."
                    },
                    "justificacion": {
                        "type": "string",
                        "description": "Razón breve de la propuesta"
                    },
                    "confianza": {
                        "type": "number",
                        "description": "Nivel de confianza 0.0–1.0"
                    }
                },
                "required": ["record_id", "tipo", "valor_actual", "valor_propuesto", "justificacion", "confianza"]
            }
        },
        "etiquetas_obsoletas": {
            "type": "array",
            "description": "Etiquetas con 0 usos en el período que podrían eliminarse",
            "items": {
                "type": "object",
                "properties": {
                    "label_id":  {"type": "string"},
                    "nombre":    {"type": "string"},
                    "razon":     {"type": "string"}
                },
                "required": ["label_id", "nombre", "razon"]
            }
        },
        "etiquetas_nuevas": {
            "type": "array",
            "description": "Etiquetas nuevas que Gemini recomienda crear para cubrir patrones detectados",
            "items": {
                "type": "object",
                "properties": {
                    "nombre":        {"type": "string"},
                    "razon":         {"type": "string"},
                    "registros_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IDs de registros que recibirían esta etiqueta al crearla"
                    }
                },
                "required": ["nombre", "razon", "registros_ids"]
            }
        },
        "resumen": {
            "type": "string",
            "description": "Resumen ejecutivo del análisis: qué se encontró, cuántos registros mejorables"
        }
    },
    "required": ["propuestas", "etiquetas_obsoletas", "etiquetas_nuevas", "resumen"]
}

SYSTEM_INSTRUCTION = """Eres un Asistente de Calidad de Datos Financieros experto en finanzas personales colombianas.
Tu misión es revisar registros de gastos/ingresos y proponer mejoras concretas para hacerlos más descriptivos,
correctamente etiquetados y bien categorizados.

PRINCIPIOS:
1. Para NOTAS vacías o crípticas: propón una descripción legible en español.
    Ejemplos: "TIENDA D1 MED CAMPO VA" → "Compras D1 Campo Valdés"
              "DLO*Temu.com" → "Compra en Temu"
              "" (vacío, gasto en cuenta Nequi) → "Gasto Nequi"
2. Para ETIQUETAS faltantes: sugiere labels existentes cuando el patrón
    del registro coincida claramente (ej. nota menciona "Susana" → label susana).
3. Para ETIQUETAS OBSOLETAS: señala las que tienen 0 usos pero solo si tienen
    sentido eliminarlas (no etiquetas que simplemente no tuvieron actividad reciente).
4. Para CATEGORÍAS "Unknown expense": siempre propón una categoría mejor si el
    nombre de la nota/contraparte da pistas suficientes.
5. Solo propón cambios con confianza ≥ 0.70.
6. Prioriza registros sin nota Y sin categoría antes que los que ya tienen algo.
7. Máximo 30 propuestas por sesión para no saturar al usuario.
8. No repropongas cambios sobre registros marcados como [RECIENTEMENTE ENRIQUECIDO].
   Esos registros fueron modificados en una sesión reciente y deben mantenerse estables."""


# ─────────────────────────────────────────────────────────────────────────────
# CARGA DE DATOS
# ─────────────────────────────────────────────────────────────────────────────

def _cargar_snapshot() -> Dict[str, Any]:
    """Carga el snapshot más reciente. Lanza FileNotFoundError si no existe."""
    if not os.path.exists(SNAPSHOT_LATEST):
        raise FileNotFoundError(
            f"No se encontró {SNAPSHOT_LATEST}. Ejecuta budget-snapshot primero."
        )
    with open(SNAPSHOT_LATEST, "r", encoding="utf-8") as f:
        datos = json.load(f)
    return datos.get("data", datos)  # soporta envelope y formato plano


def _cargar_registros_enriquecidos_recientes(lookback: int = 2) -> set:
    """
    Carga los IDs de registros modificados en las últimas N sesiones de
    enriquecimiento para no reproponer cambios sobre ellos.
    """
    if not os.path.exists(ENRIQ_LOG_PATH):
        return set()
    try:
        with open(ENRIQ_LOG_PATH, "r", encoding="utf-8") as f:
            log = json.load(f)
        sesiones = log.get("sesiones", [])[-lookback:]
        ids = set()
        for s in sesiones:
            for p in s.get("parches_aplicados", []):
                rid = p.get("id")
                if rid:
                    ids.add(rid)
        return ids
    except Exception:
        return set()


def _construir_contexto(datos: Dict[str, Any], registros_recientes: set = None) -> str:
    """
    Construye el bloque de texto con los registros y catálogos para el prompt.
    Enfoca la atención de Gemini en los registros más deficientes.
    Excluye registros enriquecidos recientemente para no reproponer cambios.
    """
    registros_recientes = registros_recientes or set()
    registros = datos.get("registros", [])
    etiquetas  = datos.get("etiquetas", [])
    categorias = datos.get("categorias", [])

    # Mapa de uso de etiquetas (id → count)
    uso_labels: Dict[str, int] = {e["id"]: 0 for e in etiquetas}
    for r in registros:
        for et in r.get("etiquetas", []):
            if et.get("id") in uso_labels:
                uso_labels[et["id"]] += 1

    # Catálogos compactos
    labels_str = "\n".join(
        f"  {e['id']} | {e['nombre']} | usos={uso_labels.get(e['id'], 0)}"
        for e in etiquetas
    )

    cats_str = "\n".join(
        f"  {c['id']} | {c['nombre']} (grupo: {c.get('grupo', {}).get('nombre', '?')})"
        for c in categorias
        if not c.get("archivada", False)
    )[:3000]  # cap para no exceder contexto

    # Registros — priorizados: sin nota primero, luego sin etiquetas, luego Unknown
    def _prioridad(r: Dict) -> int:
        p = 0
        if not r.get("nota"):                                      p += 3
        if not r.get("etiquetas"):                                  p += 2
        if "Unknown" in (r.get("categoria", {}).get("nombre", "")): p += 2
        if r.get("id") in registros_recientes:                       p -= 10
        return -p  # más negativo = más prioritario

    registros_ordenados = sorted(registros, key=_prioridad)[:80]

    lineas = []
    for r in registros_ordenados:
        monto  = r.get("monto", {})
        cat    = r.get("categoria", {})
        etqs   = [e.get("nombre", "") for e in r.get("etiquetas", [])]
        marca = " [RECIENTEMENTE ENRIQUECIDO]" if r.get("id") in registros_recientes else ""
        lineas.append(
            f"[{r['id'][:8]}…{r['id'][-4:]}] "
            f"{r.get('fecha', '')[:10]} | "
            f"{r.get('tipo', '?').upper()} {monto.get('valor', 0):+.0f} {monto.get('moneda', 'COP')} | "
            f"cuenta='{r.get('cuenta', {}).get('nombre', '')}' | "
            f"nota='{r.get('nota', '')}' | "
            f"contraparte='{r.get('contraparte', '')}' | "
            f"cat='{cat.get('nombre', '')}' | "
            f"labels={etqs} | "
            f"id_completo='{r['id']}'"
            f"{marca}"
        )

    return f"""ETIQUETAS DISPONIBLES (id | nombre | usos_en_período):
{labels_str}

CATEGORÍAS DISPONIBLES (id | nombre):
{cats_str}

REGISTROS A ANALIZAR ({len(lineas)} priorizados de {len(registros)} total):
{chr(10).join(lineas)}"""


# ─────────────────────────────────────────────────────────────────────────────
# ANÁLISIS CON GEMINI
# ─────────────────────────────────────────────────────────────────────────────

def analizar_con_gemini(
    datos: Dict[str, Any],
    modelo: str = MODELO_DEFAULT,
    temperatura: float = TEMPERATURA_DEFAULT,
    registros_recientes: set = None,
) -> Tuple[Dict[str, Any], str]:
    """
    Envía el snapshot a Gemini y obtiene propuestas de enriquecimiento.

    Args:
        datos: Snapshot financiero.
        modelo: Modelo Gemini a usar.
        temperatura: Temperatura de generación.
        registros_recientes: IDs de registros enriquecidos recientemente para excluir.

    Returns:
        (resultado_parseado, interaction_id)
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY no configurada en .env")

    contexto = _construir_contexto(datos, registros_recientes=registros_recientes)
    prompt = f"""{contexto}

TAREA:
Analiza los registros anteriores y propón mejoras concretas:
1. Para registros con nota vacía o críptica → sugiere nota legible
2. Para registros sin etiquetas → asigna labels existentes si corresponde
3. Para registros con categoría "Unknown expense" → propón categoría correcta
4. Identifica etiquetas con 0 usos que podrían estar obsoletas
5. Propón etiquetas nuevas si ves patrones sin label disponible

Usa los IDs COMPLETOS (campo id_completo) en tus propuestas. Máximo 30 propuestas."""

    client = genai.Client(api_key=api_key)
    logger.info("   🤖 Analizando registros con Gemini (modelo=%s, temp=%.1f)…", modelo, temperatura)

    interaction = client.interactions.create(
        model=modelo,
        system_instruction=SYSTEM_INSTRUCTION,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": SCHEMA_PROPUESTAS,
        },
        generation_config={"temperature": temperatura},
    )

    if interaction.status != "completed":
        raise RuntimeError(f"Interacción no completada: {interaction.status}")

    logger.info("   ✅ Análisis completado. ID: %s", interaction.id)
    resultado = json.loads(interaction.output_text or "{}")
    return resultado, interaction.id


# ─────────────────────────────────────────────────────────────────────────────
# APLICACIÓN A LA API DE WALLET
# ─────────────────────────────────────────────────────────────────────────────

def _patch_records(
    parches: List[Dict[str, Any]],
    token: str,
) -> List[Dict[str, Any]]:
    """
    Envía un batch de hasta PATCH_BATCH_SIZE parches a PATCH /records.
    Devuelve la lista de resultados por ítem.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    # Deduplicar: fusionar parches del mismo record_id (evita "duplicate id" en la API)
    fusionados: Dict[str, Dict] = {}
    for p in parches:
        rid = p["id"]
        if rid not in fusionados:
            fusionados[rid] = dict(p)
        else:
            if "labelIds" in p and "labelIds" in fusionados[rid]:
                ex = fusionados[rid]["labelIds"]
                nu = p["labelIds"]
                if isinstance(ex, dict) and isinstance(nu, dict):
                    ex.setdefault("add", []).extend(nu.get("add", []))
                    ex.setdefault("remove", []).extend(nu.get("remove", []))
            elif "labelIds" in p:
                fusionados[rid]["labelIds"] = p["labelIds"]
            for k, v in p.items():
                if k not in ("id", "labelIds"):
                    fusionados[rid][k] = v
    parches_dedup = list(fusionados.values())
    logger.info("   parches: %d -> %d tras deduplicar", len(parches), len(parches_dedup))

    resultados = []
    for i in range(0, len(parches_dedup), PATCH_BATCH_SIZE):
        lote = parches_dedup[i: i + PATCH_BATCH_SIZE]
        resp = requests.patch(
            f"{WALLET_BASE_URL}/records",
            headers=headers,
            json=lote,
            timeout=30,
        )
        if resp.status_code in (200, 207):
            data = resp.json()
            resultados.extend(data.get("results", []))
        else:
            logger.error("Error PATCH /records: %s %s", resp.status_code, resp.text[:200])
            # Marcar todos los del lote como fallidos
            for p in lote:
                resultados.append({"id": p["id"], "success": False, "error": resp.text[:100]})
        # Respetar rate limit (500 req/h → ~0.14s entre llamadas)
        if i + PATCH_BATCH_SIZE < len(parches_dedup):
            time.sleep(0.5)
    return resultados


def _crear_label(nombre: str, token: str) -> Optional[str]:
    """
    Crea un nuevo label en Wallet. Devuelve su ID o None si falla.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = requests.post(
        f"{WALLET_BASE_URL}/labels",
        headers=headers,
        json={"name": nombre},   # POST /labels recibe objeto unico, no array
        timeout=15,
    )
    if resp.status_code in (200, 201):
        nuevo_id = resp.json().get("label", {}).get("id")
        if nuevo_id:
            logger.info("   Label '%s' creado con ID %s", nombre, nuevo_id)
            return nuevo_id
    logger.error("No se pudo crear label '%s': %s", nombre, resp.text[:200])
    return None


# ─────────────────────────────────────────────────────────────────────────────
# LOOP DE CONFIRMACIÓN INTERACTIVO
# ─────────────────────────────────────────────────────────────────────────────

def _leer(prompt: str) -> str:
    """Lee stdin con manejo de EOF."""
    try:
        return input(prompt)
    except EOFError:
        return ""


def _imprimir_propuesta(p: Dict[str, Any], idx: int, total: int) -> None:
    tipo_emoji = {
        "nota":           "📝",
        "etiqueta_agregar": "🏷️ +",
        "etiqueta_quitar":  "🏷️ -",
        "categoria":        "📂",
    }.get(p.get("tipo", ""), "❓")

    print(f"\n  [{idx}/{total}] {tipo_emoji}  {p.get('tipo', '').upper()}")
    print(f"  ID registro : …{p.get('record_id', '')[-12:]}")
    print(f"  Actual      : '{p.get('valor_actual', '')}'")
    print(f"  Propuesto   : '{p.get('valor_propuesto', '')}'")
    print(f"  Confianza   : {p.get('confianza', 0):.0%}")
    print(f"  Razón       : {p.get('justificacion', '')}")


def ejecutar_sesion(
    modelo: str = MODELO_DEFAULT,
    temperatura: float = TEMPERATURA_DEFAULT,
    solo_aplicar: bool = False,
) -> Dict[str, int]:
    """
    Flujo completo: análisis → revisión → aplicación.

    Args:
        modelo:        Modelo Gemini a usar.
        temperatura:   Temperatura de generación.
        solo_aplicar:  Si True, aplica todo sin preguntar (modo automático).

    Returns:
        Resumen de la sesión: {propuestas, aceptadas, rechazadas, aplicadas, fallidas}
    """
    token = os.getenv("WALLET_API_TOKEN")
    if not token:
        raise ValueError("WALLET_API_TOKEN no configurada en .env")

    # 1. Cargar snapshot
    datos = _cargar_snapshot()
    total_registros = len(datos.get("registros", []))
    logger.info("   📊 Snapshot cargado: %d registros", total_registros)

    registros_recientes = _cargar_registros_enriquecidos_recientes()
    if registros_recientes:
        logger.info("   🚫 Registros enriquecidos recientemente excluidos: %d", len(registros_recientes))

    # 2. Análisis con Gemini
    resultado, interaction_id = analizar_con_gemini(datos, modelo, temperatura, registros_recientes)

    propuestas        = resultado.get("propuestas", [])
    etiquetas_obs     = resultado.get("etiquetas_obsoletas", [])
    etiquetas_nuevas  = resultado.get("etiquetas_nuevas", [])
    resumen           = resultado.get("resumen", "")

    print(f"\n{'═' * 64}")
    print(f"  ASISTENTE DE ENRIQUECIMIENTO — {len(propuestas)} propuestas")
    print(f"{'─' * 64}")
    print(f"  {resumen}")
    print(f"{'═' * 64}")

    resumen_sesion = {
        "propuestas": len(propuestas),
        "aceptadas": 0, "rechazadas": 0,
        "aplicadas": 0, "fallidas": 0,
        "labels_creados": 0, "labels_obsoletos_marcados": 0,
    }

    # ── 3a. Revisión de etiquetas OBSOLETAS ──────────────────────────────────
    etiquetas_obs_unicas = []
    etiquetas_obs_vistas = set()
    for eo in etiquetas_obs:
        nombre = (eo.get("nombre", "") or "").strip()
        if nombre and nombre.casefold() not in etiquetas_obs_vistas:
            etiquetas_obs_unicas.append(eo)
            etiquetas_obs_vistas.add(nombre.casefold())
    etiquetas_obs = etiquetas_obs_unicas

    if etiquetas_obs:
        print(f"\n  🗑️  ETIQUETAS OBSOLETAS DETECTADAS ({len(etiquetas_obs)}):")
        for eo in etiquetas_obs:
            print(f"    • '{eo['nombre']}' — {eo['razon']}")
        if not solo_aplicar:
            resp = _leer("\n  ¿Registrar estas etiquetas obsoletas en el log para revisión posterior? [S/N]: ").upper()
            registrar_obs = resp == "S"
        else:
            registrar_obs = True
        if registrar_obs:
            resumen_sesion["labels_obsoletos_marcados"] = len(etiquetas_obs)
            print(f"  ✅ {len(etiquetas_obs)} etiquetas marcadas en el log.")

    # ── 3b. Etiquetas NUEVAS ──────────────────────────────────────────────────
    labels_nuevos_creados: Dict[str, str] = {}  # nombre → nuevo_id
    if etiquetas_nuevas:
        print(f"\n  ✨ ETIQUETAS NUEVAS RECOMENDADAS ({len(etiquetas_nuevas)}):")
        for en in etiquetas_nuevas:
            print(f"    • '{en['nombre']}' — {en['razon']} ({len(en.get('registros_ids', []))} registros afectados)")
        if not solo_aplicar:
            resp = _leer("\n  ¿Crear estas etiquetas nuevas en Wallet? [S/N]: ").upper()
            crear = resp == "S"
        else:
            crear = True
        if crear:
            for en in etiquetas_nuevas:
                nuevo_id = _crear_label(en["nombre"], token)
                if nuevo_id:
                    labels_nuevos_creados[en["nombre"]] = nuevo_id
                    resumen_sesion["labels_creados"] += 1
                    # Inyectar propuestas de asignación para sus registros
                    for rid in en.get("registros_ids", []):
                        propuestas.append({
                            "record_id": rid,
                            "tipo": "etiqueta_agregar",
                            "valor_actual": "",
                            "valor_propuesto": en["nombre"],
                            "label_id": nuevo_id,
                            "justificacion": f"Label nuevo '{en['nombre']}' creado en esta sesión",
                            "confianza": 1.0,
                            "_auto": True,
                        })

    # ── 3c. Revisión de propuestas de registros ───────────────────────────────
    # Construir mapa label_nombre → id desde snapshot + nuevos creados
    label_name_to_id: Dict[str, str] = {
        e["nombre"]: e["id"]
        for e in datos.get("etiquetas", [])
    }
    label_name_to_id.update(labels_nuevos_creados)

    parches_aprobados: List[Dict[str, Any]] = []  # acumulados para PATCH

    if propuestas:
        print(f"\n{'─' * 64}")
        print(f"  Revisa cada propuesta: [S]í aplicar / [N]o / [M]odificar valor")
        print(f"{'─' * 64}")

    for idx, prop in enumerate(propuestas, 1):
        if solo_aplicar or prop.get("_auto"):
            decision = "S"
        else:
            _imprimir_propuesta(prop, idx, len(propuestas))
            decision = _leer("  [S/N/M]: ").strip().upper()

        if decision == "N":
            resumen_sesion["rechazadas"] += 1
            continue

        if decision == "M":
            nuevo_valor = _leer(f"  Nuevo valor para '{prop['tipo']}': ").strip()
            if not nuevo_valor:
                resumen_sesion["rechazadas"] += 1
                continue
            prop["valor_propuesto"] = nuevo_valor

        # Construir parche según tipo
        parche = _construir_parche(prop, label_name_to_id, datos)
        if parche:
            parches_aprobados.append(parche)
            resumen_sesion["aceptadas"] += 1
        else:
            logger.warning("No se pudo construir parche para %s", prop.get("record_id", ""))
            resumen_sesion["rechazadas"] += 1

    # ── 4. Aplicar parches en lote ────────────────────────────────────────────
    if parches_aprobados:
        logger.info("   🚀 Aplicando %d cambios a Wallet API…", len(parches_aprobados))
        resultados_api = _patch_records(parches_aprobados, token)
        for res in resultados_api:
            if res.get("success"):
                resumen_sesion["aplicadas"] += 1
            else:
                resumen_sesion["fallidas"] += 1
                logger.warning("Fallo en registro %s: %s", res.get("id", "?"), res.get("error", ""))
        logger.info(
            "   ✅ Aplicados: %d | Fallidos: %d",
            resumen_sesion["aplicadas"], resumen_sesion["fallidas"],
        )
    else:
        logger.info("   ℹ️  Sin cambios a aplicar.")

    # ── 5. Guardar log ────────────────────────────────────────────────────────
    _guardar_log(
        interaction_id=interaction_id,
        propuestas=propuestas,
        parches=parches_aprobados,
        etiquetas_obsoletas=etiquetas_obs if etiquetas_obs else [],
        resumen_sesion=resumen_sesion,
        resumen_gemini=resumen,
    )

    return resumen_sesion


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _construir_parche(
    prop: Dict[str, Any],
    label_map: Dict[str, str],
    datos: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Traduce una propuesta aprobada al formato PatchRecordItem de la API.
    Devuelve None si no es posible construir el parche.
    """
    record_id = prop.get("record_id")
    if not record_id:
        return None

    tipo  = prop.get("tipo")
    valor = prop.get("valor_propuesto", "")

    parche: Dict[str, Any] = {"id": record_id}

    if tipo == "nota":
        parche["note"] = valor[:255]

    elif tipo == "etiqueta_agregar":
        # Preferir label_id ya conocido; si no, buscar por nombre
        label_id = prop.get("label_id") or label_map.get(valor)
        if not label_id:
            logger.warning("Label '%s' no encontrado, omitiendo parche", valor)
            return None
        parche["labelIds"] = {"add": [label_id]}

    elif tipo == "etiqueta_quitar":
        label_id = prop.get("label_id") or label_map.get(valor)
        if not label_id:
            return None
        parche["labelIds"] = {"remove": [label_id]}

    elif tipo == "categoria":
        # valor_propuesto debe ser el ID de categoría o el nombre; buscar por nombre
        cat_id = _buscar_categoria_id(valor, datos.get("categorias", []))
        if not cat_id:
            logger.warning("Categoría '%s' no encontrada en catálogo, omitiendo", valor)
            return None
        parche["categoryId"] = cat_id

    else:
        return None

    return parche


def _buscar_categoria_id(nombre_o_id: str, categorias: List[Dict]) -> Optional[str]:
    """
    Busca un ID de categoría por nombre exacto o por ID directo.
    Hace matching case-insensitive por nombre.
    """
    # Si ya es un UUID (36 chars con guiones)
    if len(nombre_o_id) == 36 and nombre_o_id.count("-") == 4:
        return nombre_o_id
    nombre_lower = nombre_o_id.lower().strip()
    for c in categorias:
        if c.get("nombre", "").lower() == nombre_lower:
            return c["id"]
        # también intentar match de nombre compuesto "grupo > subcategoria"
        nombre_completo = f"{c.get('grupo', {}).get('nombre', '')} > {c.get('nombre', '')}".lower()
        if nombre_completo == nombre_lower:
            return c["id"]
    return None


def _guardar_log(
    interaction_id: str,
    propuestas: List[Dict],
    parches: List[Dict],
    etiquetas_obsoletas: List[Dict],
    resumen_sesion: Dict[str, int],
    resumen_gemini: str,
) -> None:
    """Persiste el log de la sesión de enriquecimiento."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    log_existente: Dict[str, Any] = {"sesiones": []}
    if os.path.exists(ENRIQ_LOG_PATH):
        try:
            with open(ENRIQ_LOG_PATH, "r", encoding="utf-8") as f:
                log_existente = json.load(f)
        except Exception:
            pass

    sesion = {
        "timestamp":           ahora_colombia().isoformat(),
        "interaction_id":      interaction_id,
        "resumen_gemini":      resumen_gemini,
        "resumen_sesion":      resumen_sesion,
        "propuestas_total":    len(propuestas),
        "etiquetas_obsoletas": etiquetas_obsoletas,
        "parches_aplicados":   parches,
    }
    log_existente.setdefault("sesiones", []).append(sesion)
    log_existente["ultima_sesion"] = ahora_colombia().isoformat()

    with open(ENRIQ_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log_existente, f, indent=4, ensure_ascii=False)
    logger.info("   💾 Log guardado: %s", ENRIQ_LOG_PATH)


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Asistente de enriquecimiento de registros financieros con Gemini AI."
    )
    parser.add_argument(
        "--modelo",
        type=str,
        default=MODELO_DEFAULT,
        help=f"Modelo Gemini (default: {MODELO_DEFAULT}).",
    )
    parser.add_argument(
        "--temperatura",
        type=float,
        default=TEMPERATURA_DEFAULT,
        help=f"Temperatura de generación (default: {TEMPERATURA_DEFAULT}).",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Aplica todas las propuestas sin confirmación manual.",
    )
    args = parser.parse_args()

    guardar_config_activa()
    logger.info("✨ ASISTENTE DE ENRIQUECIMIENTO DE REGISTROS")
    logger.info("   Modelo: %s | Temperatura: %.1f | Modo: %s",
                args.modelo, args.temperatura, "AUTO" if args.auto else "INTERACTIVO")

    resumen = ejecutar_sesion(
        modelo=args.modelo,
        temperatura=args.temperatura,
        solo_aplicar=args.auto,
    )

    print(f"\n{'═' * 64}")
    print(f"  RESUMEN FINAL")
    print(f"{'─' * 64}")
    print(f"  📋 Propuestas generadas  : {resumen['propuestas']}")
    print(f"  ✅ Aceptadas             : {resumen['aceptadas']}")
    print(f"  ❌ Rechazadas            : {resumen['rechazadas']}")
    print(f"  🚀 Aplicadas en Wallet   : {resumen['aplicadas']}")
    print(f"  ⚠️  Fallidas en API       : {resumen['fallidas']}")
    print(f"  🏷️  Labels creados        : {resumen['labels_creados']}")
    print(f"  🗑️  Labels obsoletos      : {resumen['labels_obsoletos_marcados']}")
    print(f"{'═' * 64}")
    print(f"\n  Log guardado en: {ENRIQ_LOG_PATH}")
