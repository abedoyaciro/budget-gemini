"""
Verifica la resolución de categoryId por systemId en runtime.

Requiere red + WALLET_API_TOKEN. Se omite si no hay credenciales.

Estas comprobaciones existen porque el bug P0 original escribía intereses
en "Food & Drinks" y transferencias en "Groceries/Mercado" por IDs literales
cruzados.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from wallet_client import (  # noqa: E402
    SYSTEM_ID_INTEREST_DIVIDENDS,
    SYSTEM_ID_TRANSFER,
    CategoryNotFoundError,
    WalletClient,
)


def _client_or_skip() -> WalletClient:
    if not os.getenv("WALLET_API_TOKEN"):
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
        )
        if os.path.exists(env_path):
            from dotenv import load_dotenv

            load_dotenv(env_path)
    if not os.getenv("WALLET_API_TOKEN"):
        pytest.skip("WALLET_API_TOKEN no disponible")
    return WalletClient(verbose=False)


def test_system_id_interest_es_income_no_financial_expenses():
    # Contrato: la categoría de intereses vive bajo 'income'.
    assert SYSTEM_ID_INTEREST_DIVIDENDS == "income__interest_dividends"
    assert not SYSTEM_ID_INTEREST_DIVIDENDS.startswith("financial_expenses")


def test_resolver_intereses_devuelve_categoria_income():
    client = _client_or_skip()
    cat_id = client.resolve_category_id(SYSTEM_ID_INTEREST_DIVIDENDS)

    categorias = {c["id"]: c for c in client.get_categories()}
    categoria = categorias[cat_id]

    assert categoria["systemId"] == SYSTEM_ID_INTEREST_DIVIDENDS
    # No debe ser Food & Drinks ni Groceries
    assert "food" not in categoria["name"].lower()
    assert "grocery" not in categoria["name"].lower()
    assert "groceries" not in categoria["name"].lower()


def test_resolver_transferencia_no_es_groceries():
    client = _client_or_skip()
    cat_id = client.resolve_category_id(SYSTEM_ID_TRANSFER)

    categorias = {c["id"]: c for c in client.get_categories()}
    categoria = categorias[cat_id]

    assert categoria["systemId"] == SYSTEM_ID_TRANSFER
    assert "grocery" not in categoria["name"].lower()
    assert "mercado" not in categoria["name"].lower()


def test_system_id_inexistente_aborta():
    client = _client_or_skip()
    with pytest.raises(CategoryNotFoundError):
        client.resolve_category_id("income__categoria_que_no_existe")


def test_busqueda_por_nombre_exige_coincidencia_exacta():
    client = _client_or_skip()
    # Prefijo parcial no debe resolver
    assert client.find_category_id_by_name("Intere") is None
