"""Vuelca pedidos de Shopify para diagnóstico (requerimiento 2).

Uso: python scripts/inspect_orders.py 6491 6480

Guarda el JSON crudo en inspect_output/<numero>.json y muestra un resumen comparativo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import BASE_DIR  # noqa: E402
from app.shopify_client import ShopifyError, graphql  # noqa: E402

OUTPUT_DIR = BASE_DIR / "inspect_output"

ORDER_QUERY = """
query($q: String!) {
  orders(first: 1, query: $q) {
    nodes {
      id
      name
      createdAt
      updatedAt
      processedAt
      cancelledAt
      cancelReason
      closedAt
      displayFinancialStatus
      displayFulfillmentStatus
      sourceName
      app { name }
      tags
      note
      customAttributes { key value }
      customer { id displayName numberOfOrders }
      shippingAddress { address1 address2 city zip province provinceCode country countryCodeV2 }
      lineItems(first: 50) {
        nodes {
          title
          sku
          quantity
          variant { id sku title }
          product { id title productType tags }
          customAttributes { key value }
          sellingPlan { name sellingPlanId }
          lineItemGroup { title quantity }
        }
      }
      fulfillmentOrders(first: 10) {
        nodes {
          status
          assignedLocation { name }
          lineItems(first: 50) { nodes { totalQuantity lineItem { title sku } } }
        }
      }
      metafields(first: 20) { nodes { namespace key value } }
      events(first: 50) { nodes { createdAt message } }
    }
  }
}
"""


def find_order(number: str) -> dict | None:
    number = number.lstrip("#")
    for q in (f"name:#{number}", f"name:{number}"):
        nodes = graphql(ORDER_QUERY, {"q": q})["orders"]["nodes"]
        if nodes:
            return nodes[0]
    return None


def print_summary(order: dict) -> None:
    addr = order.get("shippingAddress") or {}
    print("=" * 80)
    print(f"Pedido {order['name']}  ({order['id']})")
    print(f"  Creado: {order['createdAt']}  Actualizado: {order['updatedAt']}  Cancelado: {order['cancelledAt']}")
    print(f"  Estado: pago={order['displayFinancialStatus']}  fulfillment={order['displayFulfillmentStatus']}")
    print(f"  Origen: sourceName={order['sourceName']}  app={(order.get('app') or {}).get('name')}")
    print(f"  Tags: {order['tags']}")
    print(f"  Nota: {order['note']!r}  Atributos: {order['customAttributes']}")
    print(f"  Envío: {addr.get('address1')}, {addr.get('zip')} {addr.get('city')}, "
          f"{addr.get('province')} ({addr.get('provinceCode')}), {addr.get('countryCodeV2')}")
    print("  Líneas:")
    for li in order["lineItems"]["nodes"]:
        product = li.get("product") or {}
        extra = []
        if li.get("customAttributes"):
            extra.append(f"attrs={li['customAttributes']}")
        if li.get("sellingPlan"):
            extra.append(f"plan={li['sellingPlan']['name']}")
        if li.get("lineItemGroup"):
            extra.append(f"grupo={li['lineItemGroup']['title']}")
        print(f"    - {li['quantity']} x {li['title']} [sku={li['sku']}] "
              f"tipo={product.get('productType')!r} tags={product.get('tags')} {' '.join(extra)}")
    print("  Fulfillment orders:")
    for fo in order["fulfillmentOrders"]["nodes"]:
        location = (fo.get("assignedLocation") or {}).get("name")
        items = ", ".join(f"{n['totalQuantity']} x {n['lineItem']['title']}" for n in fo["lineItems"]["nodes"])
        print(f"    - {fo['status']} @ {location}: {items}")
    if order["metafields"]["nodes"]:
        print("  Metafields:")
        for mf in order["metafields"]["nodes"]:
            print(f"    - {mf['namespace']}.{mf['key']} = {mf['value'][:120]}")
    print("  Eventos:")
    for ev in sorted(order["events"]["nodes"], key=lambda e: e["createdAt"]):
        print(f"    - {ev['createdAt']}  {ev['message']}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    OUTPUT_DIR.mkdir(exist_ok=True)
    for number in argv:
        try:
            order = find_order(number)
        except ShopifyError as exc:
            print(f"Error consultando {number}: {exc}\n{exc.details}")
            return 1
        if not order:
            print(f"No se encontró el pedido {number}")
            continue
        out = OUTPUT_DIR / f"{number.lstrip('#')}.json"
        out.write_text(json.dumps(order, indent=2, ensure_ascii=False), encoding="utf-8")
        print_summary(order)
        print(f"  JSON crudo: {out.relative_to(BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
