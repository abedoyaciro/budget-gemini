"""
Generador de Dashboard HTML
============================
Lee los JSONs de output/ y genera output/dashboard.html, un archivo
autocontenido (sin dependencias externas) con Tailwind CSS y Chart.js
embebidos vía CDN y los datos inyectados como JavaScript inline.

Compatible con DiagnosticoFinanciero v3.0 (memoria histórica):
  - Cambios vs período anterior
  - Reglas aplicadas en el análisis
  - Nuevos patrones sugeridos
  - Proyección mes siguiente

Autor: Anderson Bedoya Ciro
Versión: 2.0
"""

import os
import json
import logging
from datetime import datetime
from typing import Any, Dict

import pytz
from dotenv import load_dotenv

from logging_config import setup_logging, ahora_colombia

logger = setup_logging(__name__)

OUTPUT_DIR       = "output"
SNAPSHOT_PATH    = os.path.join(OUTPUT_DIR, "snapshot_wallet.json")
DIAGNOSTICO_PATH = os.path.join(OUTPUT_DIR, "diagnostico_inteligente.json")
REGLAS_PATH      = os.path.join(OUTPUT_DIR, "reglas_aprendidas.json")
CONFIG_PATH      = os.path.join(OUTPUT_DIR, "config_modelos_activa.json")
ENRIQ_PATH       = os.path.join(OUTPUT_DIR, "enriquecimiento_log.json")
DASHBOARD_PATH   = os.path.join(OUTPUT_DIR, "dashboard.html")


def _leer_json(ruta: str) -> Dict[str, Any]:
    if not os.path.exists(ruta):
        return {}
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _js(data: Any) -> str:
    """Serializa a JSON seguro para inyectar en <script>."""
    return json.dumps(data, ensure_ascii=False, default=str)


def generar_dashboard() -> str:
    """Genera el HTML completo y lo guarda en output/dashboard.html."""

    # ── Cargar datos ──────────────────────────────────────────────────────────
    snap  = _leer_json(SNAPSHOT_PATH)
    diag  = _leer_json(DIAGNOSTICO_PATH)
    reg   = _leer_json(REGLAS_PATH)
    cfg   = _leer_json(CONFIG_PATH)
    enriq = _leer_json(ENRIQ_PATH)

    # Desempaquetar snapshot (puede tener envelope {data:...} o ser plano)
    snap_data = snap.get("data", snap)

    meta       = snap_data.get("metadata", snap.get("metadata", {}))
    cuentas    = snap_data.get("cuentas", [])
    registros  = snap_data.get("registros", [])
    etiquetas  = snap_data.get("etiquetas", [])
    stats      = snap_data.get("estadisticas", {})

    # ── Datos para gráficos ───────────────────────────────────────────────────
    tasa_usd_cop = stats.get("tasa_usd_cop")

    def _valor_en_cop_equivalente(registro: Dict[str, Any]) -> float:
        monto = registro.get("monto", {}) or {}
        valor = monto.get("valor", 0) or 0
        moneda = monto.get("moneda", "COP")
        if moneda == "COP":
            return float(valor)
        historico = registro.get("monto_historico_cop") or {}
        if moneda == "USD" and historico.get("valor") is not None:
            return float(historico.get("valor"))
        if moneda == "USD" and tasa_usd_cop:
            return float(valor) * float(tasa_usd_cop)
        convertido = registro.get("monto_convertido") or {}
        if convertido.get("moneda") == "COP" and convertido.get("valor") is not None:
            return float(convertido.get("valor"))
        return 0.0

    def _es_transferencia(registro: Dict[str, Any]) -> bool:
        transferencia = registro.get("transferencia") or {}
        return bool(transferencia.get("cuenta_nombre"))

    registros_sin_transferencias = [r for r in registros if not _es_transferencia(r)]

    def _nombre_categoria(registro: Dict[str, Any]) -> str:
        categoria = registro.get("categoria", {}) or {}
        return categoria.get("nombre_es") or categoria.get("nombre") or "Sin categoría"

    # 1. Gasto por categoría (top 8) con equivalencia a COP
    cat_gastos: Dict[str, float] = {}
    for r in registros_sin_transferencias:
        if r.get("tipo") == "expense":
            cat = _nombre_categoria(r)
            if cat in TRANSFER_CATEGORY_NAMES:
                continue
            monto_cop = abs(_valor_en_cop_equivalente(r))
            if monto_cop:
                cat_gastos[cat] = cat_gastos.get(cat, 0) + monto_cop

    cat_gastos_sorted = sorted(cat_gastos.items(), key=lambda x: x[1], reverse=True)[:8]
    labels_cat  = [x[0] for x in cat_gastos_sorted]
    valores_cat = [round(x[1]) for x in cat_gastos_sorted]

    # 2. Evolución temporal mensual (ingresos vs gastos en COP equivalente)
    meses: Dict[str, Dict[str, float]] = {}
    ingresos_mes_detalle: Dict[str, list[Dict[str, Any]]] = {}
    for r in registros_sin_transferencias:
        fecha = (r.get("fecha") or "")[:7]  # YYYY-MM
        if not fecha:
            continue
        meses.setdefault(fecha, {"ingresos": 0, "gastos": 0})
        valor_cop = _valor_en_cop_equivalente(r)
        if not valor_cop:
            continue
        if r.get("tipo") == "income":
            meses[fecha]["ingresos"] += valor_cop
            ingresos_mes_detalle.setdefault(fecha, []).append({
                "fecha": r.get("fecha"),
                "categoria": _nombre_categoria(r),
                "cuenta": (r.get("cuenta") or {}).get("nombre") or "Sin cuenta",
                "nota": (r.get("nota") or "").strip(),
                "contraparte": r.get("contraparte") or "",
                "moneda": (r.get("monto") or {}).get("moneda") or "COP",
                "monto_original": float((r.get("monto") or {}).get("valor", 0) or 0),
                "monto_cop": round(valor_cop, 2),
            })
        elif r.get("tipo") == "expense":
            if _nombre_categoria(r) in TRANSFER_CATEGORY_NAMES:
                continue
            meses[fecha]["gastos"] += abs(valor_cop)

    for items in ingresos_mes_detalle.values():
        items.sort(key=lambda item: item["monto_cop"], reverse=True)

    meses_sorted = sorted(meses.items())
    labels_meses   = [m[0] for m in meses_sorted]
    ingresos_mes   = [round(m[1]["ingresos"]) for m in meses_sorted]
    gastos_mes     = [round(m[1]["gastos"])   for m in meses_sorted]
    balance_mes    = [round(i - g) for i, g in zip(ingresos_mes, gastos_mes)]
    ahorro_mes     = [round((b / i) * 100, 1) if i > 0 else 0 for i, b in zip(ingresos_mes, balance_mes)]

    flujo_ingresos_fuentes: Dict[str, float] = {}
    flujo_fuentes_categorias: Dict[tuple[str, str], float] = {}
    flujo_categorias_subcategorias: Dict[tuple[str, str], float] = {}
    for r in registros_sin_transferencias:
        valor_cop = abs(_valor_en_cop_equivalente(r))
        if not valor_cop:
            continue
        categoria = r.get("categoria") or {}
        grupo = categoria.get("grupo_nombre_es") or categoria.get("grupo_nombre") or "Sin grupo"
        subcategoria = _nombre_categoria(r)
        if r.get("tipo") == "income":
            fuente = subcategoria
            flujo_ingresos_fuentes[fuente] = flujo_ingresos_fuentes.get(fuente, 0) + valor_cop
        elif r.get("tipo") == "expense" and subcategoria not in TRANSFER_CATEGORY_NAMES:
            flujo_fuentes_categorias[("Flujo de caja", grupo)] = flujo_fuentes_categorias.get(("Flujo de caja", grupo), 0) + valor_cop
            flujo_categorias_subcategorias[(grupo, subcategoria)] = flujo_categorias_subcategorias.get((grupo, subcategoria), 0) + valor_cop

    heatmap_gastos = {}
    for r in registros_sin_transferencias:
        if r.get("tipo") != "expense":
            continue
        if _nombre_categoria(r) in TRANSFER_CATEGORY_NAMES:
            continue
        fecha = (r.get("fecha") or "")[:10]
        if not fecha:
            continue
        heatmap_gastos[fecha] = round(heatmap_gastos.get(fecha, 0) + abs(_valor_en_cop_equivalente(r)), 2)

    sankey_ingresos_cuentas: Dict[str, float] = {}
    sankey_cuentas_categorias: Dict[tuple[str, str], float] = {}
    sankey_transferencias: Dict[tuple[str, str], float] = {}
    transferencias_vistas: set[tuple[str, str, str, float]] = set()
    for r in registros:
        cuenta = (r.get("cuenta") or {}).get("nombre") or "Sin cuenta"
        valor_cop = abs(_valor_en_cop_equivalente(r))
        if not valor_cop:
            continue
        if r.get("tipo") == "income" and not _es_transferencia(r):
            sankey_ingresos_cuentas[cuenta] = sankey_ingresos_cuentas.get(cuenta, 0) + valor_cop
        elif r.get("tipo") == "expense":
            categoria_nombre = _nombre_categoria(r)
            transferencia = r.get("transferencia") or {}
            cuenta_destino = transferencia.get("cuenta_nombre")
            if cuenta_destino or categoria_nombre in TRANSFER_CATEGORY_NAMES:
                cuenta_transferencia = cuenta_destino or "Sin cuenta destino"
                transfer_key = tuple(sorted((cuenta, cuenta_transferencia))) + (r.get("fecha") or "", round(valor_cop, 2))
                if transfer_key not in transferencias_vistas:
                    sankey_transferencias[(cuenta, cuenta_transferencia)] = sankey_transferencias.get((cuenta, cuenta_transferencia), 0) + valor_cop
                    transferencias_vistas.add(transfer_key)
                continue
            sankey_cuentas_categorias[(cuenta, categoria_nombre)] = sankey_cuentas_categorias.get((cuenta, categoria_nombre), 0) + valor_cop

    # 3. Distribución por tipo de pago
    tipos_pago: Dict[str, int] = {}
    for r in registros_sin_transferencias:
        tp = r.get("tipo_pago") or "desconocido"
        tipos_pago[tp] = tipos_pago.get(tp, 0) + 1

    tp_sorted = sorted(tipos_pago.items(), key=lambda x: x[1], reverse=True)
    labels_tp  = [x[0] for x in tp_sorted]
    valores_tp = [x[1] for x in tp_sorted]

    # 4. Balance por cuenta
    cuentas_cop = [
        {"nombre": c["nombre"], "balance": round(c.get("balance", {}).get("currentBalance", 0))}
        for c in cuentas
        if c.get("moneda") == "COP" and not c.get("archivada")
    ]
    cuentas_cop.sort(key=lambda x: x["balance"], reverse=True)

    cuentas_usd = [
        {"nombre": c["nombre"], "balance": round(c.get("balance", {}).get("currentBalance", 0) or 0, 2)}
        for c in cuentas
        if c.get("moneda") == "USD" and not c.get("archivada")
    ]
    cuentas_usd.sort(key=lambda x: x["balance"], reverse=True)

    total_balance_cuentas_cop = round(sum(c["balance"] for c in cuentas_cop), 2)
    total_balance_cuentas_usd = round(sum(c["balance"] for c in cuentas_usd), 2)
    total_balance_cuentas_usd_en_cop = round(total_balance_cuentas_usd * tasa_usd_cop, 2) if tasa_usd_cop else 0
    total_balance_cuentas_global_cop = round(
        total_balance_cuentas_cop + total_balance_cuentas_usd_en_cop,
        2,
    )

    # 5. Resumen de reglas
    reglas     = reg.get("reglas", [])
    confirmadas = sum(1 for r in reglas if r.get("estado") == "confirmada")
    pendientes  = sum(1 for r in reglas if r.get("estado") == "pendiente_confirmacion")
    rechazadas  = sum(1 for r in reglas if r.get("estado") == "rechazada")

    # 6. Datos de enriquecimiento
    sesiones_enriq  = enriq.get("sesiones", [])
    total_aplicados = sum(s.get("resumen_sesion", {}).get("aplicadas", 0) for s in sesiones_enriq)
    labels_obs = []
    labels_obs_vistas = set()
    for s in sesiones_enriq:
        for eo in s.get("etiquetas_obsoletas", []):
            nombre = (eo.get("nombre", "") or "").strip()
            if nombre and nombre.casefold() not in labels_obs_vistas:
                labels_obs.append(nombre)
                labels_obs_vistas.add(nombre.casefold())

    # 7. Config modelos
    config_activa = cfg.get("config_activa", {})
    catalogo      = cfg.get("catalogo", {})

    # ── Métricas clave ────────────────────────────────────────────────────────
    total_ingresos = sum(
        _valor_en_cop_equivalente(r)
        for r in registros_sin_transferencias
        if r.get("tipo") == "income"
    )
    total_gastos = sum(
        abs(_valor_en_cop_equivalente(r))
        for r in registros_sin_transferencias
        if r.get("tipo") == "expense" and _nombre_categoria(r) not in TRANSFER_CATEGORY_NAMES
    )
    total_ingresos_usd = sum(
        float((r.get("monto") or {}).get("valor", 0) or 0)
        for r in registros_sin_transferencias
        if r.get("tipo") == "income" and (r.get("monto") or {}).get("moneda") == "USD"
    )
    total_gastos_usd = sum(
        abs(float((r.get("monto") or {}).get("valor", 0) or 0))
        for r in registros_sin_transferencias
        if r.get("tipo") == "expense"
        and (r.get("monto") or {}).get("moneda") == "USD"
        and _nombre_categoria(r) not in TRANSFER_CATEGORY_NAMES
    )
    balance_neto = round(total_ingresos - total_gastos, 2)
    balance_neto_usd = round(total_ingresos_usd - total_gastos_usd, 2)
    balance_neto_global_cop = balance_neto
    tasa_ahorro  = round((balance_neto_global_cop / total_ingresos * 100), 1) if total_ingresos > 0 else 0

    ts_extraccion = meta.get("extraccion_timestamp", "")[:19].replace("T", " ")
    ts_analisis   = diag.get("fecha_analisis", "")[:19].replace("T", " ")
    ts_dashboard  = ahora_colombia().strftime("%Y-%m-%d %H:%M")

    alertas                   = diag.get("alertas", [])
    recomendaciones           = diag.get("recomendaciones", [])
    cambios_periodo           = diag.get("cambios_vs_periodo_anterior", [])
    reglas_aplicadas_diag     = diag.get("reglas_aplicadas", [])
    nuevos_patrones           = diag.get("nuevos_patrones_sugeridos", "")
    proyeccion_mes            = diag.get("proyeccion_mes_siguiente", "")
    balance_general_diag      = diag.get("balance_general", "")
    patrones_transporte_diag  = diag.get("patrones_transporte", "")
    analisis_inversiones_diag = diag.get("analisis_inversiones", "")

    # ── Construir HTML ────────────────────────────────────────────────────────
    html = _build_html(
        ts_dashboard=ts_dashboard,
        ts_extraccion=ts_extraccion,
        ts_analisis=ts_analisis,
        ventana_dias=meta.get("ventana_dias", 90),
        total_registros=stats.get("total_registros", len(registros)),
        total_cuentas=stats.get("total_cuentas", len(cuentas)),
        total_categorias=stats.get("total_categorias", 0),
        total_etiquetas=stats.get("total_etiquetas", len(etiquetas)),
        total_ingresos=total_ingresos,
        total_gastos=total_gastos,
        total_ingresos_usd=total_ingresos_usd,
        total_gastos_usd=total_gastos_usd,
        balance_neto=balance_neto,
        balance_neto_usd=balance_neto_usd,
        balance_neto_global_cop=balance_neto_global_cop,
        tasa_usd_cop=tasa_usd_cop,
        total_balance_cuentas_cop=total_balance_cuentas_cop,
        total_balance_cuentas_usd=total_balance_cuentas_usd,
        total_balance_cuentas_usd_en_cop=total_balance_cuentas_usd_en_cop,
        total_balance_cuentas_global_cop=total_balance_cuentas_global_cop,
        tasa_ahorro=tasa_ahorro,
        resumen_ejecutivo=diag.get("resumen_ejecutivo", ""),
        balance_general_diag=balance_general_diag,
        patrones_transporte_diag=patrones_transporte_diag,
        analisis_inversiones_diag=analisis_inversiones_diag,
        alertas=alertas,
        recomendaciones=recomendaciones,
        cambios_periodo=cambios_periodo,
        reglas_aplicadas_diag=reglas_aplicadas_diag,
        nuevos_patrones=nuevos_patrones,
        proyeccion_mes=proyeccion_mes,
        oportunidades_ahorro=diag.get("oportunidades_ahorro", ""),
        labels_cat=_js(labels_cat),
        valores_cat=_js(valores_cat),
        labels_meses=_js(labels_meses),
        ingresos_mes=_js(ingresos_mes),
        ingresos_mes_detalle=_js(ingresos_mes_detalle),
        gastos_mes=_js(gastos_mes),
        balance_mes=_js(balance_mes),
        ahorro_mes=_js(ahorro_mes),
        heatmap_gastos=_js(heatmap_gastos),
        sankey_ingresos_cuentas=_js(sankey_ingresos_cuentas),
        sankey_cuentas_categorias=_js([
            {"from": origen, "to": destino, "value": round(valor, 2)}
            for (origen, destino), valor in sankey_cuentas_categorias.items()
        ]),
        sankey_transferencias=_js([
            {"from": origen, "to": destino, "value": round(valor, 2)}
            for (origen, destino), valor in sankey_transferencias.items()
        ]),
        sankey_flujo_fuentes=_js([
            {"from": "Ingresos", "to": destino, "value": round(valor, 2)}
            for destino, valor in flujo_ingresos_fuentes.items()
        ]),
        sankey_flujo_categorias=_js([
            {"from": origen, "to": destino, "value": round(valor, 2)}
            for (origen, destino), valor in flujo_fuentes_categorias.items()
        ]),
        sankey_flujo_subcategorias=_js([
            {"from": origen, "to": destino, "value": round(valor, 2)}
            for (origen, destino), valor in flujo_categorias_subcategorias.items()
        ]),
        labels_tp=_js(labels_tp),
        valores_tp=_js(valores_tp),
        cuentas_cop=cuentas_cop,
        cuentas_usd=cuentas_usd,
        reglas=reglas,
        confirmadas=confirmadas,
        pendientes=pendientes,
        rechazadas=rechazadas,
        total_aplicados=total_aplicados,
        labels_obs=labels_obs,
        config_activa=config_activa,
        catalogo=catalogo,
        modelo_analizador=config_activa.get("analizador", "-"),
        modelo_aprendizaje=config_activa.get("aprendizaje", "-"),
        modelo_confirmador=config_activa.get("confirmador", "-"),
        temperatura=config_activa.get("temperatura", 0.3),
    )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("✅ Dashboard generado: %s", DASHBOARD_PATH)
    return DASHBOARD_PATH


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE HTML
# ─────────────────────────────────────────────────────────────────────────────

# Tabla de reemplazo de categorías en inglés → español para texto narrativo
_CAT_EN_ES = {
    "Loan, interests": "Préstamo e intereses",
    "Restaurants & fast food": "Restaurantes y comida rápida",
    "Groceries": "Mercado",
    "Fuel": "Combustible",
    "Alcohol, tobacco": "Alcohol y tabaco",
    "Shopping": "Compras",
    "Vehicle": "Vehículo",
    "Fuel (Vehicle)": "Combustible",
    "Vehicle maintenance": "Mantenimiento del vehículo",
    "Food & Drinks": "Comida y bebidas",
    "Bar cafe": "Bar y café",
    "Financial expenses": "Gastos financieros",
    "Advisory": "Asesoría",
    "Charges, fees": "Cobros y comisiones",
    "Fines": "Multas",
    "Insurances": "Seguros",
    "Taxes": "Impuestos",
    "Savings": "Ahorros",
    "Energy & utilities": "Energía y servicios públicos",
    "Housing": "Vivienda",
    "Insurance (Housing)": "Seguro de vivienda",
    "Maintenance & repairs": "Mantenimiento y reparaciones",
    "Mortgage": "Hipoteca",
    "Rent": "Arriendo",
    "Services": "Servicios",
    "Wage, invoices": "Salario y facturas",
    "Lending, renting": "Préstamos y arriendos",
    "Investments": "Inversiones",
    "Interest, dividends": "Intereses y dividendos",
    "Parking": "Parqueadero",
    "Gifts & joy": "Regalos y detalles",
    "Clothes & shoes": "Ropa y zapatos",
    "Health & beauty": "Salud y belleza",
    "Jewels & accessories": "Joyas y accesorios",
    "Pets & animals": "Mascotas y animales",
    "Stationery & tools": "Papelería y herramientas",
    "Health care & doctor": "Salud y doctor",
    "Hobbies": "Pasatiempos",
    "Phone, cell phones": "Teléfono y celular",
    "Income": "Ingresos",
    "Transfer": "Transferencia",
    "Vehicle > Fuel": "Vehículo > Combustible",
    "Food & Drinks > Restaurants & fast food": "Comida y bebidas > Restaurantes y comida rápida",
    "Food & Drinks > Groceries": "Comida y bebidas > Mercado",
    "Vehicle > Vehicle maintenance": "Vehículo > Mantenimiento del vehículo",
}


def _traducir_categorias(texto: str) -> str:
    """Reemplaza nombres de categorías en inglés por español en texto libre."""
    for en, es in sorted(_CAT_EN_ES.items(), key=lambda x: -len(x[0])):
        texto = texto.replace(en, es)
    return texto


TRANSFER_CATEGORY_NAMES = {
    "Transfer",
    "Transferencia",
}


def _build_html(**ctx) -> str:  # noqa: C901
    """Construye el HTML completo del dashboard."""

    def fmt_cop(val: float) -> str:
        return f"${val:,.0f}"

    def fmt_usd(val: float) -> str:
        return f"US${val:,.2f}"

    def prio_badge(p: str) -> str:
        colors = {"Alta": "bg-red-100 text-red-700", "Media": "bg-yellow-100 text-yellow-700", "Baja": "bg-green-100 text-green-700"}
        cls = colors.get(p, "bg-gray-100 text-gray-600")
        return f'<span class="px-2 py-0.5 rounded-full text-xs font-semibold {cls}">{p}</span>'

    def estado_badge(e: str) -> str:
        colors = {"confirmada": "bg-emerald-100 text-emerald-700", "pendiente_confirmacion": "bg-amber-100 text-amber-700", "rechazada": "bg-red-100 text-red-700"}
        icons  = {"confirmada": "✅", "pendiente_confirmacion": "⏳", "rechazada": "❌"}
        label  = {"confirmada": "Confirmada", "pendiente_confirmacion": "Pendiente", "rechazada": "Rechazada"}
        cls  = colors.get(e, "bg-gray-100 text-gray-600")
        icon = icons.get(e, "")
        lbl  = label.get(e, e)
        return f'<span class="px-2 py-0.5 rounded-full text-xs font-semibold {cls}">{icon} {lbl}</span>'

    # Alertas HTML
    alertas_html = ""
    for a in ctx["alertas"]:
        tipo = a.get("tipo", "")
        color = "red" if "Riesgo" in tipo else "amber"
        alertas_html += f"""
        <div class="flex gap-3 p-4 bg-{color}-50 border border-{color}-200 rounded-xl">
          <div class="text-{color}-500 text-xl mt-0.5">{"🚨" if color=="red" else "⚠️"}</div>
          <div>
            <div class="font-semibold text-{color}-800 text-sm">{_traducir_categorias(tipo)}</div>
            <div class="text-{color}-700 text-sm mt-1">{_traducir_categorias(a.get("descripcion",""))}</div>
            <div class="text-{color}-600 text-xs mt-1 italic">Impacto: {_traducir_categorias(a.get("impacto_estimado",""))}</div>
          </div>
        </div>"""

    # Cambios vs período anterior HTML
    cambios_html = ""
    for c in ctx.get("cambios_periodo", []):
        ev = c.get("evaluacion", "Neutral")
        ev_color = "emerald" if ev == "Positivo" else "red" if ev == "Negativo" else "gray"
        ev_icon  = "✅" if ev == "Positivo" else "⚠️" if ev == "Negativo" else "➡️"
        cambios_html += f"""
        <div class="flex items-start gap-3 p-3 bg-{ev_color}-50 border border-{ev_color}-100 rounded-lg">
          <div class="text-lg">{ev_icon}</div>
          <div>
            <div class="font-semibold text-{ev_color}-800 text-xs uppercase">{c.get("categoria","")}</div>
            <div class="text-{ev_color}-700 text-sm mt-0.5">{c.get("variacion","")}</div>
          </div>
        </div>"""
    if not cambios_html:
        cambios_html = '<p class="text-gray-400 text-sm italic">Sin análisis histórico previo disponible.</p>'

    # Reglas aplicadas en el análisis (badges)
    reglas_aplicadas_html = ""
    for rid in ctx.get("reglas_aplicadas_diag", []):
        reglas_aplicadas_html += f'<span class="px-2 py-1 bg-indigo-100 text-indigo-700 rounded-full text-xs font-mono font-semibold">{rid}</span>'
    if not reglas_aplicadas_html:
        reglas_aplicadas_html = '<span class="text-gray-400 text-xs italic">Ninguna regla aplicada en este análisis</span>'

    # Recomendaciones HTML
    recs_html = ""
    for r in ctx["recomendaciones"]:
        recs_html += f"""
        <div class="p-4 bg-white border border-gray-200 rounded-xl shadow-sm hover:shadow-md transition-shadow">
          <div class="flex items-center justify-between mb-2">
            <span class="font-semibold text-gray-800 text-sm">{_traducir_categorias(r.get("categoria_gasto",""))}</span>
            {prio_badge(r.get("prioridad",""))}
          </div>
          <p class="text-gray-600 text-sm">{_traducir_categorias(r.get("observacion",""))}</p>
          <p class="text-indigo-700 text-sm mt-2 font-medium">💡 {_traducir_categorias(r.get("accion_sugerida",""))}</p>
        </div>"""

    # Cuentas HTML
    cuentas_html = ""
    for c in ctx["cuentas_cop"]:
        bal = c["balance"]
        color = "emerald" if bal >= 0 else "red"
        cuentas_html += f"""
        <div class="flex items-center justify-between gap-4 p-3 bg-gray-50 rounded-lg">
          <span class="text-sm font-medium text-gray-700">{c["nombre"]}</span>
          <span class="text-sm font-bold text-{color}-600 text-right break-all">{fmt_cop(bal)}</span>
        </div>"""

    cuentas_usd_html = ""
    tasa_usd_cop = ctx.get("tasa_usd_cop")
    for c in ctx["cuentas_usd"]:
        bal = c["balance"]
        bal_cop = bal * tasa_usd_cop if tasa_usd_cop else 0
        color = "emerald" if bal >= 0 else "red"
        cuentas_usd_html += f"""
        <div class="p-3 bg-gray-50 rounded-lg">
          <div class="flex items-center justify-between gap-4">
            <span class="text-sm font-medium text-gray-700">{c["nombre"]}</span>
            <span class="text-sm font-bold text-{color}-600 text-right break-all">{fmt_usd(bal)}</span>
          </div>
          <div class="mt-1 text-xs text-gray-500 text-right">Equivale a {fmt_cop(bal_cop)}</div>
        </div>"""
    if not cuentas_usd_html:
        cuentas_usd_html = '<div class="text-sm text-gray-400 italic">Sin cuentas activas en USD.</div>'

    # Reglas HTML
    reglas_html = ""
    for r in ctx["reglas"]:
        accion = r.get("accion", {})
        etq = f" + <span class='text-purple-600'>#{accion.get('etiqueta','')}</span>" if accion.get("etiqueta") else ""
        kws = ", ".join(f"<code class='bg-gray-100 px-1 rounded text-xs'>{k}</code>" for k in r.get("palabras_clave", []))
        conf_pct = int(r.get("confianza", 0) * 100)
        conf_color = "emerald" if conf_pct >= 90 else "amber" if conf_pct >= 75 else "red"
        reglas_html += f"""
        <div class="p-4 bg-white border border-gray-200 rounded-xl shadow-sm">
          <div class="flex items-start justify-between gap-2">
            <div class="flex-1">
              <div class="flex items-center gap-2 flex-wrap mb-1">
                <span class="font-mono text-xs text-gray-400">{r.get("id","")}</span>
                {estado_badge(r.get("estado",""))}
              </div>
              <p class="text-sm font-semibold text-gray-800">{_traducir_categorias(r.get("patron",""))}</p>
              <p class="text-xs text-gray-500 mt-1">Palabras clave: {kws}</p>
              <p class="text-sm text-indigo-700 mt-2">→ <strong>{_traducir_categorias(accion.get("categoria",""))}</strong>{etq}</p>
            </div>
            <div class="text-right shrink-0">
              <div class="text-lg font-bold text-{conf_color}-600">{conf_pct}%</div>
              <div class="text-xs text-gray-400">{r.get("ejemplos",0)} ejemplos</div>
              <div class="text-xs text-gray-400">{fmt_cop(r.get("monto_promedio_cop") or 0)} avg</div>
            </div>
          </div>
        </div>"""

    # Labels obsoletos
    labels_obs_unicos = []
    labels_obs_vistos = set()
    for lb in ctx["labels_obs"]:
        normalizado = (lb or "").strip().casefold()
        if normalizado and normalizado not in labels_obs_vistos:
            labels_obs_unicos.append(lb)
            labels_obs_vistos.add(normalizado)

    obs_html = ""
    for lb in labels_obs_unicos:
        obs_html += f'<span class="px-2 py-1 bg-red-100 text-red-700 rounded-full text-xs font-medium">🗑️ {lb}</span>'
    if not obs_html:
        obs_html = '<span class="text-gray-400 text-sm">Sin etiquetas obsoletas detectadas</span>'

    # Config modelos HTML
    modelos_html = ""
    for svc, mid in [("Analizador", ctx["modelo_analizador"]), ("Aprendizaje", ctx["modelo_aprendizaje"]), ("Confirmador / Modificador", ctx["modelo_confirmador"])]:
        info = ctx["catalogo"].get(mid, {})
        vel_icon = {"rapido": "⚡", "medio": "🔄", "lento": "🐢"}.get(info.get("velocidad",""), "")
        cost_icon = {"bajo": "💚", "medio": "💛", "alto": "🔴"}.get(info.get("costo",""), "")
        modelos_html += f"""
        <div class="p-3 bg-gray-50 rounded-lg flex items-center justify-between">
          <div>
            <div class="text-xs text-gray-500">{svc}</div>
            <div class="text-sm font-semibold text-gray-800">{info.get("nombre", mid)}</div>
          </div>
          <div class="flex gap-2 text-sm">{vel_icon} {cost_icon}</div>
        </div>"""

    balance_color = "emerald" if ctx["balance_neto"] >= 0 else "red"
    balance_usd_color = "emerald" if ctx["balance_neto_usd"] >= 0 else "red"
    balance_global_color = "emerald" if ctx["balance_neto_global_cop"] >= 0 else "red"
    ahorro_color  = "emerald" if ctx["tasa_ahorro"] >= 20 else "amber" if ctx["tasa_ahorro"] >= 10 else "red"

    return f"""<!DOCTYPE html>
<html lang="es" class="scroll-smooth">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Dashboard Financiero — Anderson Bedoya</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body {{ font-family: 'Inter', system-ui, sans-serif; }}
  .card {{ @apply bg-white rounded-2xl shadow-sm border border-gray-100 p-6; }}
  .metric-card {{ transition: transform .15s; min-height: 120px; display:flex; flex-direction:column; justify-content:center; }}
  .metric-card:hover {{ transform: translateY(-2px); }}
  .metric-value {{ font-size: clamp(1.5rem, 2vw, 2rem); line-height: 1.1; word-break: break-word; overflow-wrap: anywhere; }}
  .metric-label {{ min-height: 2.5rem; display:flex; align-items:center; justify-content:center; }}
  ::-webkit-scrollbar {{ width:6px; height:6px; }}
  ::-webkit-scrollbar-track {{ background:#f1f5f9; }}
  ::-webkit-scrollbar-thumb {{ background:#cbd5e1; border-radius:3px; }}
  .dark .bg-white {{ background-color:#1e293b; }}
  .dark .bg-gray-50 {{ background-color:#0f172a; }}
  .dark .text-gray-800 {{ color:#f1f5f9; }}
  .dark .text-gray-600 {{ color:#94a3b8; }}
  .dark .border-gray-200 {{ border-color:#334155; }}
  .dark .border-gray-100 {{ border-color:#1e293b; }}
</style>
</head>
<body class="bg-gray-50 min-h-screen" id="body">

<!-- HEADER -->
<header class="bg-gradient-to-r from-indigo-700 via-indigo-600 to-purple-600 text-white shadow-lg sticky top-0 z-50">
  <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
    <div>
      <h1 class="text-lg font-bold tracking-tight">📊 Dashboard Financiero</h1>
      <p class="text-indigo-200 text-xs">Anderson Bedoya Ciro · Actualizado {ctx["ts_dashboard"]}</p>
    </div>
    <div class="flex items-center gap-3">
      <span class="hidden sm:inline text-xs text-indigo-200">Ventana: últimos {ctx["ventana_dias"]} días</span>
      <button onclick="toggleDark()" class="p-2 rounded-lg bg-white/10 hover:bg-white/20 transition text-sm" title="Modo oscuro">🌙</button>
      <button onclick="window.print()" class="p-2 rounded-lg bg-white/10 hover:bg-white/20 transition text-sm" title="Exportar PDF">🖨️</button>
    </div>
  </div>
  <!-- NAV -->
  <nav class="max-w-7xl mx-auto px-4 pb-2 flex gap-4 text-xs text-indigo-200 overflow-x-auto">
    <a href="#resumen"     class="hover:text-white whitespace-nowrap">Resumen</a>
    <a href="#balance"     class="hover:text-white whitespace-nowrap">Balance</a>
    <a href="#memoria"     class="hover:text-white whitespace-nowrap">Memoria IA</a>
    <a href="#graficos"    class="hover:text-white whitespace-nowrap">Gráficos</a>
    <a href="#cuentas"     class="hover:text-white whitespace-nowrap">Cuentas</a>
    <a href="#alertas"     class="hover:text-white whitespace-nowrap">Alertas</a>
    <a href="#reglas"      class="hover:text-white whitespace-nowrap">Reglas IA</a>
    <a href="#modelos"     class="hover:text-white whitespace-nowrap">Modelos</a>
  </nav>
</header>

<main class="max-w-7xl mx-auto px-4 py-6 space-y-8">

  <!-- MÉTRICAS CLAVE -->
  <section id="resumen">
    <h2 class="text-base font-semibold text-gray-500 uppercase tracking-wider mb-4">Métricas del Período</h2>
    <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8 gap-5">
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-emerald-600">{fmt_cop(ctx["total_ingresos"])}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Ingresos COP</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-red-500">{fmt_cop(ctx["total_gastos"])}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Gastos COP</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-emerald-600">{fmt_usd(ctx["total_ingresos_usd"])}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Ingresos USD</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-red-500">{fmt_usd(ctx["total_gastos_usd"])}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Gastos USD</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-{balance_color}-600">{fmt_cop(ctx["balance_neto"])}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Balance Neto COP</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-{balance_usd_color}-600">{fmt_usd(ctx["balance_neto_usd"])}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Balance Neto USD</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-{balance_global_color}-600">{fmt_cop(ctx["balance_neto_global_cop"])}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Balance Global COP</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-indigo-600">{fmt_cop(ctx["tasa_usd_cop"] or 0)}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Tasa USD→COP</div>
      </div>
    </div>
    <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8 gap-5 mt-5">
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-emerald-600">{fmt_cop(ctx["total_balance_cuentas_cop"])}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Acumulado cuentas COP</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-emerald-600">{fmt_usd(ctx["total_balance_cuentas_usd"])}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Acumulado cuentas USD</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-emerald-600">{fmt_cop(ctx["total_balance_cuentas_usd_en_cop"])}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">USD equivalente en COP</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-{balance_global_color}-600">{fmt_cop(ctx["total_balance_cuentas_global_cop"])}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Suma total actual en COP</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-{ahorro_color}-600">{ctx["tasa_ahorro"]}%</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Tasa de Ahorro</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-indigo-600">{ctx["total_registros"]}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Transacciones</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-purple-600">{ctx["total_cuentas"]}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Cuentas activas</div>
      </div>
      <div class="metric-card bg-white rounded-2xl shadow-sm border border-gray-100 p-4 text-center">
        <div class="metric-value font-bold text-sky-600">{ctx["total_categorias"]}</div>
        <div class="metric-label text-xs text-gray-500 mt-1">Categorías</div>
      </div>
    </div>
  </section>

  <!-- RESUMEN EJECUTIVO + OPORTUNIDADES -->
  <section id="balance" class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">🧠 Resumen Ejecutivo — Gemini AI</h2>
      <p class="text-gray-700 text-sm leading-relaxed">{_traducir_categorias(ctx["resumen_ejecutivo"])}</p>
      <div class="mt-4 pt-3 border-t border-gray-100">
        <h3 class="text-xs font-semibold text-gray-500 uppercase mb-2">💰 Balance General</h3>
        <p class="text-gray-600 text-sm leading-relaxed">{_traducir_categorias(ctx["balance_general_diag"])}</p>
      </div>
      <div class="mt-3 pt-3 border-t border-gray-100 text-xs text-gray-400">
        Análisis: {ctx["ts_analisis"]} · Extracción: {ctx["ts_extraccion"]}
      </div>
    </div>
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">💰 Oportunidades de Ahorro</h2>
      <div class="p-4 bg-emerald-50 border border-emerald-200 rounded-xl text-sm text-emerald-800 leading-relaxed">
        {ctx["oportunidades_ahorro"]}
      </div>
      <div class="mt-4">
        <h3 class="text-xs font-semibold text-gray-500 uppercase mb-3">Recomendaciones</h3>
        <div class="space-y-3">{recs_html}</div>
      </div>
    </div>
  </section>

  <!-- MEMORIA IA: CAMBIOS HISTÓRICOS + PROYECCIÓN + PATRONES NUEVOS -->
  <section id="memoria" class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 lg:col-span-1">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">📈 Cambios vs Período Anterior</h2>
      <div class="space-y-3">{cambios_html}</div>
    </div>
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 lg:col-span-1">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">📅 Proyección Próximo Mes</h2>
      <div class="p-4 bg-blue-50 border border-blue-200 rounded-xl text-sm text-blue-800 leading-relaxed">
        {ctx["proyeccion_mes"] or '<span class="text-gray-400 italic">Sin historial suficiente para proyectar.</span>'}
      </div>
      <div class="mt-4">
        <h3 class="text-xs font-semibold text-gray-500 uppercase mb-2">📐 Reglas Aplicadas en Este Análisis</h3>
        <div class="flex flex-wrap gap-2 mt-1">{reglas_aplicadas_html}</div>
      </div>
    </div>
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 lg:col-span-1">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">🔍 Nuevos Patrones Sugeridos</h2>
      <div class="p-4 bg-purple-50 border border-purple-200 rounded-xl text-sm text-purple-800 leading-relaxed">
          {_traducir_categorias(ctx["nuevos_patrones"]) or '<span class="text-gray-400 italic">Ninguno detectado en este período.</span>'}
        </div>
        <div class="mt-4">
          <h3 class="text-xs font-semibold text-gray-500 uppercase mb-2">🚗 Transporte · 💼 Inversiones</h3>
          <details class="cursor-pointer">
            <summary class="text-xs text-indigo-600 font-medium hover:underline">Ver análisis detallado</summary>
            <div class="mt-2 space-y-3">
              <div class="p-3 bg-gray-50 rounded-lg text-xs text-gray-600 leading-relaxed">
                <strong>Transporte:</strong> {_traducir_categorias(ctx["patrones_transporte_diag"][:300] + ("…" if len(ctx["patrones_transporte_diag"]) > 300 else ""))}
              </div>
              <div class="p-3 bg-gray-50 rounded-lg text-xs text-gray-600 leading-relaxed">
                <strong>Inversiones:</strong> {_traducir_categorias(ctx["analisis_inversiones_diag"][:300] + ("…" if len(ctx["analisis_inversiones_diag"]) > 300 else ""))}
              </div>
          </div>
        </details>
      </div>
    </div>
  </section>

  <!-- GRÁFICOS -->
  <section id="graficos" class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">📈 Evolución Mensual (COP equivalente)</h2>
      <canvas id="chartMeses" height="220"></canvas>
    </div>
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">🍩 Gastos por Categoría (COP equivalente)</h2>
      <canvas id="chartCat" height="220"></canvas>
    </div>
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">💳 Métodos de Pago</h2>
      <canvas id="chartTipoPago" height="220"></canvas>
    </div>
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">📉 Tendencia de Tasa de Ahorro</h2>
      <canvas id="chartAhorro" height="220"></canvas>
    </div>
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 lg:col-span-2">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">🗓️ Heatmap de Gastos por Día</h2>
      <div id="heatmapGastos" class="grid grid-cols-7 gap-2 text-xs"></div>
    </div>
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 lg:col-span-2">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">🌊 Flujo de Caja Detallado (Sankey)</h2>
      <div id="sankeyChart" class="w-full h-[520px]"></div>
      <p class="text-xs text-gray-400 mt-3">Incluye ingresos por cuenta, gastos por categoría y transferencias entre cuentas.</p>
    </div>
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 lg:col-span-2">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">🧭 Flujo de Caja por Fuentes y Categorías (Sankey)</h2>
      <div id="cashflowSankeyChart" class="w-full h-[560px]"></div>
      <p class="text-xs text-gray-400 mt-3">Muestra fuentes de ingreso, categorías grandes y subcategorías de gasto sin usar cuentas.</p>
    </div>
    <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 lg:col-span-2" id="cuentas">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">🏦 Balance por Cuenta</h2>
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div>
          <h3 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">COP</h3>
          <div class="space-y-2">{cuentas_html}</div>
        </div>
        <div>
          <h3 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">USD</h3>
          <div class="space-y-2">{cuentas_usd_html}</div>
        </div>
      </div>
    </div>
  </section>

  <!-- ALERTAS -->
  <section id="alertas" class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
    <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">⚠️ Alertas Detectadas por Gemini</h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">{alertas_html}</div>
  </section>

  <!-- REGLAS IA -->
  <section id="reglas" class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
    <div class="flex items-center justify-between mb-4 flex-wrap gap-3">
      <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider">🤖 Reglas Contables Aprendidas</h2>
      <div class="flex gap-3 text-xs">
        <span class="px-2 py-1 bg-emerald-100 text-emerald-700 rounded-full font-semibold">✅ {ctx["confirmadas"]} confirmadas</span>
        <span class="px-2 py-1 bg-amber-100 text-amber-700 rounded-full font-semibold">⏳ {ctx["pendientes"]} pendientes</span>
        <span class="px-2 py-1 bg-red-100 text-red-700 rounded-full font-semibold">❌ {ctx["rechazadas"]} rechazadas</span>
      </div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">{reglas_html}</div>
    <div class="mt-6 pt-4 border-t border-gray-100">
      <h3 class="text-xs font-semibold text-gray-500 uppercase mb-3">🗑️ Etiquetas Obsoletas Detectadas</h3>
      <div class="flex flex-wrap gap-2">{obs_html}</div>
      <p class="text-xs text-gray-400 mt-2">Total cambios aplicados a Wallet: <strong>{ctx["total_aplicados"]}</strong></p>
    </div>
  </section>

  <!-- MODELOS IA -->
  <section id="modelos" class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
    <h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">⚙️ Configuración de Modelos Gemini</h2>
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {modelos_html}
    </div>
    <div class="mt-4 p-3 bg-indigo-50 border border-indigo-100 rounded-xl text-xs text-indigo-700">
      Temperatura global: <strong>{ctx["temperatura"]}</strong> ·
      Para cambiar los modelos edita <code class="bg-indigo-100 px-1 rounded">.env</code> y ejecuta
      <code class="bg-indigo-100 px-1 rounded">make pipeline</code>
    </div>
  </section>

  <!-- FOOTER -->
  <footer class="text-center text-xs text-gray-400 py-4">
    Dashboard generado el {ctx["ts_dashboard"]} · Budget-Gemini System · Anderson Bedoya Ciro
  </footer>

</main>

<script>
// ── Datos inyectados desde Python ─────────────────────────────────────────
const labelsMeses   = {ctx["labels_meses"]};
const ingresosMes   = {ctx["ingresos_mes"]};
const ingresosMesDetalle = {ctx["ingresos_mes_detalle"]};
const gastosMes     = {ctx["gastos_mes"]};
const balanceMes    = {ctx["balance_mes"]};
const ahorroMes     = {ctx["ahorro_mes"]};
const heatmapGastos = {ctx["heatmap_gastos"]};
const labelsCat     = {ctx["labels_cat"]};
const valoresCat    = {ctx["valores_cat"]};
const labelsTp      = {ctx["labels_tp"]};
const valoresTp     = {ctx["valores_tp"]};
const sankeyIngresosCuentas = {ctx["sankey_ingresos_cuentas"]};
const sankeyCuentasCategorias = {ctx["sankey_cuentas_categorias"]};
const sankeyTransferencias = {ctx["sankey_transferencias"]};
const sankeyFlujoFuentes = {ctx["sankey_flujo_fuentes"]};
const sankeyFlujoCategorias = {ctx["sankey_flujo_categorias"]};
const sankeyFlujoSubcategorias = {ctx["sankey_flujo_subcategorias"]};
const sankeyData = [
  ...Object.entries(sankeyIngresosCuentas).map(([to, value]) => ({{ from: 'Ingresos', to, value }})),
  ...sankeyCuentasCategorias,
  ...sankeyTransferencias,
].filter(item => item.value > 0);

// ── Paleta de colores ─────────────────────────────────────────────────────
const PALETTE = ['#6366f1','#8b5cf6','#ec4899','#f43f5e','#f97316','#eab308','#22c55e','#14b8a6','#3b82f6','#a78bfa'];

// ── Gráfico: Evolución mensual ────────────────────────────────────────────
new Chart(document.getElementById('chartMeses'), {{
  type: 'bar',
  data: {{
    labels: labelsMeses,
    datasets: [
      {{ label: 'Ingresos', data: ingresosMes, backgroundColor: '#22c55e88', borderColor: '#22c55e', borderWidth: 2, borderRadius: 4 }},
      {{ label: 'Gastos',   data: gastosMes,   backgroundColor: '#ef444488', borderColor: '#ef4444', borderWidth: 2, borderRadius: 4 }},
      {{ label: 'Balance',  data: balanceMes,  type: 'line', borderColor: '#6366f1', backgroundColor: 'transparent', borderWidth: 2.5, pointRadius: 4, tension: 0.4, yAxisID: 'y' }},
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{
      legend: {{ position: 'top', labels: {{ font: {{ size:11 }} }} }},
      tooltip: {{
        callbacks: {{
          label: ctx => ' $' + ctx.raw.toLocaleString('es-CO'),
          afterBody: items => {{
            const item = items[0];
            if (!item || item.dataset.label !== 'Ingresos') return [];
            const mes = labelsMeses[item.dataIndex];
            const detalle = ingresosMesDetalle[mes] || [];
            if (!detalle.length) return ['Sin detalle disponible'];
            return ['Detalle:'].concat(detalle.map(entry => {{
              const origen = entry.nota || entry.contraparte || entry.categoria;
              return `• $${{Math.round(entry.monto_cop).toLocaleString('es-CO')}} · ${{origen}} · ${{entry.cuenta}}`;
            }}));
          }}
        }}
      }}
    }},
    scales: {{ y: {{ ticks: {{ callback: v => '$' + (v/1e6).toFixed(1) + 'M', font:{{size:10}} }}, grid: {{ color:'#f1f5f9' }} }}, x: {{ grid: {{ display:false }}, ticks: {{ font:{{size:10}} }} }} }}
  }}
}});

// ── Gráfico: Tendencia de tasa de ahorro ───────────────────────────────────
new Chart(document.getElementById('chartAhorro'), {{
  type: 'line',
  data: {{
    labels: labelsMeses,
    datasets: [{{
      label: 'Tasa de ahorro %',
      data: ahorroMes,
      borderColor: '#7c3aed',
      backgroundColor: '#7c3aed22',
      borderWidth: 2.5,
      fill: true,
      tension: 0.35,
      pointRadius: 4,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ tooltip: {{ callbacks: {{ label: ctx => ' ' + ctx.raw + '%' }} }} }},
    scales: {{ y: {{ ticks: {{ callback: v => v + '%' }}, grid: {{ color:'#f1f5f9' }} }}, x: {{ grid: {{ display:false }} }} }}
  }}
}});

// ── Heatmap de gastos por día ──────────────────────────────────────────────
(function renderHeatmap() {{
  const container = document.getElementById('heatmapGastos');
  if (!container) return;
  const entries = Object.entries(heatmapGastos).sort((a, b) => a[0].localeCompare(b[0]));
  if (!entries.length) {{
    container.innerHTML = '<div class="text-gray-400 italic col-span-7">Sin gastos para mostrar.</div>';
    return;
  }}
  const max = Math.max(...entries.map(([, value]) => value), 1);
  container.innerHTML = entries.map(([fecha, value]) => {{
    const intensity = Math.max(0.12, value / max);
    return `<div class="rounded-lg p-2 border border-gray-100" style="background: rgba(239,68,68,${{intensity.toFixed(2)}})">
      <div class="text-[11px] font-semibold text-gray-700">${{fecha.slice(5)}}</div>
      <div class="text-[11px] text-gray-700">$${{Math.round(value).toLocaleString('es-CO')}}</div>
    </div>`;
  }}).join('');
}})();

// ── Gráfico: Gastos por categoría (doughnut) ─────────────────────────────
new Chart(document.getElementById('chartCat'), {{
  type: 'doughnut',
  data: {{
    labels: labelsCat,
    datasets: [{{ data: valoresCat, backgroundColor: PALETTE, borderWidth: 2, borderColor: '#fff', hoverOffset: 8 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{
      legend: {{ position: 'right', labels: {{ font:{{size:10}}, boxWidth:12, padding:8 }} }},
      tooltip: {{ callbacks: {{ label: ctx => ' $' + ctx.raw.toLocaleString('es-CO') }} }}
    }},
    cutout: '60%'
  }}
}});

// ── Sankey interactivo con Plotly ───────────────────────────────────────────
(function renderSankey() {{
  const container = document.getElementById('sankeyChart');
  if (!container) return;

  const incomeLinks = Object.entries(sankeyIngresosCuentas)
    .map(([to, value]) => ({{ from: 'Ingresos', to, value }}))
    .filter(link => link.value > 0);
  const expenseLinks = sankeyCuentasCategorias
    .map(link => ({{ ...link }}))
    .filter(link => link.value > 0);
  const transferLinks = sankeyTransferencias
    .map(link => ({{ ...link }}))
    .filter(link => link.value > 0);

  const cuentas = [...new Set([
    ...incomeLinks.map(link => link.to),
    ...expenseLinks.map(link => link.from),
    ...transferLinks.flatMap(link => [link.from, link.to]),
  ])];
  const categorias = [...new Set(expenseLinks.map(link => link.to))];

  const nodes = [
    'Ingresos',
    ...cuentas,
    ...categorias,
  ];
  const indexByName = Object.fromEntries(nodes.map((name, index) => [name, index]));

  const links = [
    ...incomeLinks.map(link => ({{ ...link, color: 'rgba(34,197,94,0.35)' }})),
    ...expenseLinks.map(link => ({{ ...link, color: 'rgba(124,92,216,0.35)' }})),
    ...transferLinks.map(link => ({{ ...link, color: 'rgba(15,118,110,0.28)' }})),
  ].filter(link => indexByName[link.from] !== undefined && indexByName[link.to] !== undefined);

  if (!links.length) {{
    container.innerHTML = '<div class="text-sm text-gray-400 italic">Sin flujos para mostrar.</div>';
    return;
  }}

  const nodeColors = nodes.map(name => {{
    if (name === 'Ingresos') return '#16a34a';
    if (categorias.includes(name)) return '#dc2626';
    return '#3b82f6';
  }});

  Plotly.newPlot(container, [{{
    type: 'sankey',
    arrangement: 'snap',
    node: {{
      pad: 18,
      thickness: 18,
      line: {{ color: 'rgba(255,255,255,0.15)', width: 1 }},
      label: nodes,
      color: nodeColors,
      hovertemplate: '%{{label}}<extra></extra>',
    }},
    link: {{
      source: links.map(link => indexByName[link.from]),
      target: links.map(link => indexByName[link.to]),
      value: links.map(link => link.value),
      color: links.map(link => link.color),
      hovertemplate: '%{{source.label}} → %{{target.label}}<br>$%{{value:,.0f}} COP<extra></extra>',
    }},
  }}], {{
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    margin: {{ l: 20, r: 20, t: 10, b: 10 }},
    font: {{ size: 12, color: '#111827' }},
  }}, {{ responsive: true, displayModeBar: false }});
}})();

(function renderCashflowSankey() {{
  const container = document.getElementById('cashflowSankeyChart');
  if (!container) return;

  const links = [
    ...sankeyFlujoFuentes.map(link => ({{ ...link, color: 'rgba(34,197,94,0.35)' }})),
    ...sankeyFlujoCategorias.map(link => ({{ ...link, color: 'rgba(59,130,246,0.25)' }})),
    ...sankeyFlujoSubcategorias.map(link => ({{ ...link, color: 'rgba(239,68,68,0.30)' }})),
  ].filter(link => link.value > 0);

  if (!links.length) {{
    container.innerHTML = '<div class="text-sm text-gray-400 italic">Sin flujo de caja suficiente para mostrar.</div>';
    return;
  }}

  const incomeSources = [...new Set(sankeyFlujoFuentes.map(link => link.to))];
  const expenseCategories = [...new Set(sankeyFlujoCategorias.map(link => link.to))];
  const expenseSubcategories = [...new Set(sankeyFlujoSubcategorias.map(link => link.to))];
  const nodes = ['Ingresos', ...incomeSources, 'Flujo de caja', ...expenseCategories, ...expenseSubcategories];
  const indexByName = Object.fromEntries(nodes.map((name, index) => [name, index]));
  const nodeColors = nodes.map(name => {{
    if (name === 'Ingresos' || incomeSources.includes(name)) return '#16a34a';
    if (name === 'Flujo de caja' || expenseCategories.includes(name)) return '#3b82f6';
    return '#dc2626';
  }});

  Plotly.newPlot(container, [{{
    type: 'sankey',
    arrangement: 'snap',
    node: {{
      pad: 18,
      thickness: 18,
      line: {{ color: 'rgba(255,255,255,0.15)', width: 1 }},
      label: nodes,
      color: nodeColors,
      hovertemplate: '%{{label}}<extra></extra>',
    }},
    link: {{
      source: links.map(link => indexByName[link.from]),
      target: links.map(link => indexByName[link.to]),
      value: links.map(link => link.value),
      color: links.map(link => link.color),
      hovertemplate: '%{{source.label}} → %{{target.label}}<br>$%{{value:,.0f}} COP<extra></extra>',
    }},
  }}], {{
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    margin: {{ l: 20, r: 20, t: 10, b: 10 }},
    font: {{ size: 12, color: '#111827' }},
  }}, {{ responsive: true, displayModeBar: false }});
}})();

// ── Gráfico: Tipo de pago (horizontal bar) ────────────────────────────────
new Chart(document.getElementById('chartTipoPago'), {{
  type: 'bar',
  data: {{
    labels: labelsTp,
    datasets: [{{ label: 'Transacciones', data: valoresTp, backgroundColor: PALETTE, borderRadius: 4 }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ' ' + ctx.raw + ' txn' }} }} }},
    scales: {{ x: {{ ticks: {{ font:{{size:10}} }}, grid: {{ color:'#f1f5f9' }} }}, y: {{ ticks: {{ font:{{size:10}} }}, grid: {{ display:false }} }} }}
  }}
}});

// ── Modo oscuro ───────────────────────────────────────────────────────────
function toggleDark() {{
  document.getElementById('body').classList.toggle('dark');
  document.getElementById('body').classList.toggle('bg-slate-900');
}}
</script>

</body>
</html>"""


if __name__ == "__main__":
    ruta = generar_dashboard()
    print(f"✅ Dashboard listo: {ruta}")
