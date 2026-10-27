#!/usr/bin/env python3
"""
Bootstrap determinista de la Knowledge Base (rules/*.md)
=======================================================

Lee el histórico COMPLETO de Wallet por REST y escribe hechos observados:
contrapartes, categorías, etiquetas, cuentas y rangos de datos.

Reglas de diseño:
  * Cero LLM. Cero MCP. Solo `wallet_client.py` (REST) -> reproducible y barato.
  * No inventa sinónimos ni roles: solo lista lo que aparece en tus datos.
  * El archivo se divide en dos zonas:
        <!-- HECHOS:START -->  ... autogenerado, se reescribe   <!-- HECHOS:END -->
        <!-- CONVENCIONES:START -->  ... tuyo, NUNCA se toca
    Así puedes correrlo de nuevo sin perder lo que escribiste.
  * Idempotente: dos corridas seguidas producen el mismo contenido.

Uso:
    python tools/bootstrap_rules.py
    python tools/bootstrap_rules.py --dry-run
    python tools/bootstrap_rules.py --days 365        # solo último año
    python tools/bootstrap_rules.py --out-dir rules
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for candidato in (HERE, os.path.join(ROOT, "src")):
    if candidato not in sys.path:
        sys.path.insert(0, candidato)

from wallet_client import WalletAPIError, WalletClient  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

HECHOS_START = "<!-- HECHOS:START -->"
HECHOS_END = "<!-- HECHOS:END -->"
CONV_START = "<!-- CONVENCIONES:START -->"
CONV_END = "<!-- CONVENCIONES:END -->"

PISO_HISTORICO = "2000-01-01T00:00:00Z"


# ─────────────────────────────────────────────────────────────────────────────
# Formato
# ─────────────────────────────────────────────────────────────────────────────

def fmt(valor: Optional[float], moneda: str = "COP") -> str:
    """Formato es-CO: 2580398.47 -> '2.580.398,47'."""
    if valor is None:
        return "—"
    signo = "-" if valor < 0 else ""
    cuerpo = f"{abs(valor):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{signo}{cuerpo}"


def fecha_corta(valor: Any) -> str:
    if not isinstance(valor, str) or len(valor) < 10:
        return "—"
    return valor[:10]


def esc(texto: Any) -> str:
    """Escapa pipes para tablas markdown."""
    if texto is None:
        return ""
    return str(texto).replace("|", "\\|").replace("\n", " ").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Accesores tolerantes (el shape de /records varía entre fuentes)
# ─────────────────────────────────────────────────────────────────────────────

def monto_de(rec: Dict[str, Any]) -> float:
    amt = rec.get("amount") or {}
    if isinstance(amt, dict):
        try:
            return float(amt.get("value") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def moneda_de(rec: Dict[str, Any]) -> str:
    amt = rec.get("amount") or {}
    if isinstance(amt, dict):
        return (amt.get("currencyCode") or "COP").upper()
    return "COP"


def indice_categorias(categorias: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """id -> categoría. /records NO trae systemId: hay que cruzarlo por id."""
    return {c["id"]: c for c in categorias if c.get("id")}


def categoria_de(
    rec: Dict[str, Any], por_id: Optional[Dict[str, Dict[str, Any]]] = None
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Devuelve (systemId, categoryId, nombre).

    El registro solo trae {id, name, group}, así que el systemId se resuelve
    cruzando con /categories. Sin ese cruce no se puede escribir por systemId
    y se acabaría usando IDs a ojo (el bug P0 original).
    """
    cat = rec.get("category")
    if not isinstance(cat, dict) or not cat:
        return None, None, None
    cid = cat.get("id")
    nombre = cat.get("name")
    system_id = cat.get("systemId") or cat.get("system_id")
    if not system_id and por_id and cid in por_id:
        system_id = por_id[cid].get("systemId")
        nombre = por_id[cid].get("name") or nombre
    return system_id, cid, nombre


def etiquetas_de(rec: Dict[str, Any]) -> List[str]:
    """Nombres de etiquetas del registro (tolera labels[] y labelIds[])."""
    nombres: List[str] = []
    labels = rec.get("labels")
    if isinstance(labels, list):
        for lab in labels:
            if isinstance(lab, dict) and lab.get("name"):
                nombres.append(str(lab["name"]))
            elif isinstance(lab, str):
                nombres.append(lab)
    if not nombres:
        ids = rec.get("labelIds") or rec.get("label_ids") or []
        if isinstance(ids, list):
            nombres.extend(str(i) for i in ids if isinstance(i, str))
    return nombres


def cuenta_de(rec: Dict[str, Any]) -> str:
    """Nombre de la cuenta. /records expone `accountName` (no `account.name`)."""
    acc = rec.get("account")
    if isinstance(acc, dict) and acc.get("name"):
        return str(acc["name"])
    return str(rec.get("accountName") or rec.get("accountId") or "—")


def terminos_de_nota(texto: str, minimo: int = 4) -> List[str]:
    """Palabras observadas (sin inventar nada): solo normaliza y filtra cortas."""
    limpio = []
    for ch in texto.lower():
        limpio.append(ch if ch.isalnum() or ch in "áéíóúñü" else " ")
    palabras = [p for p in "".join(limpio).split() if len(p) >= minimo and not p.isdigit()]
    return palabras


# ─────────────────────────────────────────────────────────────────────────────
# Escritura con zona humana preservada
# ─────────────────────────────────────────────────────────────────────────────

def seccion_humana_previa(path: str) -> Optional[str]:
    """Extrae el bloque de convenciones de un archivo existente."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            contenido = f.read()
    except OSError:
        return None
    ini = contenido.find(CONV_START)
    if ini == -1:
        return None
    fin = contenido.find(CONV_END, ini)
    if fin == -1:
        return contenido[ini:].rstrip() + "\n"
    return contenido[ini : fin + len(CONV_END)].rstrip() + "\n"


def escribir_md(
    path: str,
    titulo: str,
    intro: str,
    hechos: str,
    convenciones_defecto: str,
    dry_run: bool,
) -> bool:
    """
    Escribe el archivo conservando la zona de convenciones si ya existía.

    Devuelve True si el archivo cambió.
    """
    previa = seccion_humana_previa(path)
    if previa:
        convenciones = previa
        preservada = True
    else:
        convenciones = (
            f"{CONV_START}\n{convenciones_defecto.rstrip()}\n{CONV_END}\n"
        )
        preservada = False

    partes = [
        f"# {titulo}\n",
        f"{intro.rstrip()}\n",
        "",
        "> La zona **HECHOS** se regenera al correr `tools/bootstrap_rules.py`.",
        "> La zona **CONVENCIONES** es tuya: nunca se sobrescribe.",
        "",
        HECHOS_START,
        hechos.rstrip(),
        HECHOS_END,
        "",
        convenciones.rstrip(),
        "",
    ]
    nuevo = "\n".join(partes)

    anterior = None
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            anterior = f.read()

    if anterior == nuevo:
        return False

    if dry_run:
        return True

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(nuevo)
    if preservada:
        print(f"   [ok] {os.path.basename(path)} (convenciones preservadas)")
    else:
        print(f"   [ok] {os.path.basename(path)} (nuevo)")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Recolección
# ─────────────────────────────────────────────────────────────────────────────

def recolectar(client: WalletClient, days: int) -> Dict[str, Any]:
    print("[1/4] Leyendo cuentas...")
    cuentas = client.get_accounts()
    print(f"      {len(cuentas)} cuentas")

    print("[2/4] Leyendo categorías y etiquetas...")
    categorias = client.get_categories()
    etiquetas = client.get_labels()
    print(f"      {len(categorias)} categorías · {len(etiquetas)} etiquetas")

    since = (
        PISO_HISTORICO
        if days <= 0
        else datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    if days > 0:
        from datetime import timedelta

        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        print(f"[3/4] Leyendo registros de los últimos {days} días...")
    else:
        print("[3/4] Leyendo histórico completo de registros...")

    registros = client.get_all_records(since_date=since)
    print(f"      {len(registros)} registros")
    if not registros:
        raise SystemExit(
            "[ABORTA] 0 registros: revisa WALLET_API_TOKEN o la ventana de fechas"
        )

    return {
        "cuentas": cuentas,
        "categorias": categorias,
        "etiquetas": etiquetas,
        "registros": registros,
        "since": since,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Generadores de cada archivo
# ─────────────────────────────────────────────────────────────────────────────

def gen_cuentas(datos: Dict[str, Any]) -> str:
    registros = datos["registros"]
    por_cuenta: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rec in registros:
        por_cuenta[cuenta_de(rec)].append(rec)

    lineas = [
        "| Cuenta | id | Moneda | Tipo | Archivada | Sync banco | Registros | Primer mov. | Último mov. | Saldo actual |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for cuenta in sorted(datos["cuentas"], key=lambda c: (c.get("name") or "").lower()):
        nombre = cuenta.get("name") or "—"
        recs = por_cuenta.get(nombre, [])
        fechas = sorted(fecha_corta(r.get("recordDate")) for r in recs if r.get("recordDate"))
        balance = cuenta.get("balance") or {}
        saldo = balance.get("currentBalance")
        lineas.append(
            "| {n} | `{i}` | {m} | {t} | {a} | {b} | {c} | {p} | {u} | {s} |".format(
                n=esc(nombre),
                i=esc((cuenta.get("id") or "")[:8] + "…"),
                m=esc(cuenta.get("currencyCode") or "—"),
                t=esc(cuenta.get("accountType") or "—"),
                a="sí" if cuenta.get("archived") else "no",
                b="sí" if cuenta.get("isBankSync") else "no",
                c=len(recs),
                p=fechas[0] if fechas else "—",
                u=fechas[-1] if fechas else "—",
                s=fmt(saldo, (cuenta.get("currencyCode") or "COP")),
            )
        )

    totales: Dict[str, float] = defaultdict(float)
    for cuenta in datos["cuentas"]:
        bal = (cuenta.get("balance") or {}).get("currentBalance")
        if bal is not None:
            totales[(cuenta.get("currencyCode") or "COP").upper()] += float(bal)
    resumen = " · ".join(
        f"{fmt(v, m)} {m}" for m, v in sorted(totales.items())
    )

    nota = (
        "\n\n**Sync banco = sí**: la entidad bancaria fija monto, fecha y estado. "
        "Solo se pueden editar categoría, etiquetas, nota y contraparte; no se "
        "pueden crear ni borrar movimientos en esas cuentas.\n"
    )
    return (
        "\n".join(lineas)
        + f"\n\n**Total por moneda (no se suman entre sí):** {resumen}\n"
        + nota
    )


def gen_categorias(datos: Dict[str, Any]) -> str:
    registros = datos["registros"]
    total = len(registros)

    por_id = indice_categorias(datos["categorias"])
    nombres_por_system: Dict[str, str] = {}
    grupo_por_system: Dict[str, str] = {}
    for cat in datos["categorias"]:
        sid = cat.get("systemId")
        if not sid:
            continue
        nombres_por_system[sid] = cat.get("name") or sid
        grupo = cat.get("group") or {}
        grupo_por_system[sid] = (grupo.get("name") if isinstance(grupo, dict) else "") or ""

    conteo: Counter = Counter()
    montos: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    contrapartes: Dict[str, Counter] = defaultdict(Counter)
    terminos: Dict[str, Counter] = defaultdict(Counter)
    tokens_categoria: Dict[str, Counter] = defaultdict(Counter)
    sin_categoria = 0

    # consistencia: contraparte -> systemId -> veces
    por_contraparte: Dict[str, Counter] = defaultdict(Counter)
    for rec in registros:
        sid, _cid, nombre_cat = categoria_de(rec, por_id)
        clave = sid or (f"«{nombre_cat}»" if nombre_cat else "SIN_CATEGORIA")
        if clave == "SIN_CATEGORIA":
            sin_categoria += 1
        conteo[clave] += 1
        moneda = moneda_de(rec)
        montos[clave][moneda] += monto_de(rec)

        cp = (rec.get("counterParty") or "").strip()
        if cp:
            contrapartes[clave][cp] += 1
            por_contraparte[cp][clave] += 1
        nota = rec.get("note") or ""
        for termino in terminos_de_nota(nota):
            terminos[clave][termino] += 1
            tokens_categoria[termino][clave] += 1

    lineas = [
        "| systemId | Nombre en Wallet | Grupo | Registros | % del total | Monto neto (COP) |",
        "|---|---|---|---|---|---|",
    ]
    for clave, n in conteo.most_common():
        if clave == "SIN_CATEGORIA":
            lineas.append(
                f"| *(sin categoría)* | — | — | {n} | {n / total:.1%} | — |"
            )
            continue
        monto_cop = montos[clave].get("COP")
        linea = "| `{sid}` | {nom} | {grupo} | {n} | {pct} | {monto} |".format(
            sid=esc(clave),
            nom=esc(nombres_por_system.get(clave, clave)),
            grupo=esc(grupo_por_system.get(clave, "")),
            n=n,
            pct=f"{n / total:.1%}",
            monto=fmt(monto_cop) if monto_cop is not None else "—",
        )
        otras = {m: v for m, v in montos[clave].items() if m != "COP"}
        if otras:
            linea = linea[:-2] + " · " + " · ".join(f"{fmt(v, m)} {m}" for m, v in otras.items()) + " |"
        lineas.append(linea)

    # consistencia contraparte -> categoría
    filas_cons: List[Tuple[int, str, str, int]] = []
    for cp, cats in por_contraparte.items():
        total_cp = sum(cats.values())
        if total_cp < 3:
            continue
        sid, veces = cats.most_common(1)[0]
        if sid == "SIN_CATEGORIA":
            continue
        nombre = nombres_por_system.get(sid, sid)
        filas_cons.append((total_cp, cp, nombre, int(round(100 * veces / total_cp))))

    filas_cons.sort(key=lambda x: (-x[0], x[1].lower()))
    tabla_cons = [
        "",
        "## Contrapartes observadas (≥3 registros)",
        "",
        "Cuántos registros de cada contraparte caen en la misma categoría.",
        "100 % = siempre la misma. Menos = el agente debe preguntar.",
        "",
        "| Contraparte | Categoría dominante | Registros | Consistencia |",
        "|---|---|---|---|",
    ]
    if filas_cons:
        for total_cp, cp, nombre, pct in filas_cons[:60]:
            tabla_cons.append(f"| {esc(cp)} | {esc(nombre)} | {total_cp} | {pct} % |")
    else:
        tabla_cons.append("| *(sin datos suficientes)* | — | — | — |")

    # Token de nota -> categoría dominante. Es la señal más fuerte del histórico:
    # el agente puede decidir la categoría con solo leer la nota.
    filas_token: List[Tuple[int, str, str, int]] = []
    for token, cats in tokens_categoria.items():
        total_token = sum(cats.values())
        if total_token < 3:
            continue
        sid, veces = cats.most_common(1)[0]
        if sid == "SIN_CATEGORIA":
            continue
        filas_token.append(
            (
                total_token,
                token,
                nombres_por_system.get(sid, sid),
                int(round(100 * veces / total_token)),
            )
        )
    filas_token.sort(key=lambda x: (-x[0], x[1]))

    tabla_terminos = [
        "",
        "## Términos de nota → categoría dominante (≥3 registros)",
        "",
        "Tu vocabulario real. Si escribes ese término, la categoría es casi segura.",
        "Por debajo de 90 % de consistencia, el agente debe preguntar.",
        "",
        "| Término | Categoría dominante | Veces | Consistencia |",
        "|---|---|---|---|",
    ]
    if filas_token:
        for total_token, token, nombre, pct in filas_token[:40]:
            tabla_terminos.append(f"| {esc(token)} | {esc(nombre)} | {total_token} | {pct} % |")
    else:
        tabla_terminos.append("| *(sin notas suficientes)* | — | — | — |")

    pie = (
        f"\n\n**Cobertura:** {total - sin_categoria}/{total} registros con categoría "
        f"({(total - sin_categoria) / total:.1%}). Sin categoría: {sin_categoria}.\n\n"
        "**Los `categoryId` no se muestran a propósito.** Al escribir se resuelve "
        "el ID a partir del `systemId` en runtime; copiar IDs a mano fue el origen "
        "del bug que grababa intereses como comida.\n"
    )
    return "\n".join(lineas + tabla_cons + tabla_terminos) + pie


def gen_etiquetas(datos: Dict[str, Any]) -> str:
    registros = datos["registros"]
    usos: Counter = Counter()
    cuentas: Dict[str, Counter] = defaultdict(Counter)
    cats: Dict[str, Counter] = defaultdict(Counter)
    ejemplo: Dict[str, str] = {}
    ultima_fecha: Dict[str, str] = {}

    por_id = indice_categorias(datos["categorias"])
    nombres_por_system = {
        c["systemId"]: c.get("name")
        for c in datos["categorias"]
        if c.get("systemId")
    }

    for rec in registros:
        sid, _cid, nombre_cat = categoria_de(rec, por_id)
        nombre_categoria = nombres_por_system.get(sid or "", nombre_cat or "sin categoría")
        for etiqueta in etiquetas_de(rec):
            usos[etiqueta] += 1
            cuentas[etiqueta][cuenta_de(rec)] += 1
            cats[etiqueta][nombre_categoria] += 1
            fecha = fecha_corta(rec.get("recordDate"))
            if fecha > ultima_fecha.get(etiqueta, ""):
                ultima_fecha[etiqueta] = fecha
                nota = (rec.get("note") or "").strip()
                if nota:
                    ejemplo[etiqueta] = nota[:70]

    definidas = {e.get("name") for e in datos["etiquetas"] if e.get("name")}
    for nombre in definidas:
        usos.setdefault(nombre, 0)

    lineas = [
        "| Etiqueta | Usos | Último uso | Cuentas | Categorías principales | Nota de ejemplo |",
        "|---|---|---|---|---|---|",
    ]
    for nombre, n in sorted(usos.items(), key=lambda kv: (-kv[1], kv[0].lower())):
        cts = ", ".join(c for c, _ in cuentas[nombre].most_common(4)) or "—"
        cts_cat = ", ".join(c for c, _ in cats[nombre].most_common(3)) or "—"
        lineas.append(
            f"| {esc(nombre)} | {n} | {ultima_fecha.get(nombre, '—')} | "
            f"{esc(cts)} | {esc(cts_cat)} | {esc(ejemplo.get(nombre, '—'))} |"
        )

    sin_uso = [n for n, c in usos.items() if c == 0]
    pie = ""
    if sin_uso:
        pie = (
            f"\n\n**Definidas sin uso:** {', '.join(sorted(sin_uso))} "
            "(candidatas a borrar o a empezar a usar).\n"
        )
    return "\n".join(lineas) + pie


def gen_informes(datos: Dict[str, Any]) -> str:
    registros = datos["registros"]
    fechas = sorted(fecha_corta(r.get("recordDate")) for r in registros if r.get("recordDate"))
    primero, ultimo = (fechas[0], fechas[-1]) if fechas else ("—", "—")
    cuentas_activas = [c for c in datos["cuentas"] if not c.get("archived")]

    monedas = sorted({(c.get("currencyCode") or "COP").upper() for c in datos["cuentas"]})

    return f"""**Inventario disponible ahora mismo**

| Dato | Valor |
|---|---|
| Registros leídos | {len(registros)} |
| Rango de fechas | {primero} → {ultimo} |
| Cuentas activas | {len(cuentas_activas)} |
| Monedas presentes | {', '.join(monedas)} |
| Leído desde | `{datos['since']}` |

---

## Plantillas (intención, no nombres de tool)

Los nombres reales de los tools están en `mcp_tools.md`. Aquí solo la intención.

### 1. Mensual por categoría
- Agrupar los registros del mes por categoría.
- Columnas: Categoría | Ingresos | Gastos | Neto | % del gasto total.
- Preferir una tool de **agregación** (una llamada). Si no hay, traer el mes con
  `limit` acotado y agregar localmente.
- Nunca traer el histórico completo para esto.

### 2. Saldo y últimos movimientos por cuenta
- Saldo: de la lista de cuentas (`currentBalance`).
- Últimos 10 movimientos: por cuenta y por fecha descendente.

### 3. Por etiqueta
- Total y desglose por categoría de los registros con esa etiqueta en la ventana.

### 4. Conciliación contra captura del banco
- Delegar en `tools/conciliar_cuenta.py` con un plan v1.
- Nunca reimplementar el matching en lenguaje natural.

### 5. Rendimiento de una cuenta (TEA mensual)
- `TEA = (1 + interes_mes / saldo_promedio_mes) ^ 12 − 1`
- Solo calcular en meses con saldo promedio > 10.000 COP.
- Meses con saldo ≈ 0 se marcan **no concluyente** (la tasa es ruido).
- Reportar la tabla mes | interés | saldo promedio | TEA, sin redondear a mano.

### 6. Presupuestos (si existen)
- Listar presupuestos con gastado, restante y % de avance del período actual.
- Marcar los que estén por encima del 100 %.

---

## Reglas de coste

- Agregar antes de traer: una agregación vale más que 200 registros.
- Tope por consulta: 50 registros salvo que el humano pida más.
- No volcar JSON crudo al chat: tablas.
- No sumar monedas distintas: reportar por moneda.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Convenciones por defecto (plantillas para el humano)
# ─────────────────────────────────────────────────────────────────────────────

CONV_CUENTAS = """## Mis convenciones

Completa el rol de cada cuenta. El agente lo usa para decidir dónde registrar
un movimiento cuando no dices la cuenta.

| Cuenta | Rol (para qué la uso) | ¿Por defecto para gastos? |
|---|---|---|
| | | |

### Reglas
- Si digo "la de siempre" para gastos → cuenta por defecto: (definir)
- Si digo "la del sueldo" → cuenta: (definir)
"""

CONV_CATEGORIAS = """## Mis convenciones

### Sinónimos que uso al hablar

Añade aquí las palabras que usas tú. A la izquierda tu término; a la derecha el
`systemId` exacto de la tabla de HECHOS.

| Mi término | systemId | Notas |
|---|---|---|
| | | |

### Reglas de categorización
- Si no hay categoría clara, preguntar. No usar "otros" por defecto.
- (añadir reglas propias)
"""

CONV_ETIQUETAS = """## Mis convenciones

### Cuándo uso cada etiqueta

| Etiqueta | Cuándo la uso | Cuándo NO |
|---|---|---|
| | | |

### Etiquetas obligatorias
- (ej.: todo gasto recurrente lleva #suscripcion)
"""

CONV_INFORMES = """## Mis preferencias de informe

- Formato de números: es-CO (2.580.398,47).
- Moneda de reporte: la de cada cuenta, sin conversiones implícitas.
- Período por defecto: mes calendario en curso.
- (añadir preferencias propias)
"""


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera rules/*.md desde el histórico real de Wallet (sin LLM)"
    )
    parser.add_argument("--days", type=int, default=0, help="0 = histórico completo")
    parser.add_argument("--out-dir", default="rules", help="Carpeta de salida")
    parser.add_argument("--dry-run", action="store_true", help="No escribe nada")
    args = parser.parse_args()

    out_dir = args.out_dir if os.path.isabs(args.out_dir) else os.path.join(ROOT, args.out_dir)

    try:
        client = WalletClient(verbose=False)
    except WalletAPIError as exc:
        print(f"[ERROR] {exc}")
        print("        Crea .env con WALLET_API_TOKEN (copia .env.example).")
        raise SystemExit(1)

    try:
        datos = recolectar(client, args.days)
    except WalletAPIError as exc:
        print(f"[ERROR API] {exc}")
        raise SystemExit(1)

    print("[4/4] Escribiendo Knowledge Base...")
    cambios = 0
    cambios += escribir_md(
        os.path.join(out_dir, "cuentas.md"),
        "Cuentas",
        "Qué cuentas existen, en qué moneda y cuánto tienen. Generado desde Wallet.",
        gen_cuentas(datos),
        CONV_CUENTAS,
        args.dry_run,
    )
    cambios += escribir_md(
        os.path.join(out_dir, "categorias.md"),
        "Categorías",
        "Mapeo entre lo que dices y el `systemId` real de Wallet, con la evidencia que lo respalda.",
        gen_categorias(datos),
        CONV_CATEGORIAS,
        args.dry_run,
    )
    cambios += escribir_md(
        os.path.join(out_dir, "etiquetas.md"),
        "Etiquetas",
        "Qué etiquetas existen, cuánto se usan y con qué se asocian.",
        gen_etiquetas(datos),
        CONV_ETIQUETAS,
        args.dry_run,
    )
    cambios += escribir_md(
        os.path.join(out_dir, "informes.md"),
        "Informes",
        "Plantillas de informe y reglas de coste. Intención, no nombres de tool.",
        gen_informes(datos),
        CONV_INFORMES,
        args.dry_run,
    )

    if args.dry_run:
        print(f"\n[DRY-RUN] {cambios} archivo(s) cambiarían. No se escribió nada.")
        return

    print(
        f"\nListo. {cambios} archivo(s) actualizado(s) en {out_dir}"
        if cambios
        else f"\nSin cambios: la KB ya estaba al día ({out_dir})"
    )
    print(
        "\nSiguiente paso (humano):\n"
        "  1. Abre rules/*.md y completa la zona CONVENCIONES (sinónimos, roles).\n"
        "  2. git add rules && git commit -m 'KB v1 validada'\n"
    )


if __name__ == "__main__":
    main()
