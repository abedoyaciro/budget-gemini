"""
Extractor de Datos BudgetBakers Wallet API
==========================================
Extrae snapshot completo de cuentas, categorías, etiquetas y registros
desde la API REST de BudgetBakers Wallet, con todos los campos disponibles.

Autor: Anderson Bedoya Ciro
Versión: 3.0 — Extracción completa según OpenAPI 1.3.0
"""

import os
import sys
import json
import time
import logging
import requests
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

from logging_config import setup_logging, ahora_colombia

logger = setup_logging(__name__)

# Cargar variables de entorno desde .env
load_dotenv()

# Windows: cp1252 no puede codificar emoji/box-drawing. Forzar UTF-8 en stdout
# evita que un print() final convierta una extracción exitosa en exit code 1.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover - entornos sin TTY
        pass


# ─────────────────────────────────────────────────────────────────────────────
# CLASE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

CATEGORY_GROUP_TRANSLATIONS = {
    "financial_expenses": "Gastos financieros",
    "food_and_drinks": "Comida y bebidas",
    "housing": "Vivienda",
    "income": "Ingresos",
    "investments": "Inversiones",
    "life_entertainment": "Vida y entretenimiento",
    "shopping": "Compras",
    "vehicle": "Vehículo",
    "communication_pc": "Comunicación y tecnología",
    "system_categories": "Categorías del sistema",
}

CATEGORY_TRANSLATIONS = {
    "financial_expenses__advisory": "Asesoría",
    "financial_expenses__aliments": "Alimentos (gastos financieros)",
    "financial_expenses__charges_fees": "Cobros y comisiones",
    "financial_expenses__general": "Gastos financieros",
    "financial_expenses__fines": "Multas",
    "financial_expenses__insurances": "Seguros",
    "financial_expenses__loan_interests": "Préstamo e intereses",
    "financial_expenses__taxes": "Impuestos",
    "investments__savings": "Ahorros",
    "food_and_drinks__bar_cafe": "Bar y café",
    "food_and_drinks__general": "Comida y bebidas",
    "food_and_drinks__food_and_drinks": "Comida y bebidas",
    "food_and_drinks__groceries": "Mercado",
    "food_and_drinks__restaurants_fast_food": "Restaurantes y comida rápida",
    "food_and_drinks__restaurants_and_fast_food": "Restaurantes y comida rápida",
    "housing__energy_utilities": "Energía y servicios públicos",
    "housing__general": "Vivienda",
    "housing__housing": "Vivienda",
    "housing__insurance": "Seguro de vivienda",
    "housing__maintenance_repairs": "Mantenimiento y reparaciones",
    "housing__mortgage": "Hipoteca",
    "housing__rent": "Arriendo",
    "housing__services": "Servicios",
    "income__general": "Ingresos",
    "income__income": "Ingresos",
    "income__interest_dividends": "Intereses y dividendos",
    "income__lending_renting": "Préstamos y arriendos",
    "income__wage_invoices": "Salario y facturas",
    "investments__general": "Inversiones",
    "life_entertainment__alcohol_tobacco": "Alcohol y tabaco",
    "life_entertainment__health_care_and_doctor": "Salud y doctor",
    "life_entertainment__hobbies": "Pasatiempos",
    "shopping__general": "Compras",
    "shopping__shopping": "Compras",
    "shopping__clothes_and_shoes": "Ropa y zapatos",
    "shopping__gifts_and_joy": "Regalos y detalles",
    "shopping__health_and_beauty": "Salud y belleza",
    "shopping__jewels_and_accessories": "Joyas y accesorios",
    "shopping__pets_and_animals": "Mascotas y animales",
    "shopping__stationery_and_tools": "Papelería y herramientas",
    "vehicle__fuel": "Combustible",
    "vehicle__general": "Vehículo",
    "vehicle__parking": "Parqueadero",
    "vehicle__vehicle_maintenance": "Mantenimiento del vehículo",
    "communication_pc__phone_cell_phones": "Teléfono y celular",
    "system_categories__transfer": "Transferencia",
}


class WalletContextExtractor:
    """Extrae y enriquece datos financieros desde la API REST de BudgetBakers Wallet."""

    BASE_URL = "https://rest.budgetbakers.com/wallet/v1/api"
    MAX_PAGE_SIZE = 200  # Máximo permitido por la API

    def __init__(self, bearer_token: str) -> None:
        self.headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _obtener_tasa_usd_cop(self) -> Optional[float]:
        """Consulta una tasa USD→COP simple desde un servicio público."""
        try:
            response = requests.get(
                "https://open.er-api.com/v6/latest/USD",
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            tasa = (data.get("rates") or {}).get("COP")
            if tasa is None:
                return None
            return float(tasa)
        except Exception as exc:
            logger.warning("No se pudo obtener tasa USD→COP: %s", exc)
            return None

    # Dominio vigente de Frankfurter (api.frankfurter.app devuelve 404 en fechas
    # recientes). Se usa .dev con fallback al host antiguo.
    FRANKFURTER_HOSTS = ("https://api.frankfurter.dev/v1", "https://api.frankfurter.app")

    def _obtener_tasa_historica(self, fecha: str) -> Optional[float]:
        """Tasa histórica USD→COP para una fecha, probando ambos hosts."""
        for host in self.FRANKFURTER_HOSTS:
            try:
                response = requests.get(
                    f"{host}/{fecha}?base=USD&symbols=COP",
                    timeout=15,
                )
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                tasa = ((response.json() or {}).get("rates") or {}).get("COP")
                if tasa is not None:
                    return float(tasa)
            except Exception:
                continue
        return None

    def _obtener_tasas_historicas_usd_cop(self, fechas_iso: List[str]) -> Dict[str, float]:
        """
        Consulta tasas históricas USD→COP por fecha YYYY-MM-DD.

        Cachea en memoria por corrida para no repetir llamadas y no ensuciar
        el log con warnings repetidos cuando una fecha no está disponible.
        """
        tasas: Dict[str, float] = {}
        fallidas: List[str] = []
        fechas = sorted({(f or "")[:10] for f in fechas_iso if f})
        for fecha in fechas:
            tasa = self._obtener_tasa_historica(fecha)
            if tasa is not None:
                tasas[fecha] = tasa
            else:
                fallidas.append(fecha)
        if fallidas:
            logger.debug(
                "Tasas históricas no disponibles para %d fecha(s): %s",
                len(fallidas),
                ", ".join(fallidas[:5]) + ("…" if len(fallidas) > 5 else ""),
            )
        return tasas

    # ── Capa de transporte ────────────────────────────────────────────────────

    # Reintentos por endpoint: el DNS falla de forma intermitente en Windows
    # (Errno 11001 / 10054). Sin retry, un fallo devolvía datos parciales como
    # si fueran completos.
    MAX_RETRIES = 5

    def _get_json(
        self,
        url: str,
        params: Dict[str, Any],
        endpoint: str,
    ) -> Dict[str, Any]:
        """
        GET con retry/backoff exponencial. Falla fuerte al agotar intentos.

        Nunca devuelve una respuesta parcial: si no se puede leer una página,
        la extracción se aborta para no guardar un snapshot incompleto.
        """
        ultimo_error: Optional[str] = None

        for intento in range(self.MAX_RETRIES):
            try:
                response = requests.get(
                    url, headers=self.headers, params=params, timeout=30
                )

                # La cabecera puede no venir: es informativa, no bloqueante.
                remaining = response.headers.get("X-RateLimit-Remaining")
                if remaining is not None:
                    try:
                        if int(remaining) < 10:
                            logger.warning(
                                "Cuota de API baja. Restantes: %s", remaining
                            )
                    except ValueError:
                        pass

                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {"items": data}

            except requests.exceptions.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                ultimo_error = f"HTTP {status}: {exc}"
                # 4xx (salvo 429) no se arregla reintentando
                if status and 400 <= status < 500 and status != 429:
                    if status == 401:
                        logger.error(
                            "401 Unauthorized: verifica que WALLET_API_TOKEN no haya expirado."
                        )
                    raise RuntimeError(
                        f"GET /{endpoint} falló con {ultimo_error}"
                    ) from exc
            except ValueError as exc:
                raise RuntimeError(
                    f"GET /{endpoint} devolvió JSON inválido: {exc}"
                ) from exc
            except requests.exceptions.RequestException as exc:
                ultimo_error = f"{type(exc).__name__}: {exc}"

            if intento < self.MAX_RETRIES - 1:
                delay = min(1.5 * (2 ** intento), 15.0)
                logger.warning(
                    "Reintento %d/%d en GET /%s (%s) tras %.1fs",
                    intento + 1,
                    self.MAX_RETRIES,
                    endpoint,
                    (ultimo_error or "").split(":")[0],
                    delay,
                )
                time.sleep(delay)

        raise RuntimeError(
            f"GET /{endpoint} falló tras {self.MAX_RETRIES} intentos: {ultimo_error}"
        )

    def _get_paginated(
        self,
        endpoint: str,
        data_key: str,
        extra_params: Optional[Dict[str, Any]] = None,
        max_records: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        GET paginado con nextOffset hasta agotar páginas.

        Args:
            endpoint:     Ruta relativa (ej. "accounts", "records").
            data_key:     Clave del array en la respuesta JSON.
            extra_params: Parámetros de consulta adicionales (filtros).
            max_records:  Tope TOTAL de ítems. Se pagina completo y luego se
                          trunca: nunca se corta la paginación a mitad.

        Returns:
            Lista de objetos recuperados.

        Raises:
            RuntimeError: si alguna página falla tras los reintentos. Se
            prefiere fallar a devolver datos parciales como si fueran completos.
        """
        url = f"{self.BASE_URL}/{endpoint}"
        resultados: List[Dict[str, Any]] = []
        offset = 0
        paginas = 0

        while True:
            # limit > 200 devuelve 400: se capea siempre a MAX_PAGE_SIZE.
            params: Dict[str, Any] = {
                "limit": self.MAX_PAGE_SIZE,
                "offset": offset,
            }
            if extra_params:
                # El caller no puede imponer un limit mayor al máximo de la API
                filtros = {k: v for k, v in extra_params.items() if k != "limit"}
                params.update(filtros)

            data = self._get_json(url, params, endpoint)
            page_items = data.get(data_key) or data.get("items") or []
            if not isinstance(page_items, list):
                raise RuntimeError(
                    f"Respuesta inesperada en /{endpoint}: '{data_key}' no es lista"
                )

            resultados.extend(page_items)
            paginas += 1

            next_offset = data.get("nextOffset")
            if (
                next_offset is None
                or not page_items
                or next_offset == offset
                or len(page_items) < self.MAX_PAGE_SIZE
            ):
                break

            offset = next_offset

        logger.debug(
            "GET /%s -> %d ítems en %d página(s)", endpoint, len(resultados), paginas
        )

        if max_records is not None and len(resultados) > max_records:
            logger.warning(
                "Se recuperaron %d ítems en /%s; se truncan a max_records=%d",
                len(resultados),
                endpoint,
                max_records,
            )
            return resultados[:max_records]

        return resultados

    # ── Mapas de lookup ───────────────────────────────────────────────────────

    def _build_lookup_maps(
        self,
        accounts: List[Dict],
        categories: List[Dict],
        labels: List[Dict],
    ) -> Tuple[Dict, Dict, Dict]:
        """
        Construye mapas id → objeto completo para lookups rápidos.

        Returns:
            Tupla (account_map, category_map, label_map).
        """
        account_map = {a["id"]: a for a in accounts if isinstance(a, dict) and a.get("id")}
        category_map = {c["id"]: c for c in categories if isinstance(c, dict) and c.get("id")}
        label_map = {l["id"]: l for l in labels if isinstance(l, dict) and l.get("id")}
        return account_map, category_map, label_map

    # ── Transformadores de entidades ──────────────────────────────────────────

    def _transform_account(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transforma una cuenta cruda al formato normalizado del snapshot.

        Campos del schema Account (OpenAPI 1.3.0):
          id, name, accountType, color, bankAccountNumber,
          isBankSync, isInvestmentAccount, excludeFromStats,
          initialBalance {value, currencyCode},
          balance {currencyCode, currentBalance, rawCurrentBalance,
                   initial, formula, balanceMode, ...},
          recordStats {recordCount, totalIncomes, totalExpenses,
                       recordDate.min/.max, createdAt.min/.max, lastUpdatedAt},
          archived, createdAt, updatedAt
        """
        initial_balance = raw.get("initialBalance") or {}
        balance = raw.get("balance") or {}
        record_stats = raw.get("recordStats") or {}

        return {
            # Identificación
            "id": raw.get("id"),
            "nombre": raw.get("name"),
            # Tipo y moneda — campos CORRECTOS según el schema
            "tipo": raw.get("accountType"),           # ej. "CurrentAccount", "SavingAccount"…
            "moneda": (
                initial_balance.get("currencyCode")   # moneda principal de la cuenta
                or balance.get("currencyCode")
            ),
            # Atributos adicionales
            "color": raw.get("color"),
            "numero_bancario": raw.get("bankAccountNumber"),
            "es_banco_sync": raw.get("isBankSync", False),
            "es_inversion": raw.get("isInvestmentAccount", False),
            "excluir_estadisticas": raw.get("excludeFromStats", False),
            "archivada": raw.get("archived", False),
            # Balance detallado (ya viene calculado por la API)
            "balance": balance if balance else None,
            # Estadísticas de registros
            "estadisticas_registros": {
                "total_registros": record_stats.get("recordCount"),
                "total_ingresos": record_stats.get("totalIncomes"),
                "total_gastos": record_stats.get("totalExpenses"),
                "fecha_primer_registro": (record_stats.get("recordDate") or {}).get("min"),
                "fecha_ultimo_registro": (record_stats.get("recordDate") or {}).get("max"),
                "ultima_actualizacion": record_stats.get("lastUpdatedAt"),
            } if record_stats else None,
            # Auditoría
            "creado_en": raw.get("createdAt"),
            "actualizado_en": raw.get("updatedAt"),
        }

    def _transform_category(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transforma una categoría cruda al formato normalizado.

        Campos del schema Category (OpenAPI 1.3.0):
          id, name, parentId, color, customCategory, customName,
          enabled, archived, cardinality, systemId,
          group {id, name}, createdAt, updatedAt
        """
        group = raw.get("group") or {}
        system_id = raw.get("systemId")
        group_id = group.get("id")
        nombre = raw.get("name")
        grupo_nombre = group.get("name")
        return {
            "id": raw.get("id"),
            "nombre": nombre,
            "nombre_es": CATEGORY_TRANSLATIONS.get(system_id, nombre),
            "id_padre": raw.get("parentId"),          # None = categoría raíz
            "grupo": {
                "id": group_id,                        # slug estable, ej. "food_and_drinks"
                "nombre": grupo_nombre,
                "nombre_es": CATEGORY_GROUP_TRANSLATIONS.get(group_id, grupo_nombre),
            } if group else None,
            "color": raw.get("color"),
            "sistema_id": system_id,                  # slug de categoría del sistema
            "es_personalizada": raw.get("customCategory", False),
            "activa": raw.get("enabled", True),
            "archivada": raw.get("archived", False),
            "cardinalidad": raw.get("cardinality"),   # none/must/need/want
            "creado_en": raw.get("createdAt"),
            "actualizado_en": raw.get("updatedAt"),
        }

    def _transform_label(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transforma una etiqueta cruda al formato normalizado.

        Campos del schema Label (OpenAPI 1.3.0):
          id, name, color, archived, createdAt, updatedAt
        """
        return {
            "id": raw.get("id"),
            "nombre": raw.get("name"),
            "color": raw.get("color"),
            "archivada": raw.get("archived", False),
            "creado_en": raw.get("createdAt"),
            "actualizado_en": raw.get("updatedAt"),
        }

    def _transform_record(
        self,
        raw: Dict[str, Any],
        account_map: Dict,
        category_map: Dict,
        label_map: Dict,
    ) -> Dict[str, Any]:
        """
        Transforma un registro crudo al formato normalizado y enriquecido.

        Campos del schema Record (OpenAPI 1.3.0):
          id, recordDate, recordType, recordState, paymentType,
          amount {value, currencyCode},
          convertedAmount {value, currencyCode, ratio, conversionPair},
          note, counterParty, source,
          accountId, accountName, accountIsBankSync,
          category {id, name, color, group},
          labels [{id, name, color, archived}],
          transferRecord {id, accountId, amount, note, counterParty},
          place {name, address, latitude, longitude},
          photos [{temporaryUrl, createdAt}],
          createdAt, updatedAt
        """
        # ── Amount ──────────────────────────────────────────────────────────
        amount_raw = raw.get("amount") or {}
        amount_value = amount_raw.get("value")
        amount_currency = amount_raw.get("currencyCode")

        # ── Tipo derivado de amount si recordType no está disponible ─────────
        record_type = raw.get("recordType")  # "income" | "expense"
        if not record_type and amount_value is not None:
            record_type = "income" if amount_value > 0 else "expense"

        # ── Cuenta ──────────────────────────────────────────────────────────
        account_id = raw.get("accountId")
        # La API embebe accountName directamente en el registro
        account_name = raw.get("accountName") or (
            account_map.get(account_id, {}).get("name") if account_id else None
        )

        # ── Categoría (embebida en el registro) ──────────────────────────────
        cat_raw = raw.get("category") or {}
        cat_group = cat_raw.get("group") or {}
        cat_system_id = cat_raw.get("systemId")
        if not cat_system_id and cat_group.get("id") and cat_raw.get("name"):
            cat_name_slug = (
                str(cat_raw.get("name"))
                .lower()
                .replace("&", "and")
                .replace(",", "")
                .replace("(", "")
                .replace(")", "")
                .replace("/", " ")
                .replace("-", " ")
                .replace("  ", " ")
                .strip()
                .replace(" ", "_")
            )
            cat_system_id = f"{cat_group.get('id')}__{cat_name_slug}"

        # ── Etiquetas (embebidas en el registro) ─────────────────────────────
        labels_raw = raw.get("labels") or []
        etiquetas = [
            {
                "id": lbl.get("id"),
                "nombre": lbl.get("name"),
                "color": lbl.get("color"),
                "archivada": lbl.get("archived", False),
            }
            for lbl in labels_raw
            if isinstance(lbl, dict)
        ]

        # ── Transferencia enlazada ───────────────────────────────────────────
        transfer_raw = raw.get("transferRecord") or {}
        transferencia = None
        if transfer_raw and transfer_raw.get("id"):
            tr_amount = transfer_raw.get("amount") or {}
            transferencia = {
                "id": transfer_raw.get("id"),
                "cuenta_id": transfer_raw.get("accountId"),
                "cuenta_nombre": account_map.get(transfer_raw.get("accountId"), {}).get("name"),
                "monto": {
                    "valor": tr_amount.get("value"),
                    "moneda": tr_amount.get("currencyCode"),
                },
                "nota": transfer_raw.get("note"),
                "contraparte": transfer_raw.get("counterParty"),
            }

        # ── Lugar ────────────────────────────────────────────────────────────
        place_raw = raw.get("place") or {}
        lugar = None
        if place_raw and (place_raw.get("name") or place_raw.get("address")):
            lugar = {
                "nombre": place_raw.get("name"),
                "direccion": place_raw.get("address"),
                "latitud": place_raw.get("latitude"),
                "longitud": place_raw.get("longitude"),
            }

        # ── Monto convertido (si la API lo devuelve) ─────────────────────────
        converted_raw = raw.get("convertedAmount") or {}
        monto_convertido = None
        if converted_raw and converted_raw.get("value") is not None:
            monto_convertido = {
                "valor": converted_raw.get("value"),
                "moneda": converted_raw.get("currencyCode"),
                "tasa": converted_raw.get("ratio"),
                "par": converted_raw.get("conversionPair"),
            }

        return {
            # ── Identificación ──────────────────────────────────────────────
            "id": raw.get("id"),
            # ── Temporalidad ────────────────────────────────────────────────
            "fecha": raw.get("recordDate"),
            "creado_en": raw.get("createdAt"),
            "actualizado_en": raw.get("updatedAt"),
            # ── Clasificación ────────────────────────────────────────────────
            "tipo": record_type,               # "income" | "expense"
            "estado": raw.get("recordState"),  # "cleared" | "reconciled" | "uncleared" | "void"
            "tipo_pago": raw.get("paymentType"),
            "origen": raw.get("source"),       # "android"|"ios"|"web"|"rest"|"mcp"|"backend"
            # ── Monto ────────────────────────────────────────────────────────
            "monto": {
                "valor": amount_value,
                "moneda": amount_currency,
            },
            "monto_convertido": monto_convertido,
            # ── Descripción ──────────────────────────────────────────────────
            "nota": raw.get("note", ""),
            "contraparte": raw.get("counterParty"),  # Payee/merchant
            # ── Cuenta ───────────────────────────────────────────────────────
            "cuenta": {
                "id": account_id,
                "nombre": account_name,
                "es_banco_sync": raw.get("accountIsBankSync"),
            },
            # ── Categoría (embebida) ──────────────────────────────────────────
            "categoria": {
                "id": cat_raw.get("id"),
                "nombre": cat_raw.get("name"),
                "nombre_es": CATEGORY_TRANSLATIONS.get(cat_system_id, cat_raw.get("name")),
                "color": cat_raw.get("color"),
                "grupo_id": cat_group.get("id"),
                "grupo_nombre": cat_group.get("name"),
                "grupo_nombre_es": CATEGORY_GROUP_TRANSLATIONS.get(cat_group.get("id"), cat_group.get("name")),
                "sistema_id": cat_system_id,
            } if cat_raw else {"id": None, "nombre": "Sin categoría", "nombre_es": "Sin categoría"},
            # ── Etiquetas (embebidas) ─────────────────────────────────────────
            "etiquetas": etiquetas,
            # ── Transferencia enlazada ────────────────────────────────────────
            "transferencia": transferencia,
            # ── Lugar ─────────────────────────────────────────────────────────
            "lugar": lugar,
        }

    # ── Orquestador principal ─────────────────────────────────────────────────

    # Piso absoluto de la ventana cuando days_back == 0.
    # Sin recordDate la API devuelve un subset (22 registros en vez de todo),
    # así que NUNCA se omite el filtro: se usa una fecha muy antigua.
    SIN_LIMITE_DESDE = "2000-01-01T00:00:00Z"

    def get_context_snapshot(
        self,
        records_limit: Optional[int] = None,
        days_back: int = 90,
    ) -> Dict[str, Any]:
        """
        Extrae un snapshot completo y enriquecido de los datos de Wallet.

        Args:
            records_limit: Tope TOTAL de registros. None = sin tope (se pagina
                           hasta agotar). Se pagina completo y luego se trunca;
                           nunca se corta la paginación a mitad.
            days_back:     Ventana temporal en días hacia atrás para los registros
                           (por defecto 90 días). 0 = histórico completo, que se
                           implementa con un piso de fecha explícito, no omitiendo
                           el filtro.

        Returns:
            Diccionario con snapshot completo incluyendo metadata.

        Raises:
            RuntimeError: si la API falla tras los reintentos.
        """
        logger.info("Iniciando extracción de BudgetBakers Wallet API…")
        extraction_start = ahora_colombia()

        # ── 1. Cuentas ───────────────────────────────────────────────────────
        accounts_raw = self._get_paginated("accounts", "accounts")
        logger.info("   [+] Cuentas: %d obtenidas", len(accounts_raw))

        # ── 2. Categorías ────────────────────────────────────────────────────
        categories_raw = self._get_paginated("categories", "categories")
        logger.info("   [+] Categorías: %d obtenidas", len(categories_raw))

        # ── 3. Etiquetas ─────────────────────────────────────────────────────
        labels_raw = self._get_paginated("labels", "labels")
        logger.info("   [+] Etiquetas: %d obtenidas", len(labels_raw))

        # ── 4. Registros (recordDate SIEMPRE presente) ───────────────────────
        if days_back > 0:
            since = (extraction_start - timedelta(days=days_back)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            ventana_descripcion = f"últimos {days_back} días"
        else:
            since = self.SIN_LIMITE_DESDE
            ventana_descripcion = "histórico completo"

        record_params: Dict[str, Any] = {"recordDate": f"gte.{since}"}
        logger.info("   -> Registros desde %s (%s)", since, ventana_descripcion)

        records_raw = self._get_paginated(
            "records", "records", extra_params=record_params, max_records=records_limit
        )
        logger.info("   [+] Registros: %d obtenidos", len(records_raw))

        # ── 5. Construir mapas de lookup ─────────────────────────────────────
        account_map, category_map, label_map = self._build_lookup_maps(
            accounts_raw, categories_raw, labels_raw
        )

        # ── 6. Transformar entidades ─────────────────────────────────────────
        logger.info("   🔄 Transformando y normalizando entidades…")

        cuentas = [
            self._transform_account(a)
            for a in accounts_raw
            if isinstance(a, dict)
        ]

        categorias = [
            self._transform_category(c)
            for c in categories_raw
            if isinstance(c, dict)
        ]

        etiquetas = [
            self._transform_label(l)
            for l in labels_raw
            if isinstance(l, dict)
        ]

        registros = [
            self._transform_record(r, account_map, category_map, label_map)
            for r in records_raw
            if isinstance(r, dict)
        ]

        extraction_end = ahora_colombia()
        duration = (extraction_end - extraction_start).total_seconds()

        # ── 7. Estadísticas enriquecidas ─────────────────────────────────────
        ingresos = [r for r in registros if r.get("tipo") == "income"]
        gastos = [r for r in registros if r.get("tipo") == "expense"]
        tasa_usd_cop = self._obtener_tasa_usd_cop()
        tasas_historicas_usd_cop = self._obtener_tasas_historicas_usd_cop([
            r.get("fecha") for r in registros if r.get("monto", {}).get("moneda") == "USD"
        ])

        for r in registros:
            monto = r.get("monto", {}) or {}
            moneda = monto.get("moneda")
            valor = monto.get("valor") or 0
            fecha = (r.get("fecha") or "")[:10]
            tasa_historica = tasas_historicas_usd_cop.get(fecha)
            if moneda == "USD" and tasa_historica:
                r["monto_historico_cop"] = {
                    "valor": round(float(valor) * float(tasa_historica), 2),
                    "moneda": "COP",
                    "tasa_usd_cop": round(float(tasa_historica), 6),
                    "fecha_tasa": fecha,
                }
            else:
                r["monto_historico_cop"] = None

        total_ingresos_cop = sum(
            r["monto"]["valor"] for r in ingresos
            if r.get("monto", {}).get("moneda") == "COP" and r["monto"]["valor"]
        )
        total_gastos_cop = sum(
            abs(r["monto"]["valor"]) for r in gastos
            if r.get("monto", {}).get("moneda") == "COP" and r["monto"]["valor"]
        )
        total_ingresos_usd = sum(
            r["monto"]["valor"] for r in ingresos
            if r.get("monto", {}).get("moneda") == "USD" and r["monto"]["valor"]
        )
        total_gastos_usd = sum(
            abs(r["monto"]["valor"]) for r in gastos
            if r.get("monto", {}).get("moneda") == "USD" and r["monto"]["valor"]
        )
        ingresos_usd_en_cop_historico = round(sum(
            (r.get("monto_historico_cop") or {}).get("valor", 0) or 0
            for r in ingresos
            if r.get("monto", {}).get("moneda") == "USD"
        ), 2)
        gastos_usd_en_cop_historico = round(sum(
            abs((r.get("monto_historico_cop") or {}).get("valor", 0) or 0)
            for r in gastos
            if r.get("monto", {}).get("moneda") == "USD"
        ), 2)

        ingresos_usd_en_cop = round(total_ingresos_usd * tasa_usd_cop, 2) if tasa_usd_cop else 0
        gastos_usd_en_cop = round(total_gastos_usd * tasa_usd_cop, 2) if tasa_usd_cop else 0
        balance_neto_usd = round(total_ingresos_usd - total_gastos_usd, 2)
        balance_neto_global_cop = round(
            total_ingresos_cop + ingresos_usd_en_cop_historico - total_gastos_cop - gastos_usd_en_cop_historico,
            2,
        )

        balances_por_moneda = {}
        for moneda in ("COP", "USD"):
            cuentas_moneda = [
                c for c in cuentas
                if c.get("moneda") == moneda and not c.get("archivada")
            ]
            balances_por_moneda[moneda] = round(sum(
                (c.get("balance") or {}).get("currentBalance", 0) or 0
                for c in cuentas_moneda
            ), 2)

        estadisticas = {
            "total_cuentas": len(cuentas),
            "total_categorias": len(categorias),
            "total_etiquetas": len(etiquetas),
            "total_registros": len(registros),
            "registros_ingreso": len(ingresos),
            "registros_gasto": len(gastos),
            "registros_con_etiquetas": len([r for r in registros if r.get("etiquetas")]),
            "registros_sin_categoria": len(
                [r for r in registros if not r.get("categoria", {}).get("id")]
            ),
            "registros_con_contraparte": len(
                [r for r in registros if r.get("contraparte")]
            ),
            "registros_transferencia": len(
                [r for r in registros if r.get("transferencia")]
            ),
            "tasa_usd_cop": round(tasa_usd_cop, 4) if tasa_usd_cop else None,
            "tasas_historicas_usd_cop": tasas_historicas_usd_cop,
            "suma_ingresos_cop": round(total_ingresos_cop, 2),
            "suma_gastos_cop": round(total_gastos_cop, 2),
            "balance_neto_cop": round(total_ingresos_cop - total_gastos_cop, 2),
            "suma_ingresos_usd": round(total_ingresos_usd, 2),
            "suma_gastos_usd": round(total_gastos_usd, 2),
            "balance_neto_usd": balance_neto_usd,
            "suma_ingresos_usd_en_cop": ingresos_usd_en_cop,
            "suma_gastos_usd_en_cop": gastos_usd_en_cop,
            "suma_ingresos_usd_en_cop_historico": ingresos_usd_en_cop_historico,
            "suma_gastos_usd_en_cop_historico": gastos_usd_en_cop_historico,
            "balance_neto_global_cop": balance_neto_global_cop,
            "balance_cuentas_cop": balances_por_moneda["COP"],
            "balance_cuentas_usd": balances_por_moneda["USD"],
            "balance_cuentas_usd_en_cop": round(balances_por_moneda["USD"] * tasa_usd_cop, 2) if tasa_usd_cop else 0,
        }

        # ── 8. Snapshot final ─────────────────────────────────────────────────
        # `tipo_extraccion` refleja la ventana realmente usada, para que no haya
        # incoherencia entre la metadata del envelope y la del snapshot.
        tipo_extraccion = "full" if days_back <= 0 else "ventana"

        snapshot = {
            "metadata": {
                "version": "3.1.0",
                "extraccion_timestamp": extraction_start.isoformat(),
                "extraccion_duracion_segundos": round(duration, 2),
                "ventana_dias": days_back,
                "ventana_desde": since,
                "ventana_descripcion": ventana_descripcion,
                "tipo_extraccion": tipo_extraccion,
                "records_limit": records_limit,
                "registros_solicitados_tope": records_limit,
                "api_base_url": self.BASE_URL,
                "api_version": "1.3.0",
                "paginacion": "nextOffset",
                "max_page_size": self.MAX_PAGE_SIZE,
            },
            "cuentas": cuentas,
            "categorias": categorias,
            "etiquetas": etiquetas,
            "registros": registros,
            "estadisticas": estadisticas,
        }

        logger.info("Extracción finalizada en %.2f s", duration)
        return snapshot


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_cop(valor: float) -> str:
    """Formato es-CO: separador de miles '.', decimal ','."""
    signo = "-" if valor < 0 else ""
    cuerpo = f"{abs(valor):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{signo}{cuerpo}"


if __name__ == "__main__":
    TOKEN = os.getenv("WALLET_API_TOKEN")

    if not TOKEN:
        logger.error(
            "La variable WALLET_API_TOKEN no está configurada en .env\n"
            "Agrega: WALLET_API_TOKEN=tu_token_aqui"
        )
        sys.exit(1)

    extractor = WalletContextExtractor(TOKEN)

    # Configurable vía .env o docker-compose.yml:
    #   RECORDS_LIMIT=200   -> tope total de registros (0 o vacío = sin tope)
    #   DAYS_BACK=90        -> ventana en días (0 = histórico completo)
    records_limit_env = os.getenv("RECORDS_LIMIT", "0").strip()
    records_limit = int(records_limit_env) if records_limit_env else 0
    records_limit_arg = records_limit if records_limit > 0 else None
    days_back = int(os.getenv("DAYS_BACK", 90))

    try:
        snapshot_data = extractor.get_context_snapshot(
            records_limit=records_limit_arg, days_back=days_back
        )
    except RuntimeError as exc:
        logger.error("Extracción abortada: %s", exc)
        sys.exit(1)

    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "snapshot_wallet.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_data, f, indent=4, ensure_ascii=False)

    stats = snapshot_data["estadisticas"]
    meta = snapshot_data["metadata"]

    print(f"\nSnapshot guardado en '{output_path}'")
    print(f"\nRESUMEN DE EXTRACCION (v{meta['version']})")
    print("   " + "-" * 50)
    print(f"   Cuentas activas        : {stats['total_cuentas']}")
    print(f"   Categorias             : {stats['total_categorias']}")
    print(f"   Etiquetas              : {stats['total_etiquetas']}")
    print(f"   Registros extraidos    : {stats['total_registros']}")
    print(f"   -- Ingresos            : {stats['registros_ingreso']}")
    print(f"   -- Gastos              : {stats['registros_gasto']}")
    print("   " + "-" * 50)
    print(f"   Con etiquetas          : {stats['registros_con_etiquetas']}")
    print(f"   Sin categoria          : {stats['registros_sin_categoria']}")
    print(f"   Con contraparte        : {stats['registros_con_contraparte']}")
    print(f"   Transferencias         : {stats['registros_transferencia']}")
    print("   " + "-" * 50)
    print(f"   Ingresos COP           : {_fmt_cop(stats['suma_ingresos_cop'])}")
    print(f"   Gastos COP             : {_fmt_cop(stats['suma_gastos_cop'])}")
    print(f"   Balance neto COP       : {_fmt_cop(stats['balance_neto_cop'])}")
    print(f"   Ingresos USD           : {stats['suma_ingresos_usd']:,.2f}")
    print(f"   Gastos USD             : {stats['suma_gastos_usd']:,.2f}")
    print(f"   Balance neto USD       : {stats['balance_neto_usd']:,.2f}")
    if stats.get("tasa_usd_cop"):
        print(f"   Tasa USD->COP          : {_fmt_cop(stats['tasa_usd_cop'])}")
        print(f"   Balance global COP     : {_fmt_cop(stats.get('balance_neto_global_cop', stats['balance_neto_cop']))}")
    print("   " + "-" * 50)
    print(f"   Duracion               : {meta['extraccion_duracion_segundos']:.2f} s")
    print(f"   Ventana                : {meta['ventana_descripcion']} (desde {meta['ventana_desde']})")
    print(f"\nSnapshot v{meta['version']} generado exitosamente")
    print(f"   Timestamp: {meta['extraccion_timestamp']}")
