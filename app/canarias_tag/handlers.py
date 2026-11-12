"""Handlers de webhooks del requerimiento 4: tag cuando la dirección de envío cambia a Canarias.

orders/updated no indica qué cambió, así que hace falta conocer la dirección anterior.
Sin base de datos, ese estado se guarda en el propio pedido, en un metafield con
"<hash de la dirección>|<updated_at del evento>".

- orders/create: guarda la línea base (no taggea: nacer en Canarias no es un cambio).
- orders/updated: si el hash cambió y la nueva dirección es de Canarias, agrega el tag.
  Si el hash no cambió, no escribe nada. Eso corta el bucle que generan nuestras propias
  escrituras (tagsAdd y metafieldsSet disparan otro orders/updated con la misma dirección).
"""

from __future__ import annotations

import logging

from app.canarias_tag.address import es_canarias, hash_direccion
from app.config import get_settings, parse_iso_datetime
from app.shopify_client import graphql

logger = logging.getLogger(__name__)

ORDER_STATE_QUERY = """
query($id: ID!, $namespace: String!, $key: String!) {
  order(id: $id) {
    id
    tags
    metafield(namespace: $namespace, key: $key) { value }
  }
}
"""

TAGS_ADD = """
mutation($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) { node { id } userErrors { field message } }
}
"""

METAFIELDS_SET = """
mutation($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id }
    userErrors { field message code }
  }
}
"""

BASELINE_SAVED = "línea base guardada"
BASELINE_INITIALIZED = "línea base inicializada (pedido sin estado previo, no se taggea)"
STALE_EVENT = "evento anterior al estado guardado, se ignora"
NO_CHANGE = "sin cambios de dirección"
TAGGED = "dirección cambiada a Canarias: tag agregado"
ALREADY_TAGGED = "dirección cambiada a Canarias: el tag ya estaba"
CHANGED_NOT_CANARIAS = "dirección cambiada, no es Canarias"


def _order_gid(payload: dict) -> str:
    return payload.get("admin_graphql_api_id") or f"gid://shopify/Order/{payload['id']}"


def parse_state(value: str | None) -> tuple[str, str | None] | None:
    """"<hash>|<updated_at>" → (hash, updated_at). Un valor ajeno o vacío se trata como ausente."""
    if not value:
        return None
    digest, _, updated_at = value.partition("|")
    if len(digest) != 64 and digest != "none":
        return None
    return digest, updated_at or None


def _save_state(order_gid: str, digest: str, updated_at: str) -> None:
    settings = get_settings()
    graphql(METAFIELDS_SET, {"metafields": [{
        "ownerId": order_gid,
        "namespace": settings.address_metafield_namespace,
        "key": settings.address_metafield_key,
        "type": "single_line_text_field",
        "value": f"{digest}|{updated_at}",
    }]})


def handle_create(topic: str, webhook_id: str, payload: dict) -> str:
    _save_state(_order_gid(payload), hash_direccion(payload.get("shipping_address")), payload["updated_at"])
    return BASELINE_SAVED


def handle_updated(topic: str, webhook_id: str, payload: dict) -> str:
    settings = get_settings()
    order_gid = _order_gid(payload)
    address = payload.get("shipping_address")
    new_hash = hash_direccion(address)
    updated_at = payload["updated_at"]

    order = graphql(ORDER_STATE_QUERY, {
        "id": order_gid,
        "namespace": settings.address_metafield_namespace,
        "key": settings.address_metafield_key,
    })["order"]
    state = parse_state((order.get("metafield") or {}).get("value"))

    if state is None:
        _save_state(order_gid, new_hash, updated_at)
        return BASELINE_INITIALIZED

    stored_hash, stored_updated_at = state
    if stored_updated_at and parse_iso_datetime(updated_at) < parse_iso_datetime(stored_updated_at):
        return STALE_EVENT

    if new_hash == stored_hash:
        return NO_CHANGE  # ninguna escritura: corta el bucle

    result = CHANGED_NOT_CANARIAS
    if es_canarias(address):
        if settings.canarias_tag in order.get("tags", []):
            result = ALREADY_TAGGED
        else:
            graphql(TAGS_ADD, {"id": order_gid, "tags": [settings.canarias_tag]})
            result = TAGGED
    _save_state(order_gid, new_hash, updated_at)
    return result
