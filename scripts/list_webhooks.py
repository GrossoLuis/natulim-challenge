"""Lista las suscripciones de webhooks de la app, marcando las propias.

Uso: python scripts/list_webhooks.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.shopify_client import ShopifyError  # noqa: E402
from scripts.register_webhooks import is_own, list_subscriptions  # noqa: E402


def main() -> int:
    owner = get_settings().webhook_owner or ""
    try:
        subs = list_subscriptions()
    except ShopifyError as exc:
        print(f"Error de Shopify: {exc}\n{exc.details}")
        return 1
    if not subs:
        print("No hay suscripciones.")
    for sub in sorted(subs, key=lambda s: (not is_own(s, owner), s["topic"])):
        marca = "propia" if owner and is_own(sub, owner) else "otra  "
        print(f"[{marca}] {sub['topic']:<18} {sub['uri']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
