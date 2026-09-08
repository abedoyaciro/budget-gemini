"""
Analizador Financiero Inteligente con Google Gemini AI
======================================================
Genera diagnósticos financieros completos usando Gemini AI con MEMORIA:
  - Lee el snapshot más reciente (output/snapshot_wallet.json)
  - Incorpora el diagnóstico anterior (output/diagnosticos/diagnostico_latest.json)
  - Aplica las reglas contables aprendidas (output/reglas_aprendidas.json)
  - Incorpora los cambios detectados desde el último snapshot
  - Guarda el diagnóstico en output/diagnosticos/ con timestamp y actualiza
    output/diagnostico_inteligente.json para compatibilidad con el dashboard.

Autor: Anderson Bedoya Ciro
Versión: 3.0 — Con memoria histórica y consistencia entre análisis
"""

import os
import json
import shutil
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from config_modelos import modelo_analizador, temperatura_global, guardar_config_activa
from logging_config import setup_logging, ahora_colombia

logger = setup_logging(__name__)

# ── Rutas ─────────────────────────────────────────────────────────────────────
OUTPUT_DIR         = "output"
DIAGNOSTICOS_DIR   = os.path.join(OUTPUT_DIR, "diagnosticos")
SNAPSHOT_PATH      = os.path.join(OUTPUT_DIR, "snapshot_wallet.json")
DIAGNOSTICO_PATH   = os.path.join(OUTPUT_DIR, "diagnostico_inteligente.json")
DIAGNOSTICO_LATEST = os.path.join(DIAGNOSTICOS_DIR, "diagnostico_latest.json")
REGLAS_PATH        = os.path.join(OUTPUT_DIR, "reglas_aprendidas.json")


# ─────────────────────────────────────────────────────────────────────────────
# MODELOS PYDANTIC (Structured Outputs)
# ─────────────────────────────────────────────────────────────────────────────

class RecomendacionFinanciera(BaseModel):
    """Modelo para una recomendación financiera específica."""
    categoria_gasto: str = Field(
        description="Categoría general del gasto analizado (ej: Transporte, Alimentación, Entretenimiento)"
    )
    observacion: str = Field(
        description="Análisis detallado del patrón detectado en los registros financieros"
    )
    accion_sugerida: str = Field(
        description="Acción concreta y específica recomendada para optimizar este flujo de dinero"
    )
    prioridad: str = Field(
        description="Nivel de prioridad: Alta, Media o Baja",
        default="Media"
    )


class AlertaFinanciera(BaseModel):
    """Modelo para alertas importantes detectadas."""
    tipo: str = Field(
        description="Tipo de alerta: Gasto Excesivo, Oportunidad de Ahorro, Riesgo Financiero, Cambio Significativo"
    )
    descripcion: str = Field(
        description="Descripción detallada de la alerta"
    )
    impacto_estimado: str = Field(
        description="Impacto económico estimado (ej: $50,000 COP mensuales)"
    )


class CambioVsPeriodoAnterior(BaseModel):
    """Comparación con el período anterior."""
    categoria: str = Field(
        description="Categoría o área financiera comparada"
    )
    variacion: str = Field(
        description="Descripción de la variación detectada (ej: +15% en gastos de transporte)"
    )
    evaluacion: str = Field(
        description="Evaluación cualitativa: Positivo, Negativo, Neutral"
    )


class DiagnosticoFinanciero(BaseModel):
    """Modelo principal del diagnóstico financiero completo con memoria histórica."""

    resumen_ejecutivo: str = Field(
        description="Resumen ejecutivo de la situación financiera actual (2-3 párrafos). "
                    "Si hay diagnóstico previo, comenta la evolución desde entonces."
    )

    balance_general: str = Field(
        description="Análisis del balance entre ingresos y gastos con cifras específicas en COP. "
                    "Incluir tasa de ahorro y comparación con período anterior si está disponible."
    )

    patrones_transporte: str = Field(
        description="Análisis detallado de gastos en transporte (combustible, mantenimiento moto, plataformas)"
    )

    gastos_sociales_familiares: str = Field(
        description="Análisis de gastos compartidos o sociales (etiquetas: susana, familia, etc.)"
    )

    analisis_inversiones: str = Field(
        description="Evaluación de cuentas de inversión y ahorro (Trii, Tyba, Lulo X, Hapi, etc.) "
                    "con comparación de rendimiento vs período anterior si aplica."
    )

    mantenimiento_activos: str = Field(
        description="Alertas y análisis de mantenimiento de activos (Moto, vehículos, etc.)"
    )

    cambios_vs_periodo_anterior: List[CambioVsPeriodoAnterior] = Field(
        description="Lista de cambios significativos detectados respecto al período anterior. "
                    "Vacía si no hay diagnóstico previo.",
        default_factory=list
    )

    reglas_aplicadas: List[str] = Field(
        description="IDs de reglas contables aprendidas que se aplicaron en este análisis "
                    "(ej: ['rule_001', 'rule_002']). Vacío si no hay reglas.",
        default_factory=list
    )

    nuevos_patrones_sugeridos: str = Field(
        description="Patrones recurrentes detectados en los datos actuales que podrían convertirse "
                    "en nuevas reglas contables. 'Ninguno detectado' si no hay.",
        default="Ninguno detectado"
    )

    alertas: List[AlertaFinanciera] = Field(
        description="Lista de alertas importantes detectadas en el análisis",
        default_factory=list
    )

    recomendaciones: List[RecomendacionFinanciera] = Field(
        description="Lista de recomendaciones priorizadas basadas en los datos analizados"
    )

    oportunidades_ahorro: str = Field(
        description="Identificación de oportunidades concretas de ahorro mensual con cifras específicas"
    )

    proyeccion_mes_siguiente: str = Field(
        description="Proyección del balance esperado para el próximo mes basada en patrones actuales. "
                    "Incluir supuestos utilizados.",
        default="Insuficiente historial para proyectar"
    )

    fecha_analisis: str = Field(
        description="Fecha y hora del análisis en formato YYYY-MM-DD HH:MM:SS",
        default_factory=lambda: ahora_colombia().strftime("%Y-%m-%d %H:%M:%S")
    )


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES DE CARGA DE CONTEXTO HISTÓRICO
# ─────────────────────────────────────────────────────────────────────────────

def _cargar_json_seguro(ruta: str) -> Optional[Dict[str, Any]]:
    """Carga un JSON desde disco de forma segura. Devuelve None si falla."""
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("No se pudo leer %s: %s", ruta, exc)
        return None


def _cargar_diagnostico_anterior() -> Optional[Dict[str, Any]]:
    """
    Carga el diagnóstico más reciente disponible.
    Primero intenta diagnostico_latest.json; si no existe, usa diagnostico_inteligente.json.
    """
    diag = _cargar_json_seguro(DIAGNOSTICO_LATEST)
    if diag:
        logger.info("   📋 Diagnóstico anterior cargado: diagnostico_latest.json")
        return diag
    diag = _cargar_json_seguro(DIAGNOSTICO_PATH)
    if diag:
        logger.info("   📋 Diagnóstico anterior cargado: diagnostico_inteligente.json")
        return diag
    logger.info("   📋 Sin diagnóstico anterior — primer análisis")
    return None


def _cargar_reglas_confirmadas() -> List[Dict[str, Any]]:
    """Carga solo las reglas con estado 'confirmada' del archivo de reglas."""
    datos = _cargar_json_seguro(REGLAS_PATH)
    if not datos:
        return []
    todas = datos.get("reglas", [])
    confirmadas = [r for r in todas if r.get("estado") == "confirmada"]
    logger.info("   📐 Reglas confirmadas disponibles: %d / %d", len(confirmadas), len(todas))
    return confirmadas


def _obtener_cambios_detectados(snapshot_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extrae los cambios detectados desde el último snapshot.
    El snapshot_wallet.json es el snapshot plano (sin envelope), pero el gestor_snapshots
    guarda el envelope en snapshots/. Buscamos el último snapshot del historial.
    """
    snapshots_dir = os.path.join(OUTPUT_DIR, "snapshots")
    if not os.path.isdir(snapshots_dir):
        return None

    archivos = sorted([
        f for f in os.listdir(snapshots_dir)
        if f.startswith("snapshot_") and f.endswith(".json")
    ])
    if not archivos:
        return None

    # El más reciente
    ruta_ultimo = os.path.join(snapshots_dir, archivos[-1])
    envelope = _cargar_json_seguro(ruta_ultimo)
    if envelope and "metadata_gestion" in envelope:
        return envelope["metadata_gestion"].get("cambios_detectados")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUCTOR DEL PROMPT CON MEMORIA
# ─────────────────────────────────────────────────────────────────────────────

def construir_prompt_contextual(
    snapshot_data: Dict[str, Any],
    diagnostico_anterior: Optional[Dict[str, Any]],
    reglas_confirmadas: List[Dict[str, Any]],
    cambios_detectados: Optional[Dict[str, Any]],
) -> str:
    """
    Construye un prompt optimizado con memoria histórica para Gemini AI.

    Args:
        snapshot_data:       Snapshot financiero actual.
        diagnostico_anterior: Diagnóstico del período anterior (puede ser None).
        reglas_confirmadas:  Reglas contables confirmadas por el usuario.
        cambios_detectados:  Cambios detectados vs snapshot anterior.

    Returns:
        Prompt estructurado listo para enviar a Gemini.
    """
    # Estadísticas básicas del snapshot actual
    num_cuentas    = len(snapshot_data.get("cuentas", []))
    num_categorias = len(snapshot_data.get("categorias", []))
    num_etiquetas  = len(snapshot_data.get("etiquetas", []))
    num_registros  = len(snapshot_data.get("registros", []))
    stats          = snapshot_data.get("estadisticas", {})
    meta           = snapshot_data.get("metadata", {})

    nombres_cuentas   = [c.get("nombre", "") for c in snapshot_data.get("cuentas", [])]
    nombres_etiquetas = [e.get("nombre", "") for e in snapshot_data.get("etiquetas", [])]

    # ── Bloque de contexto histórico ─────────────────────────────────────────
    bloque_historico = ""

    if diagnostico_anterior:
        resumen_ant = diagnostico_anterior.get("resumen_ejecutivo", "")[:500]
        balance_ant = diagnostico_anterior.get("balance_general", "")[:400]
        fecha_ant   = diagnostico_anterior.get("fecha_analisis", "desconocida")
        bloque_historico += f"""
═══════════════════════════════════════════════════════════════
CONTEXTO HISTÓRICO — ANÁLISIS PREVIO
═══════════════════════════════════════════════════════════════
Fecha del análisis anterior: {fecha_ant}

Resumen ejecutivo anterior (extracto):
{resumen_ant}

Balance general anterior (extracto):
{balance_ant}
"""
        # Recomendaciones anteriores que vale recordar
        recs_ant = diagnostico_anterior.get("recomendaciones", [])
        if recs_ant:
            recs_texto = "\n".join([
                f"  - [{r.get('prioridad', '?')}] {r.get('categoria_gasto', '')}: {r.get('accion_sugerida', '')}"
                for r in recs_ant[:5]
            ])
            bloque_historico += f"\nRecomendaciones anteriores pendientes de revisar:\n{recs_texto}\n"

    if cambios_detectados:
        bloque_historico += f"""
CAMBIOS DETECTADOS VS SNAPSHOT ANTERIOR:
  - Nuevos registros    : {cambios_detectados.get("nuevos_registros", 0)}
  - Registros modificados: {cambios_detectados.get("registros_modificados", 0)}
  - Nuevas categorías   : {cambios_detectados.get("nuevas_categorias", 0)}
  - Nuevas etiquetas    : {cambios_detectados.get("nuevas_etiquetas", 0)}
  - Nuevas cuentas      : {cambios_detectados.get("nuevas_cuentas", 0)}
"""

    # ── Bloque de reglas aprendidas ───────────────────────────────────────────
    bloque_reglas = ""
    if reglas_confirmadas:
        reglas_texto = "\n".join([
            f"  [{r.get('id')}] {r.get('patron')} → "
            f"Categoría: {r.get('accion', {}).get('categoria', '?')}"
            + (f", Etiqueta: {r.get('accion', {}).get('etiqueta')}" if r.get('accion', {}).get('etiqueta') else "")
            + f" (confianza: {r.get('confianza', 0):.0%}, {r.get('ejemplos', 0)} ejemplos)"
            for r in reglas_confirmadas
        ])
        bloque_reglas = f"""
═══════════════════════════════════════════════════════════════
REGLAS CONTABLES APRENDIDAS Y CONFIRMADAS
═══════════════════════════════════════════════════════════════
Aplica estas reglas automáticamente al analizar transacciones:
{reglas_texto}

IDs de reglas a referenciar en el campo "reglas_aplicadas": {[r.get("id") for r in reglas_confirmadas]}
"""

    # ── Prompt principal ──────────────────────────────────────────────────────
    prompt = f"""
Eres un Analista Financiero Senior con MEMORIA de análisis previos, especializado en finanzas personales colombianas y optimización de presupuestos.
Tu objetivo es analizar los datos financieros del usuario, mantener CONSISTENCIA con diagnósticos anteriores y generar un diagnóstico completo, profesional y accionable.
{bloque_historico}
{bloque_reglas}
═══════════════════════════════════════════════════════════════
DATOS ACTUALES DEL PERÍODO
═══════════════════════════════════════════════════════════════
Período analizado: últimos {meta.get("ventana_dias", 90)} días
Timestamp extracción: {meta.get("extraccion_timestamp", "")}

RESUMEN ESTADÍSTICO:
  - Cuentas activas            : {num_cuentas} ({", ".join(nombres_cuentas)})
  - Categorías disponibles     : {num_categorias}
  - Etiquetas personales       : {num_etiquetas} ({", ".join(nombres_etiquetas)})
  - Registros analizados       : {num_registros}
  - Ingresos COP (período)     : ${stats.get("suma_ingresos_cop", 0):,.0f}
  - Gastos COP (período)       : ${stats.get("suma_gastos_cop", 0):,.0f}
  - Balance neto COP           : ${stats.get("balance_neto_cop", 0):,.0f}
  - Ingresos USD (período)     : ${stats.get("suma_ingresos_usd", 0):,.2f}
  - Gastos USD (período)       : ${stats.get("suma_gastos_usd", 0):,.2f}
  - Balance neto USD           : ${stats.get("balance_neto_usd", 0):,.2f}
  - Tasa USD→COP usada         : ${stats.get("tasa_usd_cop", 0):,.2f}
  - Balance neto global en COP : ${stats.get("balance_neto_global_cop", stats.get("balance_neto_cop", 0)):,.0f}
  - Balance cuentas COP        : ${stats.get("balance_cuentas_cop", 0):,.0f}
  - Balance cuentas USD        : ${stats.get("balance_cuentas_usd", 0):,.2f}
  - Balance cuentas USD en COP : ${stats.get("balance_cuentas_usd_en_cop", 0):,.0f}
  - Con etiquetas              : {stats.get("registros_con_etiquetas", 0)}
  - Transferencias             : {stats.get("registros_transferencia", 0)}
  - Sin categoría              : {stats.get("registros_sin_categoria", 0)}

SNAPSHOT COMPLETO (JSON con todos los registros, cuentas, categorías y etiquetas):
{json.dumps(snapshot_data, indent=2, ensure_ascii=False)}

═══════════════════════════════════════════════════════════════
INSTRUCCIONES DE ANÁLISIS
═══════════════════════════════════════════════════════════════

1. **CONSISTENCIA HISTÓRICA**: Si hay diagnóstico previo, evalúa la evolución.
   ¿Mejoró el balance? ¿Se siguieron las recomendaciones anteriores?
   Llena el campo "cambios_vs_periodo_anterior" con comparaciones concretas.

2. **REGLAS APRENDIDAS**: Aplica las reglas confirmadas para identificar transacciones.
   Lista en "reglas_aplicadas" los IDs de las reglas que pudiste verificar en los datos.

3. **NUEVOS PATRONES**: Si ves patrones recurrentes NO cubiertos por reglas existentes,
   descríbelos en "nuevos_patrones_sugeridos" para que el usuario los confirme.

4. **BALANCE GENERAL**: Calcula y analiza el flujo de ingresos vs gastos con:
   - Tasa de ahorro = (ingresos - gastos) / ingresos × 100
   - Comparación con período anterior si disponible
   - Considera tanto COP nativo como USD convertido a COP con la tasa provista en el snapshot
   - Cuando menciones cuentas o balances en USD, muestra también su equivalente actual en COP

5. **PATRONES DE TRANSPORTE**: Busca combustible, mantenimiento moto, plataformas.
   Calcula gasto mensual promedio en transporte, incluyendo consumos en USD convertidos a COP si existen.

6. **GASTOS SOCIALES/FAMILIARES**: Transacciones con etiquetas susana, familia, etc.
   Analiza si son gastos discrecionales o compromisos, incorporando USD cuando aplique.

7. **INVERSIONES**: Evalúa Trii, Tyba, Lulo X, Hapi, Pibank.
   Si hay cuentas o movimientos en USD, analiza saldo en USD, equivalente en COP y su impacto sobre el patrimonio total.

8. **PROYECCIÓN**: Basado en los patrones actuales, proyecta el balance del próximo mes.
   Incluye la implicación de saldos o flujos en USD cuando sea relevante.

9. **ALERTAS**: Detecta gastos excesivos, riesgos, exposición cambiaria y oportunidades de ahorro inmediatas.

10. **RECOMENDACIONES**: Acciones concretas, ordenadas por impacto y urgencia.
   Si propones acciones sobre cuentas USD, explica el efecto esperado en USD y en COP equivalente.

IMPORTANTE:
- Usa cifras específicas en COP cuando sea posible
- Cuando haya USD relevante, muestra ambas vistas: USD nominal y COP equivalente
- Sé directo y profesional
- Identifica patrones ocultos en los datos
- Considera el contexto colombiano (COP como moneda principal)
- Diferencia entre gastos fijos, variables y discrecionales
- No ignores cuentas o movimientos en USD: intégralos explícitamente en el razonamiento

Genera un diagnóstico completo siguiendo estrictamente el esquema JSON solicitado.
"""

    return prompt


# ─────────────────────────────────────────────────────────────────────────────
# VALIDACIÓN Y PERSISTENCIA
# ─────────────────────────────────────────────────────────────────────────────

def validar_snapshot(snapshot_data: Dict) -> bool:
    """Valida que el snapshot tenga la estructura mínima requerida."""
    campos_requeridos = ["cuentas", "categorias", "etiquetas", "registros"]
    for campo in campos_requeridos:
        if campo not in snapshot_data:
            logger.error("Falta el campo '%s' en el snapshot", campo)
            return False
        if not isinstance(snapshot_data[campo], list):
            logger.error("El campo '%s' debe ser una lista", campo)
            return False
    if len(snapshot_data["registros"]) == 0:
        logger.warning("No hay registros en el snapshot")
        return False
    return True


def guardar_diagnostico(diagnostico_json: Dict[str, Any]) -> str:
    """
    Guarda el diagnóstico en output/diagnosticos/ con timestamp y actualiza
    output/diagnostico_inteligente.json para compatibilidad con el dashboard.

    Returns:
        Ruta del archivo con timestamp guardado.
    """
    os.makedirs(DIAGNOSTICOS_DIR, exist_ok=True)

    ts = ahora_colombia().strftime("%Y-%m-%d_%H-%M-%S")
    nombre_archivo = f"diagnostico_{ts}.json"
    ruta_ts = os.path.join(DIAGNOSTICOS_DIR, nombre_archivo)

    # Guardar con timestamp
    with open(ruta_ts, "w", encoding="utf-8") as f:
        json.dump(diagnostico_json, f, indent=4, ensure_ascii=False)
    logger.info("   💾 Diagnóstico guardado: diagnosticos/%s", nombre_archivo)

    # Actualizar diagnostico_latest.json
    with open(DIAGNOSTICO_LATEST, "w", encoding="utf-8") as f:
        json.dump(diagnostico_json, f, indent=4, ensure_ascii=False)
    logger.info("   🔗 diagnostico_latest.json actualizado")

    # Compatibilidad con dashboard (output/diagnostico_inteligente.json)
    with open(DIAGNOSTICO_PATH, "w", encoding="utf-8") as f:
        json.dump(diagnostico_json, f, indent=4, ensure_ascii=False)
    logger.info("   🔗 diagnostico_inteligente.json actualizado (compatibilidad)")

    return ruta_ts


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def analizar_snapshot_financiero() -> None:
    """Función principal que ejecuta el análisis financiero completo con memoria."""

    print("\n" + "=" * 70)
    print("🧠 ANALIZADOR FINANCIERO INTELIGENTE — v3.0 (con Memoria)")
    print("=" * 70 + "\n")

    load_dotenv()
    guardar_config_activa()

    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        logger.error("GEMINI_API_KEY no configurada en el archivo .env")
        return

    logger.info("✅ API Key de Gemini cargada")

    # ── 1. Cargar snapshot actual ─────────────────────────────────────────────
    if not os.path.exists(SNAPSHOT_PATH):
        logger.error(
            "No se encontró '%s'. Ejecuta primero: python src/gestor_snapshots.py",
            SNAPSHOT_PATH,
        )
        return

    try:
        with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            snapshot_raw = json.load(f)
        # Soporta envelope {data:...} y formato plano
        snapshot_data = snapshot_raw.get("data", snapshot_raw)
        logger.info("✅ Snapshot cargado: %d registros", len(snapshot_data.get("registros", [])))
    except Exception as exc:
        logger.error("Error al leer el snapshot: %s", exc)
        return

    if not validar_snapshot(snapshot_data):
        logger.error("El snapshot no tiene la estructura correcta")
        return

    # ── 2. Cargar contexto histórico ──────────────────────────────────────────
    logger.info("📚 Cargando contexto histórico…")
    diagnostico_anterior = _cargar_diagnostico_anterior()
    reglas_confirmadas   = _cargar_reglas_confirmadas()
    cambios_detectados   = _obtener_cambios_detectados(snapshot_data)

    tiene_memoria = diagnostico_anterior is not None or len(reglas_confirmadas) > 0
    if tiene_memoria:
        logger.info(
            "   🧠 Memoria disponible: diagnóstico=%s, reglas=%d, cambios=%s",
            "sí" if diagnostico_anterior else "no",
            len(reglas_confirmadas),
            "sí" if cambios_detectados else "no",
        )
    else:
        logger.info("   📝 Sin memoria previa — análisis inicial")

    # ── 3. Construir prompt ───────────────────────────────────────────────────
    logger.info("📝 Construyendo prompt contextual con memoria histórica…")
    prompt = construir_prompt_contextual(
        snapshot_data=snapshot_data,
        diagnostico_anterior=diagnostico_anterior,
        reglas_confirmadas=reglas_confirmadas,
        cambios_detectados=cambios_detectados,
    )

    # ── 4. Llamar a Gemini ────────────────────────────────────────────────────
    try:
        client = genai.Client(api_key=gemini_api_key)
        logger.info("✅ Cliente Gemini inicializado")
    except Exception as exc:
        logger.error("Error al inicializar Gemini: %s", exc)
        return

    modelo = modelo_analizador()
    temperatura = temperatura_global()
    logger.info("🚀 Enviando a Gemini AI (modelo=%s, temp=%.1f)…", modelo, temperatura)
    logger.info("⏳ Esto puede tomar 15-45 segundos…")

    try:
        response = client.models.generate_content(
            model=modelo,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DiagnosticoFinanciero,
                temperature=temperatura,
                top_p=0.95,
                top_k=40,
            ),
        )
        logger.info("✅ Análisis completado por Gemini")
    except Exception as exc:
        logger.error("Error durante la generación del análisis: %s", exc)
        logger.error("  Tipo: %s", type(exc).__name__)
        return

    # ── 5. Parsear y guardar ──────────────────────────────────────────────────
    try:
        diagnostico_json = json.loads(response.text)
    except json.JSONDecodeError as exc:
        logger.error("Error al parsear la respuesta de Gemini: %s", exc)
        logger.error("Respuesta (primeros 500 chars): %s", response.text[:500])
        return

    ruta_ts = guardar_diagnostico(diagnostico_json)

    # ── 6. Mostrar resumen en consola ─────────────────────────────────────────
    print("\n" + "=" * 70)
    print("📊 RESUMEN DEL DIAGNÓSTICO FINANCIERO")
    print("=" * 70)

    print("\n📝 RESUMEN EJECUTIVO:")
    print("-" * 70)
    print(diagnostico_json.get("resumen_ejecutivo", "No disponible"))

    print("\n💰 BALANCE GENERAL:")
    print("-" * 70)
    print(diagnostico_json.get("balance_general", "No disponible"))

    # Cambios vs período anterior
    cambios_periodo = diagnostico_json.get("cambios_vs_periodo_anterior", [])
    if cambios_periodo:
        print("\n📈 CAMBIOS VS PERÍODO ANTERIOR:")
        print("-" * 70)
        for c in cambios_periodo:
            emoji = "✅" if c.get("evaluacion") == "Positivo" else ("⚠️ " if c.get("evaluacion") == "Negativo" else "➡️ ")
            print(f"  {emoji} [{c.get('categoria', '?')}] {c.get('variacion', '')} — {c.get('evaluacion', '')}")

    # Reglas aplicadas
    reglas_aplicadas = diagnostico_json.get("reglas_aplicadas", [])
    if reglas_aplicadas:
        print(f"\n📐 REGLAS APLICADAS: {', '.join(reglas_aplicadas)}")

    # Nuevos patrones sugeridos
    nuevos_patrones = diagnostico_json.get("nuevos_patrones_sugeridos", "Ninguno detectado")
    if nuevos_patrones and nuevos_patrones != "Ninguno detectado":
        print("\n🔍 NUEVOS PATRONES DETECTADOS:")
        print("-" * 70)
        print(nuevos_patrones)

    # Alertas
    alertas = diagnostico_json.get("alertas", [])
    if alertas:
        print("\n⚠️  ALERTAS IMPORTANTES:")
        print("-" * 70)
        for i, alerta in enumerate(alertas, 1):
            print(f"\n  {i}. [{alerta.get('tipo', 'N/A')}]")
            print(f"     {alerta.get('descripcion', 'N/A')}")
            print(f"     Impacto: {alerta.get('impacto_estimado', 'N/A')}")

    # Recomendaciones (top 5)
    recomendaciones = diagnostico_json.get("recomendaciones", [])
    if recomendaciones:
        print("\n💡 RECOMENDACIONES PRINCIPALES (top 5):")
        print("-" * 70)
        for i, rec in enumerate(recomendaciones[:5], 1):
            print(f"\n  {i}. {rec.get('categoria_gasto', 'N/A')} — Prioridad: {rec.get('prioridad', 'Media')}")
            print(f"     📌 {rec.get('observacion', 'N/A')}")
            print(f"     ✅ {rec.get('accion_sugerida', 'N/A')}")

    print("\n💡 OPORTUNIDADES DE AHORRO:")
    print("-" * 70)
    print(diagnostico_json.get("oportunidades_ahorro", "No disponible"))

    print("\n📅 PROYECCIÓN PRÓXIMO MES:")
    print("-" * 70)
    print(diagnostico_json.get("proyeccion_mes_siguiente", "No disponible"))

    print("\n" + "=" * 70)
    print(f"✅ Análisis completado: {diagnostico_json.get('fecha_analisis', 'N/A')}")
    print(f"   🧠 Memoria usada: diagnóstico={'sí' if diagnostico_anterior else 'no'}, "
          f"reglas={len(reglas_aplicadas)}/{len(reglas_confirmadas)}")
    print("=" * 70)
    print(f"\n📄 Diagnóstico guardado en: {ruta_ts}")
    print(f"   También disponible en: {DIAGNOSTICO_PATH}")
    print("\n🎯 ¡Revisa el archivo JSON para el análisis detallado completo!")


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        analizar_snapshot_financiero()
    except KeyboardInterrupt:
        print("\n\n[⚠️] Análisis interrumpido por el usuario")
    except Exception as exc:
        logger.error("Error inesperado: %s", exc)
        import traceback
        traceback.print_exc()
