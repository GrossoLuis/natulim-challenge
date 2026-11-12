import json

import pytest
from fastapi.testclient import TestClient

from app import dispatcher
from app.main import app
from app.security import compute_hmac, verify_webhook

SECRET = "secreto-de-test"
SHOP = "tienda-test.myshopify.com"


def test_verify_webhook_valido():
    body = b'{"id": 1}'
    assert verify_webhook(body, compute_hmac(body, SECRET), SECRET)


def test_verify_webhook_invalido_o_ausente():
    body = b'{"id": 1}'
    assert not verify_webhook(body, compute_hmac(body, "otro"), SECRET)
    assert not verify_webhook(body, None, SECRET)
    assert not verify_webhook(b'{"id": 2}', compute_hmac(body, SECRET), SECRET)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _post(client, body: bytes, hmac_value: str, shop: str = SHOP):
    return client.post(
        "/webhooks",
        content=body,
        headers={
            "X-Shopify-Hmac-Sha256": hmac_value,
            "X-Shopify-Topic": "orders/updated",
            "X-Shopify-Webhook-Id": "wh-1",
            "X-Shopify-Shop-Domain": shop,
            "Content-Type": "application/json",
        },
    )


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_webhook_hmac_invalido_401(client):
    assert _post(client, b'{"id": 1}', "firma-falsa").status_code == 401


def test_webhook_tienda_distinta_401(client):
    body = b'{"id": 1}'
    assert _post(client, body, compute_hmac(body, SECRET), shop="otra.myshopify.com").status_code == 401


def test_webhook_hmac_valido_200(client, monkeypatch):
    monkeypatch.setattr(dispatcher, "HANDLERS", {})  # solo se prueba la capa HTTP
    body = json.dumps({"id": 1, "name": "#1001"}).encode()
    assert _post(client, body, compute_hmac(body, SECRET)).status_code == 200


def test_webhook_feature_falla_500_y_otro_corre(client, monkeypatch):
    llamadas = []

    def ok(topic, webhook_id, payload):
        llamadas.append("ok")
        return "ok"

    def falla(topic, webhook_id, payload):
        raise RuntimeError("boom")

    monkeypatch.setattr(dispatcher, "HANDLERS", {"orders/updated": [("falla", falla), ("ok", ok)]})
    body = b'{"id": 1}'
    assert _post(client, body, compute_hmac(body, SECRET)).status_code == 500
    assert llamadas == ["ok"]
