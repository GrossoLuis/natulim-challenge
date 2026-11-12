"""Conexión SQLite y creación del esquema del requerimiento 3."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
  id                 INTEGER PRIMARY KEY,   -- order id de Shopify (numérico)
  admin_graphql_id   TEXT NOT NULL,
  name               TEXT NOT NULL,         -- "#1001"
  email              TEXT,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  cancelled_at       TEXT,
  financial_status   TEXT,
  fulfillment_status TEXT,
  currency           TEXT,
  subtotal_price     TEXT,                  -- precios como TEXT para no perder precisión decimal
  total_price        TEXT,
  shipping_country   TEXT,
  shipping_province  TEXT,
  shipping_zip       TEXT,
  tags               TEXT,
  deleted            INTEGER NOT NULL DEFAULT 0,
  raw_json           TEXT NOT NULL,
  synced_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_lines (
  id               INTEGER PRIMARY KEY,     -- line item id
  order_id         INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id       INTEGER,
  variant_id       INTEGER,
  sku              TEXT,
  title            TEXT,
  variant_title    TEXT,
  quantity         INTEGER NOT NULL,        -- cantidad original de la línea
  current_quantity INTEGER NOT NULL,        -- cantidad vigente tras ediciones (0 = línea quitada)
  price            TEXT
);

CREATE INDEX IF NOT EXISTS idx_order_lines_order_id ON order_lines(order_id);

CREATE TABLE IF NOT EXISTS processed_webhooks (
  webhook_id  TEXT PRIMARY KEY,
  topic       TEXT NOT NULL,
  received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
  key   TEXT PRIMARY KEY,                 -- ej: last_reconcile_started_at
  value TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)  # transacciones explícitas
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(path: Path) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
    conn.close()
