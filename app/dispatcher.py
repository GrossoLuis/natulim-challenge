"""Enruta cada webhook a los features que lo procesan, según X-Shopify-Topic.

Cada feature corre de forma independiente: si uno falla, los demás igual se ejecutan.
Si alguno falló, se lanza DispatchError para responder 500 y que Shopify reintente.
Los handlers deben ser idempotentes, porque un reintento vuelve a ejecutarlos todos.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

Handler = Callable[[str, str, dict], str]
"""handler(topic, webhook_id, payload) -> descripción corta del resultado."""

# topic -> lista de (nombre del feature, handler). Se completa en register_handlers().
HANDLERS: dict[str, list[tuple[str, Handler]]] = {}


class DispatchError(RuntimeError):
    def __init__(self, failures: dict[str, Exception]):
        super().__init__("Fallaron features: " + ", ".join(failures))
        self.failures = failures


def register(topic: str, feature: str, handler: Handler) -> None:
    HANDLERS.setdefault(topic, []).append((feature, handler))


def register_handlers() -> None:
    """Registra los handlers de los requerimientos 3 y 4."""
    from app.canarias_tag import handlers as canarias_tag
    from app.order_sync import handlers as order_sync

    HANDLERS.clear()
    order_sync.setup()
    for topic in ("orders/create", "orders/updated", "orders/cancelled"):
        register(topic, "order_sync", order_sync.handle_upsert)
    register("orders/delete", "order_sync", order_sync.handle_delete)
    register("orders/create", "canarias_tag", canarias_tag.handle_create)
    register("orders/updated", "canarias_tag", canarias_tag.handle_updated)


def dispatch(topic: str, webhook_id: str, payload: dict) -> dict[str, str]:
    handlers = HANDLERS.get(topic, [])
    if not handlers:
        logger.info("topic=%s webhook_id=%s sin handlers, se ignora", topic, webhook_id)
        return {}

    results: dict[str, str] = {}
    failures: dict[str, Exception] = {}
    for feature, handler in handlers:
        try:
            results[feature] = handler(topic, webhook_id, payload)
            logger.info("feature=%s topic=%s webhook_id=%s resultado=%s",
                        feature, topic, webhook_id, results[feature])
        except Exception as exc:  # noqa: BLE001 - se aísla cada feature
            failures[feature] = exc
            logger.exception("feature=%s topic=%s webhook_id=%s falló", feature, topic, webhook_id)

    if failures:
        raise DispatchError(failures)
    return results
