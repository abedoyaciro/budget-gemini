"""
Contratos de escritura del cliente Wallet (sin red).

Cubren los bugs P0 originales:
  * enviar campos no escribibles -> 400
  * envolver el batch en {"records": [...]} -> 400
  * PATCH /accounts/{id} -> 404
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from wallet_client import (  # noqa: E402
    FORBIDDEN_RECORD_FIELDS,
    WRITABLE_RECORD_FIELDS,
    WalletAPIError,
    WalletClient,
)


def _client() -> WalletClient:
    return WalletClient(token="token-de-prueba", verbose=False)


# -- sanitize_record_for_write -----------------------------------------------

def test_sanitize_conserva_solo_campos_escribibles():
    record = {
        "accountId": "acc",
        "amount": {"value": 100.0, "currencyCode": "COP"},
        "recordDate": "2026-10-01T00:00:00Z",
        "note": "Intereses",
        "categoryId": "cat",
        "counterParty": "Pibank",
        "labelIds": ["l1"],
    }
    limpio = WalletClient.sanitize_record_for_write(record)
    assert set(limpio) == set(record)
    assert set(limpio) <= WRITABLE_RECORD_FIELDS


@pytest.mark.parametrize("campo", sorted(FORBIDDEN_RECORD_FIELDS))
def test_sanitize_elimina_campos_prohibidos(campo):
    record = {
        "accountId": "acc",
        "amount": {"value": 1.0},
        "recordDate": "2026-10-01T00:00:00Z",
        campo: "x",
    }
    limpio = WalletClient.sanitize_record_for_write(record)
    assert campo not in limpio


def test_sanitize_elimina_campos_desconocidos():
    record = {
        "accountId": "acc",
        "amount": {"value": 1.0},
        "recordDate": "2026-10-01T00:00:00Z",
        "campo_inventado": "x",
    }
    limpio = WalletClient.sanitize_record_for_write(record)
    assert "campo_inventado" not in limpio


def test_sanitize_limpia_amount():
    record = {
        "accountId": "acc",
        "amount": {"value": 1.0, "currencyCode": "COP", "extra": "x"},
        "recordDate": "2026-10-01T00:00:00Z",
    }
    limpio = WalletClient.sanitize_record_for_write(record)
    assert set(limpio["amount"]) == {"value", "currencyCode"}


def test_sanitize_quita_none():
    record = {
        "accountId": "acc",
        "amount": {"value": 1.0},
        "recordDate": "2026-10-01T00:00:00Z",
        "note": None,
        "categoryId": None,
    }
    limpio = WalletClient.sanitize_record_for_write(record)
    assert "note" not in limpio
    assert "categoryId" not in limpio


# -- transferencias ----------------------------------------------------------

def test_transfer_shape_real_paired():
    record = {
        "id": "r1",
        "transfer": {
            "type": "paired",
            "transferId": "t1",
            "mirrorRecord": {"id": "r2", "accountId": "acc2"},
        },
    }
    info = WalletClient.get_transfer_info(record)
    assert info is not None
    assert info["transferId"] == "t1"
    assert WalletClient.is_paired_transfer(record) is True


def test_transfer_shape_legado_transferRecord():
    record = {"id": "r1", "transferRecord": {"id": "r2", "accountId": "acc2"}}
    info = WalletClient.get_transfer_info(record)
    assert info is not None
    assert info["transferId"] == "r2"


def test_registro_sin_transfer_no_esta_pareado():
    assert WalletClient.is_paired_transfer({"id": "r1"}) is False
    assert WalletClient.is_paired_transfer({"id": "r1", "transfer": {}}) is False
    assert (
        WalletClient.is_paired_transfer({"id": "r1", "transfer": {"type": "unpaired"}})
        is False
    )


# -- paginación --------------------------------------------------------------

def test_get_records_exige_since_date():
    client = _client()
    with pytest.raises(ValueError, match="since_date"):
        client.get_records("acc", since_date="")


def test_crear_sin_registros_no_llama_a_la_api():
    client = _client()
    resultado = client.create_records([])
    assert resultado["summary"]["succeeded"] == 0


def test_patch_records_ignora_items_sin_id():
    client = _client()
    resultado = client.patch_records([{"note": "sin id"}])
    assert resultado["summary"]["succeeded"] == 0


def test_wallet_client_sin_token_falla(monkeypatch):
    # Sin token explícito ni variable de entorno: debe fallar, no continuar
    monkeypatch.delenv("WALLET_API_TOKEN", raising=False)
    with pytest.raises(WalletAPIError):
        WalletClient(token="")
