#!/usr/bin/env python3
"""
Cliente HTTP para BudgetBakers Wallet REST API
==============================================

Única fuente de verdad para contratos de la API. Todos los módulos deben
usar este cliente en lugar de hablar HTTP directamente.

Contratos verificados empíricamente (no solo OpenAPI):

P0 — bugs que corrompían datos y quedan encapsulados aquí:
  * categoryId se resuelve SIEMPRE por systemId en runtime (GET /categories).
    Se aborta si no hay match exacto. Nunca IDs literales.
  * GET /records SIEMPRE exige recordDate=gte.<ISO>. Solo con accountId
    la API devuelve 200 con 0 registros.
  * POST /records y PATCH /records exigen array raíz. Envolver en
    {"records": [...]} devuelve 400 cannot unmarshal object into Go value.
  * Campos NO escribibles (la API rechaza con 400, no los ignora):
    recordType, recordState, source, paymentType.
    Solo se aceptan: accountId, amount{value,currencyCode}, recordDate,
    note, categoryId, counterParty, labelIds.
  * PATCH /accounts/{id} no existe (404). Es batch sobre la colección:
    PATCH /accounts con [{id, initialBalance}].

P1 — contratos documentados:
  * El pareo de transferencias NO se hace con pairingMode (no existe).
    La API devuelve en cada registro:
        transfer: {type: "paired", transferId, mirrorRecord}
    El espejo se crea como un registro normal en la cuenta contraparte.
  * limit > 200 devuelve 400. Paginar con nextOffset.
  * X-RateLimit-Remaining no siempre viene: nunca condicionar el flujo a ella.
  * Límites de batch: OpenAPI declara maxItems 50 (create) y 10 (patch).
    NO VERIFICADOS empíricamente; se respetan como cota conservadora.

P2 — entorno Windows:
  * Retry con backoff exponencial ante errores de red/DNS (Errno 11001/10054).
  * Falla fuerte: nunca devuelve datos parciales como si fueran completos.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterable, List, Optional

import requests

BASE_URL = "https://rest.budgetbakers.com/wallet/v1/api"

# Límite duro de la API por página (limit > 200 -> 400).
MAX_PAGE_SIZE = 200

# Cotas de batch. OpenAPI declara maxItems 50 en create y 10 en patch.
# NO CONFIRMADAS empíricamente: se usan como cota conservadora.
BATCH_CREATE_LIMIT = 50
BATCH_PATCH_LIMIT = 10

# SystemIds canónicos. El categoryId SIEMPRE se resuelve en runtime.
SYSTEM_ID_INTEREST_DIVIDENDS = "income__interest_dividends"
SYSTEM_ID_TRANSFER = "system_categories__transfer"

# Campos que la API acepta al escribir un registro.
WRITABLE_RECORD_FIELDS = {
    "accountId",
    "amount",
    "recordDate",
    "note",
    "categoryId",
    "counterParty",
    "labelIds",
}

# Campos que la API rechaza con 400.
FORBIDDEN_RECORD_FIELDS = {"recordType", "recordState", "source", "paymentType"}


class WalletAPIError(RuntimeError):
    """Error definitivo de la API (no reintentable)."""

    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class CategoryNotFoundError(WalletAPIError):
    """El systemId no existe en la cuenta: se aborta para no escribir basura."""


class WalletClient:
    """Cliente mínimo, explícito y con contratos correctos."""

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: str = BASE_URL,
        max_retries: int = 5,
        timeout: int = 30,
        verbose: bool = True,
    ) -> None:
        token = token or os.getenv("WALLET_API_TOKEN")
        if not token:
            raise WalletAPIError("WALLET_API_TOKEN no configurado")
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.timeout = timeout
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self._categories_by_system_id: Optional[Dict[str, Dict[str, Any]]] = None
        self.last_rate_limit: Dict[str, Optional[str]] = {
            "limit": None,
            "remaining": None,
        }

    # ── Transporte ────────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
    ) -> Dict[str, Any]:
        """
        Ejecuta la petición con retry/backoff.

        Reintenta: errores de red (DNS, timeout, conexión reseteada) y 5xx.
        No reintenta: 4xx (error de cliente, reintentar no ayuda).

        Falla fuerte al agotar intentos: nunca devuelve datos parciales.
        """
        url = f"{self.base_url}{path}"
        last_error: Optional[str] = None

        for attempt in range(self.max_retries):
            try:
                resp = self.session.request(
                    method, url, params=params, json=json, timeout=self.timeout
                )

                # La cabecera de rate limit es informativa, nunca bloqueante.
                self.last_rate_limit["limit"] = resp.headers.get("X-RateLimit-Limit")
                self.last_rate_limit["remaining"] = resp.headers.get(
                    "X-RateLimit-Remaining"
                )

                if resp.status_code < 500:
                    return self._handle_response(method, url, resp)

                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"

            except requests.exceptions.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt < self.max_retries - 1:
                delay = min(1.5 * (2 ** attempt), 15.0)
                self._log(
                    f"   [RETRY {attempt + 1}/{self.max_retries}] {method} {path} "
                    f"falló ({last_error.split(':')[0]}), reintento en {delay:.1f}s"
                )
                time.sleep(delay)

        raise WalletAPIError(
            f"{method} {url} falló tras {self.max_retries} intentos: {last_error}"
        )

    def _handle_response(
        self, method: str, url: str, resp: requests.Response
    ) -> Dict[str, Any]:
        if resp.status_code >= 400:
            raise WalletAPIError(
                f"{method} {url} -> HTTP {resp.status_code}: {resp.text[:500]}",
                status=resp.status_code,
                body=resp.text,
            )
        if not resp.content:
            return {}
        try:
            data = resp.json()
        except ValueError:
            raise WalletAPIError(
                f"{method} {url} devolvió JSON inválido: {resp.text[:300]}",
                status=resp.status_code,
            )
        return data if isinstance(data, dict) else {"items": data}

    # ── Cuentas ───────────────────────────────────────────────────────────────

    def get_accounts(self) -> List[Dict[str, Any]]:
        data = self._request("GET", "/accounts", params={"limit": MAX_PAGE_SIZE})
        return data.get("accounts", [])

    def find_account(self, nombre: str) -> Optional[Dict[str, Any]]:
        """Búsqueda por nombre, case-insensitive, coincidencia parcial."""
        needle = nombre.strip().lower()
        if not needle:
            return None
        cuentas = self.get_accounts()
        # Prioriza coincidencia exacta para evitar ambigüedad
        for c in cuentas:
            if (c.get("name") or "").strip().lower() == needle:
                return c
        for c in cuentas:
            nombre_cuenta = (c.get("name") or "").strip().lower()
            if needle in nombre_cuenta or nombre_cuenta in needle:
                return c
        return None

    def patch_accounts(self, patches: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        PATCH /accounts (colección).

        Uso: patch_accounts([{"id": "...", "initialBalance": 1234.56}])
        NO existe PATCH /accounts/{id}.
        """
        if not patches:
            return {"summary": {"succeeded": 0}, "results": []}
        return self._request("PATCH", "/accounts", json=patches)

    # ── Categorías ────────────────────────────────────────────────────────────

    def get_categories(self, force: bool = False) -> List[Dict[str, Any]]:
        if self._categories_by_system_id is not None and not force:
            return list(self._categories_by_system_id.values())
        data = self._request(
            "GET", "/categories", params={"limit": MAX_PAGE_SIZE}
        )
        categorias = data.get("categories", [])
        self._categories_by_system_id = {
            c["systemId"]: c for c in categorias if c.get("systemId")
        }
        if self._categories_by_system_id:
            self._log(
                f"   [CACHE] {len(self._categories_by_system_id)} categorías de sistema indexadas por systemId"
            )
        return categorias

    def resolve_category_id(self, system_id: str) -> str:
        """
        Resuelve categoryId a partir del systemId, consultando /categories en runtime.

        Aborta si no hay match exacto: escribir con una categoría aproximada
        corrompe los reportes (fue el bug P0 de Food & Drinks en intereses).
        """
        self.get_categories()
        assert self._categories_by_system_id is not None
        categoria = self._categories_by_system_id.get(system_id)
        if not categoria:
            disponibles = ", ".join(sorted(self._categories_by_system_id))
            raise CategoryNotFoundError(
                f"systemId '{system_id}' no existe en esta cuenta. "
                f"Disponibles: {disponibles}"
            )
        return categoria["id"]

    def find_category_id_by_name(self, nombre: str) -> Optional[str]:
        """
        Busca categoryId por nombre exacto (case-insensitive).
        Devuelve None si no hay coincidencia exacta. No adivina.
        """
        needle = (nombre or "").strip().lower()
        if not needle:
            return None
        for cat in self.get_categories():
            if (cat.get("name") or "").strip().lower() == needle:
                return cat["id"]
        return None

    # ── Registros ─────────────────────────────────────────────────────────────

    def get_records(
        self,
        account_id: str,
        since_date: str,
        until_date: Optional[str] = None,
        max_records: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        GET /records paginado con nextOffset.

        since_date es OBLIGATORIO: sin recordDate la API devuelve un subset
        (o 0 registros si solo se filtra por accountId). Formato ISO 8601.
        """
        if not since_date:
            raise ValueError(
                "since_date es obligatorio: GET /records sin recordDate devuelve un subset"
            )

        resultados: List[Dict[str, Any]] = []
        offset = 0

        while True:
            params: Dict[str, Any] = {
                "accountId": account_id,
                "limit": MAX_PAGE_SIZE,
                "offset": offset,
                "recordDate": f"gte.{since_date}",
            }
            if until_date:
                params["recordDate"] = f"gte.{since_date},{until_date}"

            data = self._request("GET", "/records", params=params)
            pagina = data.get("records", [])
            resultados.extend(pagina)

            if max_records is not None and len(resultados) >= max_records:
                return resultados[:max_records]

            next_offset = data.get("nextOffset")
            # Sin nextOffset o página vacía => no hay más
            if next_offset is None or not pagina or next_offset == offset:
                break
            offset = next_offset

        return resultados

    @staticmethod
    def sanitize_record_for_write(record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deja solo campos que la API acepta al escribir.

        La API rechaza con 400 los campos no escribibles (recordType,
        recordState, source, paymentType); no los ignora en silencio.
        """
        limpio: Dict[str, Any] = {}
        for campo in WRITABLE_RECORD_FIELDS:
            if campo in record and record[campo] is not None:
                limpio[campo] = record[campo]

        amount = limpio.get("amount")
        if isinstance(amount, dict):
            limpio["amount"] = {
                k: v for k, v in amount.items() if k in ("value", "currencyCode") and v is not None
            }

        invalidos = FORBIDDEN_RECORD_FIELDS & set(limpio)
        if invalidos:
            raise WalletAPIError(
                f"Campos no escribibles presentes: {sorted(invalidos)}"
            )
        return limpio

    def create_records(self, records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """
        POST /records. El body es un ARRAY RAÍZ, no {"records": [...]}.
        Se envía en lotes de BATCH_CREATE_LIMIT.
        """
        limpios = [self.sanitize_record_for_write(r) for r in records]
        if not limpios:
            return {"summary": {"total": 0, "succeeded": 0}, "results": []}

        acumulado: Dict[str, Any] = {
            "summary": {"total": 0, "succeeded": 0, "clientErrors": 0, "serverErrors": 0},
            "results": [],
        }
        for i in range(0, len(limpios), BATCH_CREATE_LIMIT):
            lote = limpios[i : i + BATCH_CREATE_LIMIT]
            resp = self._request("POST", "/records", json=lote)
            self._merge_batch(acumulado, resp)
        return acumulado

    def patch_records(self, patches: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """PATCH /records. Body: array raíz. Lotes de BATCH_PATCH_LIMIT."""
        limpios = [p for p in patches if p and p.get("id")]
        if not limpios:
            return {"summary": {"total": 0, "succeeded": 0}, "results": []}

        acumulado: Dict[str, Any] = {
            "summary": {"total": 0, "succeeded": 0, "clientErrors": 0, "serverErrors": 0},
            "results": [],
        }
        for i in range(0, len(limpios), BATCH_PATCH_LIMIT):
            lote = limpios[i : i + BATCH_PATCH_LIMIT]
            resp = self._request("PATCH", "/records", json=lote)
            self._merge_batch(acumulado, resp)
        return acumulado

    def delete_records(self, ids: Iterable[str]) -> Dict[str, Any]:
        """DELETE /records. Body: {"ids": [...]} (DeleteRequest)."""
        lista = [i for i in ids if i]
        if not lista:
            return {"summary": {"total": 0, "succeeded": 0}, "results": []}
        return self._request("DELETE", "/records", json={"ids": lista})

    @staticmethod
    def _merge_batch(acumulado: Dict[str, Any], resp: Dict[str, Any]) -> None:
        summary = resp.get("summary") or {}
        for campo in ("total", "succeeded", "clientErrors", "serverErrors"):
            if campo in summary:
                acumulado["summary"][campo] = (
                    acumulado["summary"].get(campo, 0) + summary.get(campo, 0)
                )
        acumulado["results"].extend(resp.get("results") or [])

    # ── Transferencias ────────────────────────────────────────────────────────

    @staticmethod
    def get_transfer_info(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Devuelve la información de transferencia del registro, o None.

        Shape real que devuelve la API:
            transfer: {type: "paired", transferId: "<uuid>", mirrorRecord: {...}}
        También se tolera el embed legado transferRecord {id, accountId, ...}.
        """
        transfer = record.get("transfer") or {}
        if isinstance(transfer, dict) and transfer.get("type") == "paired":
            return transfer

        legado = record.get("transferRecord") or {}
        if isinstance(legado, dict) and legado.get("id"):
            return {
                "type": "paired",
                "transferId": legado.get("id"),
                "mirrorRecord": legado,
            }
        return None

    @classmethod
    def is_paired_transfer(cls, record: Dict[str, Any]) -> bool:
        return cls.get_transfer_info(record) is not None
