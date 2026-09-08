"""
Gestor de Snapshots Financieros
================================
Gestiona el ciclo de vida completo de snapshots: almacenamiento con timestamp,
detección de cambios entre versiones y acceso al histórico.

Integra directamente con WalletContextExtractor para extraer y guardar en un
solo paso. El snapshot_wallet.json raíz se actualiza siempre como copia del
último snapshot para mantener compatibilidad con el analizador existente.

Autor: Anderson Bedoya Ciro
Versión: 1.0
"""

import os
import json
import logging
import shutil
import argparse
from datetime import datetime
from typing import Any, Dict, Optional

from extractor_wallet import WalletContextExtractor

from logging_config import setup_logging, ahora_colombia


logger = setup_logging(__name__)

# ── Rutas base ────────────────────────────────────────────────────────────────
OUTPUT_DIR = "output"
SNAPSHOTS_DIR = os.path.join(OUTPUT_DIR, "snapshots")
DIAGNOSTICOS_DIR = os.path.join(OUTPUT_DIR, "diagnosticos")
SNAPSHOT_LATEST = os.path.join(OUTPUT_DIR, "snapshot_wallet.json")    # compatibilidad


def _ensure_dirs() -> None:
    """Crea los directorios necesarios si no existen."""
    for d in (OUTPUT_DIR, SNAPSHOTS_DIR, DIAGNOSTICOS_DIR):
        os.makedirs(d, exist_ok=True)


def _timestamp_str(dt: Optional[datetime] = None) -> str:
    """Devuelve timestamp en formato YYYY-MM-DD_HH-MM-SS (hora Colombia)."""
    return ahora_colombia().strftime("%Y-%m-%d_%H-%M-%S")


def _snapshot_filename(ts: str) -> str:
    return f"snapshot_{ts}.json"


def _listar_snapshots() -> list[str]:
    """
    Lista todos los archivos de snapshot ordenados del más antiguo al más reciente.
    Devuelve lista de rutas absolutas.
    """
    if not os.path.isdir(SNAPSHOTS_DIR):
        return []
    archivos = [
        os.path.join(SNAPSHOTS_DIR, f)
        for f in os.listdir(SNAPSHOTS_DIR)
        if f.startswith("snapshot_") and f.endswith(".json")
    ]
    archivos.sort()  # orden lexicográfico = cronológico por el formato de nombre
    return archivos


def _cargar_snapshot(ruta: str) -> Optional[Dict[str, Any]]:
    """Carga un snapshot desde disco. Devuelve None si falla."""
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("No se pudo leer snapshot '%s': %s", ruta, exc)
        return None


def _detectar_cambios(
    anterior: Dict[str, Any],
    actual: Dict[str, Any],
) -> Dict[str, int]:
    """
    Compara dos snapshots y devuelve un diccionario de cambios detectados.

    Compara por IDs para encontrar entidades nuevas o modificadas.
    """
    def ids(seccion: str, snap: Dict) -> set:
        return {item["id"] for item in snap.get(seccion, []) if item.get("id")}

    def ids_con_actualizacion(seccion: str, snap: Dict) -> Dict[str, str]:
        """Mapa id → updated_at para detección de modificaciones."""
        return {
            item["id"]: (item.get("actualizado_en") or "")
            for item in snap.get(seccion, [])
            if item.get("id")
        }

    # ── Registros ────────────────────────────────────────────────────────────
    ids_ant = ids("registros", anterior)
    ids_act = ids("registros", actual)
    nuevos_registros = len(ids_act - ids_ant)

    # Registros que existían antes y tienen distinto updated_at
    act_map = ids_con_actualizacion("registros", actual)
    ant_map = ids_con_actualizacion("registros", anterior)
    modificados = sum(
        1 for rid in (ids_ant & ids_act)
        if act_map.get(rid) != ant_map.get(rid)
    )

    # ── Categorías ───────────────────────────────────────────────────────────
    nuevas_categorias = len(ids("categorias", actual) - ids("categorias", anterior))

    # ── Etiquetas ────────────────────────────────────────────────────────────
    nuevas_etiquetas = len(ids("etiquetas", actual) - ids("etiquetas", anterior))

    # ── Cuentas ──────────────────────────────────────────────────────────────
    nuevas_cuentas = len(ids("cuentas", actual) - ids("cuentas", anterior))

    return {
        "nuevos_registros": nuevos_registros,
        "registros_modificados": modificados,
        "nuevas_categorias": nuevas_categorias,
        "nuevas_etiquetas": nuevas_etiquetas,
        "nuevas_cuentas": nuevas_cuentas,
    }


def guardar_snapshot(
    datos: Dict[str, Any],
    tipo_extraccion: str = "full",
) -> str:
    """
    Persiste un snapshot en output/snapshots/ con nombre timestamped,
    actualiza output/snapshot_wallet.json para compatibilidad con el analizador,
    e inyecta metadata de gestión (cambios detectados, snapshot anterior).

    Args:
        datos:           Snapshot crudo devuelto por WalletContextExtractor.
        tipo_extraccion: "full" o "incremental".

    Returns:
        Ruta del archivo guardado.
    """
    _ensure_dirs()

    ts = _timestamp_str()
    nombre_archivo = _snapshot_filename(ts)
    ruta_nueva = os.path.join(SNAPSHOTS_DIR, nombre_archivo)

    # ── Detectar snapshot anterior ───────────────────────────────────────────
    snapshots_existentes = _listar_snapshots()
    snapshot_anterior_nombre: Optional[str] = None
    cambios: Optional[Dict[str, int]] = None

    if snapshots_existentes:
        ruta_ant = snapshots_existentes[-1]
        snapshot_anterior_nombre = os.path.basename(ruta_ant)
        anterior = _cargar_snapshot(ruta_ant)
        if anterior and "data" in anterior:
            # Los snapshots guardados tienen estructura {metadata_gestion, data}
            cambios = _detectar_cambios(anterior["data"], datos)
        elif anterior:
            # Snapshot en formato plano (compatibilidad con v2.0.0)
            cambios = _detectar_cambios(anterior, datos)

    if cambios:
        logger.info(
            "   📊 Cambios detectados → %d nuevos registros, %d modificados, "
            "%d nuevas categorías, %d nuevas etiquetas",
            cambios["nuevos_registros"],
            cambios["registros_modificados"],
            cambios["nuevas_categorias"],
            cambios["nuevas_etiquetas"],
        )
    else:
        logger.info("   📊 Sin snapshot anterior — extracción inicial")

    # ── Construir envelope de gestión ────────────────────────────────────────
    envelope = {
        "metadata_gestion": {
            "timestamp": ahora_colombia().isoformat(),
            "tipo_extraccion": tipo_extraccion,
            "ventana_dias": datos.get("metadata", {}).get("ventana_dias"),
            "snapshot_anterior": snapshot_anterior_nombre,
            "cambios_detectados": cambios or {
                "nuevos_registros": len(datos.get("registros", [])),
                "registros_modificados": 0,
                "nuevas_categorias": len(datos.get("categorias", [])),
                "nuevas_etiquetas": len(datos.get("etiquetas", [])),
                "nuevas_cuentas": len(datos.get("cuentas", [])),
            },
        },
        "data": datos,
    }

    # ── Guardar snapshot con timestamp ───────────────────────────────────────
    with open(ruta_nueva, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=4, ensure_ascii=False)
    logger.info("   💾 Snapshot guardado: snapshots/%s", nombre_archivo)

    # ── Actualizar snapshot_wallet.json (compatibilidad con analizador) ───────
    # El analizador lee output/snapshot_wallet.json directamente; le pasamos
    # el contenido plano (la sección "data") para no romper compatibilidad.
    with open(SNAPSHOT_LATEST, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)
    logger.info("   🔗 snapshot_wallet.json actualizado (compatibilidad)")

    return ruta_nueva


def obtener_ultimo_snapshot() -> Optional[Dict[str, Any]]:
    """
    Devuelve el contenido del snapshot más reciente (sección 'data'),
    o None si no existe ninguno.
    """
    snapshots = _listar_snapshots()
    if not snapshots:
        return None
    envelope = _cargar_snapshot(snapshots[-1])
    if envelope and "data" in envelope:
        return envelope["data"]
    return envelope  # formato plano (compatibilidad)


def listar_historial() -> list[Dict[str, Any]]:
    """
    Devuelve un resumen del historial de snapshots disponibles.
    Cada entrada incluye: nombre, timestamp, tipo_extraccion, cambios_detectados,
    total_registros.
    """
    historial = []
    for ruta in _listar_snapshots():
        envelope = _cargar_snapshot(ruta)
        if not envelope:
            continue

        meta_gestion = envelope.get("metadata_gestion", {})
        datos = envelope.get("data", envelope)  # soporte formato plano
        estadisticas = datos.get("estadisticas", {})

        historial.append({
            "archivo": os.path.basename(ruta),
            "timestamp": meta_gestion.get("timestamp") or datos.get("metadata", {}).get("extraccion_timestamp"),
            "tipo_extraccion": meta_gestion.get("tipo_extraccion", "desconocido"),
            "ventana_dias": meta_gestion.get("ventana_dias"),
            "cambios_detectados": meta_gestion.get("cambios_detectados"),
            "total_registros": estadisticas.get("total_registros"),
            "total_cuentas": estadisticas.get("total_cuentas"),
        })
    return historial


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA — extrae + guarda snapshot en un solo comando
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Extrae y gestiona snapshots financieros de BudgetBakers Wallet."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.getenv("DAYS_BACK", 90)),
        help="Días hacia atrás para filtrar registros (0 = sin límite, default: 90).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("RECORDS_LIMIT", 200)),
        help="Número máximo de registros a obtener (default: 200).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Extracción completa (ignora --days, usa days=0).",
    )
    parser.add_argument(
        "--historial",
        action="store_true",
        help="Muestra el historial de snapshots disponibles y sale.",
    )
    args = parser.parse_args()

    # ── Modo historial ───────────────────────────────────────────────────────
    if args.historial:
        historial = listar_historial()
        if not historial:
            print("📭 No hay snapshots guardados todavía.")
        else:
            print(f"\n📚 HISTORIAL DE SNAPSHOTS ({len(historial)} disponibles)")
            print("   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for entry in reversed(historial):  # más reciente primero
                cambios = entry.get("cambios_detectados") or {}
                print(f"   📁 {entry['archivo']}")
                print(f"      Timestamp  : {entry['timestamp']}")
                print(f"      Tipo       : {entry['tipo_extraccion']}")
                print(f"      Registros  : {entry['total_registros']}")
                print(f"      Nuevos     : {cambios.get('nuevos_registros', '?')}")
                print()
        raise SystemExit(0)

    # ── Extracción y guardado ─────────────────────────────────────────────────
    TOKEN = os.getenv("WALLET_API_TOKEN")
    if not TOKEN:
        logger.error(
            "La variable WALLET_API_TOKEN no está configurada en .env\n"
            "Agrega: WALLET_API_TOKEN=tu_token_aquí"
        )
        raise SystemExit(1)

    days = 0 if args.full else args.days
    tipo = "full" if args.full or days == 0 else "incremental"

    logger.info(
        "🚀 Iniciando extracción %s | días=%d | límite=%d",
        tipo.upper(), days, args.limit,
    )

    extractor = WalletContextExtractor(TOKEN)
    datos = extractor.get_context_snapshot(records_limit=args.limit, days_back=days)
    ruta = guardar_snapshot(datos, tipo_extraccion=tipo)

    stats = datos["estadisticas"]
    meta = datos["metadata"]

    print(f"\n📊 RESUMEN DE EXTRACCIÓN (v{meta['version']})")
    print(f"   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"   📁 Cuentas          : {stats['total_cuentas']}")
    print(f"   🏷️  Categorías       : {stats['total_categorias']}")
    print(f"   🔖 Etiquetas        : {stats['total_etiquetas']}")
    print(f"   📝 Registros        : {stats['total_registros']}")
    print(f"   ── Ingresos         : {stats['registros_ingreso']}")
    print(f"   ── Gastos           : {stats['registros_gasto']}")
    print(f"   📅 Ventana          : últimos {meta['ventana_dias']} días")
    print(f"   ⏱️  Duración         : {meta['extraccion_duracion_segundos']:.2f} s")
    print(f"   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"   💵 Ingresos COP     : ${stats['suma_ingresos_cop']:,.0f}")
    print(f"   💸 Gastos COP       : ${stats['suma_gastos_cop']:,.0f}")
    print(f"   📈 Balance neto COP : ${stats['balance_neto_cop']:,.0f}")
    print(f"   💵 Ingresos USD     : ${stats.get('suma_ingresos_usd', 0):,.2f}")
    print(f"   💸 Gastos USD       : ${stats.get('suma_gastos_usd', 0):,.2f}")
    print(f"   📈 Balance neto USD : ${stats.get('balance_neto_usd', 0):,.2f}")
    if stats.get("tasa_usd_cop"):
        print(f"   💱 Tasa USD→COP     : ${stats['tasa_usd_cop']:,.2f}")
        print(f"   🌐 Balance global   : ${stats.get('balance_neto_global_cop', stats['balance_neto_cop']):,.0f} COP")
    print(f"\n✅ Snapshot guardado en: {ruta}")
    print(f"   snapshot_wallet.json actualizado para el analizador")
