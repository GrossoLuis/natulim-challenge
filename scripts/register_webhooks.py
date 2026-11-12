"""Crea o actualiza las suscripciones de webhooks propias (idempotente).

Uso:
  python scripts/register_webhooks.py           # registra/actualiza hacia {PUBLIC_BASE_URL}/webhooks?owner={WEBHOOK_OWNER}
  python scripts/register_webhooks.py --delete  # elimina las suscripciones propias

Solo gestiona las suscripciones cuya URL tiene el marcador owner={WEBHOOK_OWNER}.
Las suscripciones de otras instalaciones de la misma app no se modifican.
La URL del túnel cambia en cada arranque: hay que volver a correr este script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ConfigError, get_settings, webhook_url  # noqa: E402
from app.shopify_client import ShopifyError, graphql  # noqa: E402

TOPICS = ["ORDERS_CREATE", "ORDERS_UPDATED", "ORDERS_CANCELLED", "ORDERS_DELETE"]

LIST_QUERY = """
query($cursor: String) {
  webhookSubscriptions(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { id topic uri format }
  }
}
"""

CREATE = """
mutation($topic: WebhookSubscriptionTopic!, $sub: WebhookSubscriptionInput!) {
  webhookSubscriptionCreate(topic: $topic, webhookSubscription: $sub) {
    webhookSubscription { id topic uri }
    userErrors { field message }
  }
}
"""

UPDATE = """
mutation($id: ID!, $sub: WebhookSubscriptionInput!) {
  webhookSubscriptionUpdate(id: $id, webhookSubscription: $sub) {
    webhookSubscription { id topic uri }
    userErrors { field message }
  }
}
"""

DELETE = """
mutation($id: ID!) {
  webhookSubscriptionDelete(id: $id) {
    deletedWebhookSubscriptionId
    userErrors { field message }
  }
}
"""


def list_subscriptions() -> list[dict]:
    subs: list[dict] = []
    cursor = None
    while True:
        data = graphql(LIST_QUERY, {"cursor": cursor})["webhookSubscriptions"]
        subs += data["nodes"]
        if not data["pageInfo"]["hasNextPage"]:
            return subs
        cursor = data["pageInfo"]["endCursor"]


def is_own(sub: dict, owner: str) -> bool:
    query = parse_qs(urlparse(sub.get("uri") or "").query)
    return query.get("owner") == [owner]


def run(delete: bool) -> int:
    settings = get_settings()
    owner = settings.webhook_owner
    if not owner:
        raise ConfigError("Falta WEBHOOK_OWNER (identificador de las suscripciones propias).")

    subs = list_subscriptions()
    own = [s for s in subs if is_own(s, owner)]
    print(f"Suscripciones en la app: {len(subs)} (propias: {len(own)}, de otras instalaciones: {len(subs) - len(own)})")

    if delete:
        for sub in own:
            graphql(DELETE, {"id": sub["id"]})
            print(f"  {sub['topic']:<18} eliminada")
        return 0

    target = webhook_url(settings)
    print(f"Destino: {target}")
    for topic in TOPICS:
        existing = [s for s in own if s["topic"] == topic]
        sub_input = {"uri": target, "format": "JSON"}
        if not existing:
            graphql(CREATE, {"topic": topic, "sub": sub_input})
            print(f"  {topic:<18} creada")
            continue
        first, *duplicates = existing
        if first["uri"] == target:
            print(f"  {topic:<18} sin cambios")
        else:
            graphql(UPDATE, {"id": first["id"], "sub": sub_input})
            print(f"  {topic:<18} actualizada (antes: {first['uri']})")
        for dup in duplicates:
            graphql(DELETE, {"id": dup["id"]})
            print(f"  {topic:<18} duplicada eliminada")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--delete", action="store_true", help="elimina las suscripciones propias")
    args = parser.parse_args()
    try:
        return run(args.delete)
    except ConfigError as exc:
        print(f"Error de configuración: {exc}")
    except ShopifyError as exc:
        print(f"Error de Shopify: {exc}\n{exc.details}")
        if "protected customer data" in str(exc.details).lower():
            print("La app necesita acceso a protected customer data (ver README).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
