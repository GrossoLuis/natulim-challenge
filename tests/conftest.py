"""Configuración común de tests: variables de entorno ficticias antes de importar la app."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# load_dotenv no pisa variables ya definidas: los tests nunca usan el .env real.
TEST_ENV = {
    "SHOPIFY_SHOP_DOMAIN": "tienda-test.myshopify.com",
    "SHOPIFY_API_VERSION": "2026-10",
    "SHOPIFY_ADMIN_TOKEN": "shpat_test",
    "SHOPIFY_CLIENT_ID": "",
    "SHOPIFY_CLIENT_SECRET": "",
    "SHOPIFY_WEBHOOK_SECRET": "secreto-de-test",
    "PUBLIC_BASE_URL": "",
    "SYNC_START_AT": "2026-11-01T00:00:00Z",
}
os.environ.update(TEST_ENV)


@pytest.fixture(autouse=True)
def _settings_limpias():
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
