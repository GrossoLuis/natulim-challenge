"""Suscriptores nuevos de los últimos N meses: Península vs Canarias (requerimiento 1).

Uso: python scripts/subscribers_report.py [--months 6] [--include-cancelled]

Criterios:
- Suscriptor nuevo = pedido con el tag de Recharge "Subscription First Order".
  Se reportan pedidos y clientes únicos.
- Canarias = España con CP 35xxx/38xxx o provincia GC/TF.
- Península = España sin Canarias, Baleares (07), Ceuta (51) ni Melilla (52).
- La zona se toma de la dirección de envío del primer pedido.
- Requiere el scope read_all_orders para ver pedidos de más de 60 días.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.canarias_tag.address import zona_espana  # noqa: E402
from app.shopify_client import ShopifyError, graphql  # noqa: E402

FIRST_ORDER_TAG = "Subscription First Order"

QUERY = """
query($cursor: String, $q: String!) {
  orders(first: 250, after: $cursor, query: $q, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      name
      createdAt
      cancelledAt
      tags
      customer { id }
      shippingAddress { zip provinceCode countryCodeV2 }
    }
  }
}
"""

ZONAS = [
    ("peninsula", "Península"),
    ("canarias", "Canarias"),
    ("otras_es", "Baleares/Ceuta/Melilla"),
    ("extranjero", "Fuera de España"),
    ("sin_direccion", "Sin dirección de envío"),
]


def fetch_first_orders(since: datetime) -> list[dict]:
    q = f"tag:'{FIRST_ORDER_TAG}' AND created_at:>='{since.strftime('%Y-%m-%dT%H:%M:%SZ')}'"
    orders: list[dict] = []
    cursor = None
    while True:
        data = graphql(QUERY, {"cursor": cursor, "q": q})["orders"]
        # La búsqueda por tag no distingue mayúsculas ni coincidencias parciales: se filtra exacto.
        orders += [o for o in data["nodes"] if FIRST_ORDER_TAG in o["tags"]]
        if not data["pageInfo"]["hasNextPage"]:
            return orders
        cursor = data["pageInfo"]["endCursor"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--include-cancelled", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=round(args.months * 30.44))

    try:
        orders = fetch_first_orders(since)
    except ShopifyError as exc:
        print(f"Error de Shopify: {exc}\n{exc.details}")
        return 1

    cancelados = [o for o in orders if o["cancelledAt"]]
    if not args.include_cancelled:
        orders = [o for o in orders if not o["cancelledAt"]]

    pedidos: Counter[str] = Counter()
    clientes: dict[str, set[str]] = {z: set() for z, _ in ZONAS}
    for order in orders:
        zona = zona_espana(order["shippingAddress"])
        pedidos[zona] += 1
        clientes[zona].add((order.get("customer") or {}).get("id") or order["name"])

    print(f"Suscriptores nuevos (tag '{FIRST_ORDER_TAG}') desde {since:%Y-%m-%d} hasta {now:%Y-%m-%d}")
    print(f"Pedidos cancelados {'incluidos' if args.include_cancelled else 'excluidos'}: {len(cancelados)}")
    print(f"{'Zona':<26}{'Pedidos':>10}{'Clientes':>10}")
    for zona, etiqueta in ZONAS:
        print(f"{etiqueta:<26}{pedidos[zona]:>10}{len(clientes[zona]):>10}")
    print(f"{'Total':<26}{sum(pedidos.values()):>10}{sum(len(c) for c in clientes.values()):>10}")

    pen, can = len(clientes["peninsula"]), len(clientes["canarias"])
    if can:
        print(f"\nPenínsula / Canarias: {pen / can:.1f}x  "
              f"(Canarias = {can / (pen + can):.1%} de Península + Canarias)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
