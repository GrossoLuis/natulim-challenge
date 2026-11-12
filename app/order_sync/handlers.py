"""Handlers de webhooks del requerimiento 3: sincronización de pedidos a SQLite."""

from __future__ import annotations

import logging

from app.config import ConfigError, get_settings
from app.order_sync import repository
from app.order_sync.db import connect, init_db

logger = logging.getLogger(__name__)


def setup() -> None:
    settings = get_settings()
    if not settings.sync_start_at:
        raise ConfigError("Falta SYNC_START_AT: los pedidos anteriores a la puesta en producción no se sincronizan.")
    init_db(settings.database_path)


def handle_upsert(topic: str, webhook_id: str, payload: dict) -> str:
    """orders/create, orders/updated y orders/cancelled."""
    settings = get_settings()
    conn = connect(settings.database_path)
    try:
        return repository.upsert_order(
            conn, repository.from_webhook(payload), settings.sync_start_at, webhook_id, topic
        )
    finally:
        conn.close()


def handle_delete(topic: str, webhook_id: str, payload: dict) -> str:
    """orders/delete: el payload solo trae el id."""
    conn = connect(get_settings().database_path)
    try:
        return repository.mark_deleted(conn, int(payload["id"]), webhook_id, topic)
    finally:
        conn.close()
