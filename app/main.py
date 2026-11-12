"""Servicio FastAPI que recibe los webhooks de pedidos de Shopify.

Ejecutar: uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app import dispatcher
from app.config import get_settings
from app.security import verify_webhook

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app.webhooks")


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings()  # falla al arrancar si la configuración es inválida
    dispatcher.register_handlers()
    yield


app = FastAPI(title="Natulim - webhooks de pedidos", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/webhooks")
async def webhooks(request: Request) -> JSONResponse:
    started = time.perf_counter()
    settings = get_settings()

    # El HMAC se calcula sobre el body crudo: hay que leerlo antes de parsear el JSON.
    raw = await request.body()
    if not verify_webhook(raw, request.headers.get("X-Shopify-Hmac-Sha256"), settings.webhook_secret):
        logger.warning("Webhook rechazado: HMAC inválido")
        return JSONResponse({"error": "invalid hmac"}, status_code=401)

    topic = request.headers.get("X-Shopify-Topic", "")
    webhook_id = request.headers.get("X-Shopify-Webhook-Id", "")
    shop = request.headers.get("X-Shopify-Shop-Domain", "")
    if shop != settings.shop_domain:
        logger.warning("Webhook rechazado: tienda %r no coincide", shop)
        return JSONResponse({"error": "unknown shop"}, status_code=401)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    order_ref = f"{payload.get('id')}/{payload.get('name', '-')}"
    try:
        results = await run_in_threadpool(dispatcher.dispatch, topic, webhook_id, payload)
    except dispatcher.DispatchError as exc:
        logger.error("topic=%s webhook_id=%s pedido=%s ERROR %s (%.0f ms)",
                     topic, webhook_id, order_ref, exc, (time.perf_counter() - started) * 1000)
        return JSONResponse({"error": str(exc)}, status_code=500)

    logger.info("topic=%s webhook_id=%s pedido=%s OK %s (%.0f ms)",
                topic, webhook_id, order_ref, results, (time.perf_counter() - started) * 1000)
    return JSONResponse({"ok": True})
