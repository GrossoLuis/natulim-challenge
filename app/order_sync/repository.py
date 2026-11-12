"""Normalización de pedidos (webhook y GraphQL) y persistencia en SQLite."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.config import parse_iso_datetime

INSERTED = "insertado"
UPDATED = "actualizado"
SKIPPED_OLD = "omitido: updated_at anterior al guardado"
SKIPPED_BEFORE_START = "omitido: pedido anterior a la puesta en producción"
SKIPPED_DUPLICATE = "omitido: webhook ya procesado"
DELETED = "marcado eliminado"
NOT_FOUND = "omitido: pedido no sincronizado"

_FULFILLMENT_REST = {None: "unfulfilled", "partial": "partially_fulfilled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _gid_to_int(value) -> int | None:
    if value is None:
        return None
    return int(str(value).rsplit("/", 1)[-1])


def _money(price_set: dict | None) -> str | None:
    return ((price_set or {}).get("shopMoney") or {}).get("amount")


def from_webhook(payload: dict) -> dict:
    """Payload REST (snake_case) de orders/create, orders/updated u orders/cancelled."""
    addr = payload.get("shipping_address") or {}
    fulfillment = payload.get("fulfillment_status")
    lines = []
    for li in payload.get("line_items") or []:
        current = li.get("current_quantity")
        lines.append({
            "id": li["id"],
            "product_id": li.get("product_id"),
            "variant_id": li.get("variant_id"),
            "sku": li.get("sku"),
            "title": li.get("title"),
            "variant_title": li.get("variant_title"),
            "quantity": li.get("quantity") or 0,
            "current_quantity": (li.get("quantity") or 0) if current is None else current,
            "price": li.get("price"),
        })
    return {
        "id": payload["id"],
        "admin_graphql_id": payload.get("admin_graphql_api_id") or f"gid://shopify/Order/{payload['id']}",
        "name": payload.get("name"),
        "email": payload.get("email"),
        "created_at": payload["created_at"],
        "updated_at": payload["updated_at"],
        "cancelled_at": payload.get("cancelled_at"),
        "financial_status": payload.get("financial_status"),
        "fulfillment_status": _FULFILLMENT_REST.get(fulfillment, fulfillment),
        "currency": payload.get("currency"),
        "subtotal_price": payload.get("current_subtotal_price") or payload.get("subtotal_price"),
        "total_price": payload.get("current_total_price") or payload.get("total_price"),
        "shipping_country": addr.get("country_code"),
        "shipping_province": addr.get("province_code"),
        "shipping_zip": addr.get("zip"),
        "tags": payload.get("tags") or "",
        "raw_json": json.dumps(payload, ensure_ascii=False),
        "lines": lines,
    }


GRAPHQL_ORDER_FIELDS = """
  id name email createdAt updatedAt cancelledAt
  displayFinancialStatus displayFulfillmentStatus currencyCode tags
  currentSubtotalPriceSet { shopMoney { amount } }
  currentTotalPriceSet { shopMoney { amount } }
  shippingAddress { countryCodeV2 provinceCode zip }
  lineItems(first: 250) {
    nodes {
      id sku title variantTitle quantity currentQuantity
      originalUnitPriceSet { shopMoney { amount } }
      product { id }
      variant { id }
    }
  }
"""


def from_graphql(node: dict) -> dict:
    """Nodo Order de la GraphQL Admin API (ver GRAPHQL_ORDER_FIELDS)."""
    addr = node.get("shippingAddress") or {}
    lines = [{
        "id": _gid_to_int(li["id"]),
        "product_id": _gid_to_int((li.get("product") or {}).get("id")),
        "variant_id": _gid_to_int((li.get("variant") or {}).get("id")),
        "sku": li.get("sku"),
        "title": li.get("title"),
        "variant_title": li.get("variantTitle"),
        "quantity": li.get("quantity") or 0,
        "current_quantity": li.get("currentQuantity") or 0,
        "price": _money(li.get("originalUnitPriceSet")),
    } for li in node["lineItems"]["nodes"]]
    return {
        "id": _gid_to_int(node["id"]),
        "admin_graphql_id": node["id"],
        "name": node.get("name"),
        "email": node.get("email"),
        "created_at": node["createdAt"],
        "updated_at": node["updatedAt"],
        "cancelled_at": node.get("cancelledAt"),
        "financial_status": (node.get("displayFinancialStatus") or "").lower() or None,
        "fulfillment_status": (node.get("displayFulfillmentStatus") or "").lower() or None,
        "currency": node.get("currencyCode"),
        "subtotal_price": _money(node.get("currentSubtotalPriceSet")),
        "total_price": _money(node.get("currentTotalPriceSet")),
        "shipping_country": addr.get("countryCodeV2"),
        "shipping_province": addr.get("provinceCode"),
        "shipping_zip": addr.get("zip"),
        "tags": ", ".join(node.get("tags") or []),
        "raw_json": json.dumps(node, ensure_ascii=False),
        "lines": lines,
    }


def _mark_processed(conn: sqlite3.Connection, webhook_id: str | None, topic: str) -> bool:
    """Registra el webhook. Devuelve False si ya estaba procesado."""
    if not webhook_id:
        return True
    cur = conn.execute(
        "INSERT OR IGNORE INTO processed_webhooks (webhook_id, topic, received_at) VALUES (?, ?, ?)",
        (webhook_id, topic, _now()),
    )
    return cur.rowcount == 1


ORDER_COLUMNS = [
    "id", "admin_graphql_id", "name", "email", "created_at", "updated_at", "cancelled_at",
    "financial_status", "fulfillment_status", "currency", "subtotal_price", "total_price",
    "shipping_country", "shipping_province", "shipping_zip", "tags", "raw_json",
]
LINE_COLUMNS = [
    "id", "order_id", "product_id", "variant_id", "sku", "title", "variant_title",
    "quantity", "current_quantity", "price",
]


def upsert_order(
    conn: sqlite3.Connection,
    order: dict,
    sync_start_at: datetime,
    webhook_id: str | None = None,
    topic: str = "reconcile",
) -> str:
    """Inserta o actualiza el pedido y reemplaza sus líneas, en una sola transacción."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not _mark_processed(conn, webhook_id, topic):
            conn.execute("ROLLBACK")
            return SKIPPED_DUPLICATE

        if parse_iso_datetime(order["created_at"]) < sync_start_at:
            conn.execute("COMMIT")  # se registra el webhook como procesado igual
            return SKIPPED_BEFORE_START

        row = conn.execute("SELECT updated_at FROM orders WHERE id = ?", (order["id"],)).fetchone()
        if row and parse_iso_datetime(order["updated_at"]) < parse_iso_datetime(row["updated_at"]):
            conn.execute("COMMIT")
            return SKIPPED_OLD

        values = [order[c] for c in ORDER_COLUMNS]
        updates = ", ".join(f"{c} = excluded.{c}" for c in ORDER_COLUMNS if c != "id")
        conn.execute(
            f"INSERT INTO orders ({', '.join(ORDER_COLUMNS)}, deleted, synced_at) "
            f"VALUES ({', '.join('?' * len(ORDER_COLUMNS))}, 0, ?) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}, deleted = 0, synced_at = excluded.synced_at",
            [*values, _now()],
        )
        conn.execute("DELETE FROM order_lines WHERE order_id = ?", (order["id"],))
        conn.executemany(
            f"INSERT INTO order_lines ({', '.join(LINE_COLUMNS)}) VALUES ({', '.join('?' * len(LINE_COLUMNS))})",
            [[{**line, "order_id": order["id"]}[c] for c in LINE_COLUMNS] for line in order["lines"]],
        )
        conn.execute("COMMIT")
        return UPDATED if row else INSERTED
    except Exception:
        conn.execute("ROLLBACK")
        raise


def mark_deleted(conn: sqlite3.Connection, order_id: int, webhook_id: str | None = None, topic: str = "orders/delete") -> str:
    """Soft delete: conserva el pedido y sus líneas con deleted = 1."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not _mark_processed(conn, webhook_id, topic):
            conn.execute("ROLLBACK")
            return SKIPPED_DUPLICATE
        cur = conn.execute("UPDATE orders SET deleted = 1, synced_at = ? WHERE id = ?", (_now(), order_id))
        conn.execute("COMMIT")
        return DELETED if cur.rowcount else NOT_FOUND
    except Exception:
        conn.execute("ROLLBACK")
        raise


def get_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
