"""Valida las credenciales consultando el nombre de la tienda.

Uso: python scripts/check_connection.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ConfigError, get_settings, mask_secret  # noqa: E402
from app.shopify_client import ShopifyError, get_access_token, graphql  # noqa: E402

QUERY = """
{
  shop { name myshopifyDomain }
  currentAppInstallation { accessScopes { handle } }
}
"""


def main() -> int:
    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"Error de configuración: {exc}")
        return 1

    modo = "token fijo" if settings.admin_token else "client credentials"
    print(f"Tienda: {settings.shop_domain} | API {settings.api_version} | autenticación: {modo}")

    try:
        print(f"Token: {mask_secret(get_access_token())}")
        data = graphql(QUERY)
    except ShopifyError as exc:
        print(f"Error de Shopify: {exc}\n{exc.details}")
        return 1

    shop = data["shop"]
    scopes = sorted(s["handle"] for s in data["currentAppInstallation"]["accessScopes"])
    print(f"Conectado a: {shop['name']} ({shop['myshopifyDomain']})")
    print(f"Scopes concedidos: {', '.join(scopes)}")

    requeridos = {"read_orders", "write_orders"}
    faltan = requeridos - set(scopes)
    if faltan:
        print(f"ATENCIÓN: faltan scopes requeridos: {', '.join(sorted(faltan))}")
    if "read_all_orders" not in scopes:
        print("ATENCIÓN: sin read_all_orders solo se ven pedidos de los últimos 60 días.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
