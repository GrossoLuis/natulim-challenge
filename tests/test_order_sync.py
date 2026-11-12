import copy

import pytest

from app.config import parse_iso_datetime
from app.order_sync import repository
from app.order_sync.db import connect, init_db

SYNC_START = parse_iso_datetime("2026-11-01T00:00:00Z")

PAYLOAD = {
    "id": 1001,
    "admin_graphql_api_id": "gid://shopify/Order/1001",
    "name": "#1001",
    "email": "cliente@example.com",
    "created_at": "2026-11-12T10:00:00+01:00",
    "updated_at": "2026-11-12T10:00:00+01:00",
    "cancelled_at": None,
    "financial_status": "paid",
    "fulfillment_status": None,
    "currency": "EUR",
    "current_subtotal_price": "20.00",
    "current_total_price": "24.20",
    "tags": "",
    "shipping_address": {"country_code": "ES", "province_code": "M", "zip": "28001"},
    "line_items": [
        {"id": 1, "product_id": 10, "variant_id": 100, "sku": "A", "title": "Producto A",
         "variant_title": None, "quantity": 1, "current_quantity": 1, "price": "10.00"},
        {"id": 2, "product_id": 20, "variant_id": 200, "sku": "B", "title": "Producto B",
         "variant_title": None, "quantity": 2, "current_quantity": 2, "price": "5.00"},
    ],
}


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "orders.db"
    init_db(path)
    c = connect(path)
    yield c
    c.close()


def _upsert(conn, payload, webhook_id):
    return repository.upsert_order(conn, repository.from_webhook(payload), SYNC_START, webhook_id, "orders/updated")


def _lines(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT sku, quantity, current_quantity FROM order_lines WHERE order_id = 1001 ORDER BY id")]


def test_crear_inserta_pedido_y_lineas(conn):
    assert _upsert(conn, PAYLOAD, "wh-1") == repository.INSERTED
    order = conn.execute("SELECT * FROM orders WHERE id = 1001").fetchone()
    assert order["name"] == "#1001"
    assert order["total_price"] == "24.20"
    assert order["fulfillment_status"] == "unfulfilled"
    assert order["shipping_zip"] == "28001"
    assert _lines(conn) == [("A", 1, 1), ("B", 2, 2)]


def test_update_mas_nuevo_actualiza_y_reemplaza_lineas(conn):
    _upsert(conn, PAYLOAD, "wh-1")
    edited = copy.deepcopy(PAYLOAD)
    edited["updated_at"] = "2026-11-12T11:00:00+01:00"
    edited["current_total_price"] = "14.20"
    edited["line_items"][1]["current_quantity"] = 0  # línea quitada con Edit
    edited["line_items"].append({"id": 3, "product_id": 30, "variant_id": 300, "sku": "C", "title": "C",
                                 "variant_title": None, "quantity": 1, "current_quantity": 1, "price": "4.00"})
    assert _upsert(conn, edited, "wh-2") == repository.UPDATED
    assert conn.execute("SELECT total_price FROM orders WHERE id = 1001").fetchone()[0] == "14.20"
    assert _lines(conn) == [("A", 1, 1), ("B", 2, 0), ("C", 1, 1)]


def test_update_mas_viejo_se_ignora(conn):
    newer = copy.deepcopy(PAYLOAD)
    newer["updated_at"] = "2026-11-12T12:00:00+01:00"
    newer["tags"] = "nuevo"
    _upsert(conn, newer, "wh-1")
    # 10:30Z es anterior a 12:00+01:00 (= 11:00Z).
    older = copy.deepcopy(PAYLOAD)
    older["updated_at"] = "2026-11-12T10:30:00Z"
    assert _upsert(conn, older, "wh-2") == repository.SKIPPED_OLD
    assert conn.execute("SELECT tags FROM orders WHERE id = 1001").fetchone()[0] == "nuevo"


def test_comparacion_con_zonas_horarias_distintas(conn):
    _upsert(conn, PAYLOAD, "wh-1")  # 10:00+01:00 = 09:00Z
    later = copy.deepcopy(PAYLOAD)
    later["updated_at"] = "2026-11-12T09:30:00Z"  # como string es "menor", como datetime es posterior
    assert _upsert(conn, later, "wh-2") == repository.UPDATED


def test_webhook_repetido_no_reprocesa(conn):
    _upsert(conn, PAYLOAD, "wh-1")
    edited = copy.deepcopy(PAYLOAD)
    edited["updated_at"] = "2026-11-12T11:00:00+01:00"
    edited["tags"] = "cambio"
    assert _upsert(conn, edited, "wh-1") == repository.SKIPPED_DUPLICATE
    assert conn.execute("SELECT tags FROM orders WHERE id = 1001").fetchone()[0] == ""


def test_pedido_anterior_al_inicio_se_ignora(conn):
    old = copy.deepcopy(PAYLOAD)
    old["created_at"] = "2026-10-01T00:00:00Z"
    assert _upsert(conn, old, "wh-1") == repository.SKIPPED_BEFORE_START
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM processed_webhooks").fetchone()[0] == 1


def test_delete_marca_eliminado(conn):
    _upsert(conn, PAYLOAD, "wh-1")
    assert repository.mark_deleted(conn, 1001, "wh-2") == repository.DELETED
    row = conn.execute("SELECT deleted FROM orders WHERE id = 1001").fetchone()
    assert row["deleted"] == 1
    assert len(_lines(conn)) == 2  # soft delete: se conserva la historia


def test_delete_de_pedido_inexistente(conn):
    assert repository.mark_deleted(conn, 999, "wh-1") == repository.NOT_FOUND


def test_from_graphql_equivale_a_from_webhook():
    node = {
        "id": "gid://shopify/Order/1001", "name": "#1001", "email": "cliente@example.com",
        "createdAt": "2026-11-12T09:00:00Z", "updatedAt": "2026-11-12T09:00:00Z", "cancelledAt": None,
        "displayFinancialStatus": "PAID", "displayFulfillmentStatus": "UNFULFILLED", "currencyCode": "EUR",
        "tags": ["a", "b"],
        "currentSubtotalPriceSet": {"shopMoney": {"amount": "20.0"}},
        "currentTotalPriceSet": {"shopMoney": {"amount": "24.2"}},
        "shippingAddress": {"countryCodeV2": "ES", "provinceCode": "M", "zip": "28001"},
        "lineItems": {"nodes": [{
            "id": "gid://shopify/LineItem/1", "sku": "A", "title": "Producto A", "variantTitle": None,
            "quantity": 1, "currentQuantity": 1, "originalUnitPriceSet": {"shopMoney": {"amount": "10.0"}},
            "product": {"id": "gid://shopify/Product/10"}, "variant": {"id": "gid://shopify/ProductVariant/100"},
        }]},
    }
    order = repository.from_graphql(node)
    assert order["id"] == 1001
    assert order["financial_status"] == "paid"
    assert order["fulfillment_status"] == "unfulfilled"
    assert order["tags"] == "a, b"
    assert order["lines"][0] == {"id": 1, "product_id": 10, "variant_id": 100, "sku": "A", "title": "Producto A",
                                 "variant_title": None, "quantity": 1, "current_quantity": 1, "price": "10.0"}
    assert set(order) == set(repository.from_webhook(PAYLOAD))
