"""Reconciliación: trae por API los pedidos actualizados recientemente y los sincroniza.

Red de seguridad del requerimiento 3: Shopify no garantiza la entrega de webhooks.
Reutiliza el mismo upsert que los webhooks; es idempotente.

Uso:
  python scripts/reconcile.py                                # desde el inicio de la última reconciliación - 10 min
  python scripts/reconcile.py --since 2026-11-12T00:00:00Z
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ConfigError, get_settings, parse_iso_datetime  # noqa: E402
from app.order_sync import repository  # noqa: E402
from app.order_sync.db import connect, init_db  # noqa: E402
from app.shopify_client import ShopifyError, graphql  # noqa: E402

QUERY = f"""
query($cursor: String, $q: String!) {{
  orders(first: 50, after: $cursor, sortKey: UPDATED_AT, query: $q) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ {repository.GRAPHQL_ORDER_FIELDS} }}
  }}
}}
"""

SAFETY_MARGIN = timedelta(minutes=10)
STATE_KEY = "last_reconcile_started_at"


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", help="ISO 8601 UTC; por defecto, inicio de la última reconciliación - 10 minutos")
    args = parser.parse_args()

    try:
        settings = get_settings()
        if not settings.sync_start_at:
            raise ConfigError("Falta SYNC_START_AT.")
    except ConfigError as exc:
        print(f"Error de configuración: {exc}")
        return 1

    init_db(settings.database_path)
    conn = connect(settings.database_path)
    started_at = datetime.now(timezone.utc)
    try:
        # Se parte del inicio de la última corrida exitosa (no de MAX(synced_at)): si un webhook
        # se perdió y luego llegaron otros, MAX(synced_at) avanzaría y el pedido perdido nunca se recuperaría.
        if args.since:
            since = parse_iso_datetime(args.since)
        else:
            last = repository.get_state(conn, STATE_KEY)
            since = parse_iso_datetime(last) - SAFETY_MARGIN if last else settings.sync_start_at
        since = max(since, settings.sync_start_at)

        q = f"updated_at:>='{_iso(since)}' AND created_at:>='{_iso(settings.sync_start_at)}'"
        print(f"Reconciliando pedidos con {q}")

        counts: Counter[str] = Counter()
        cursor = None
        while True:
            data = graphql(QUERY, {"cursor": cursor, "q": q})["orders"]
            for node in data["nodes"]:
                result = repository.upsert_order(conn, repository.from_graphql(node), settings.sync_start_at)
                counts[result] += 1
            if not data["pageInfo"]["hasNextPage"]:
                break
            cursor = data["pageInfo"]["endCursor"]
        repository.set_state(conn, STATE_KEY, started_at.isoformat(timespec="seconds"))
    except ShopifyError as exc:
        print(f"Error de Shopify: {exc}\n{exc.details}")
        return 1
    finally:
        conn.close()

    print(f"Insertados: {counts[repository.INSERTED]}  Actualizados: {counts[repository.UPDATED]}  "
          f"Omitidos: {sum(v for k, v in counts.items() if k.startswith('omitido'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
