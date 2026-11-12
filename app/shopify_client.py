"""Cliente mínimo de la GraphQL Admin API de Shopify.

Soporta dos formas de autenticación:
- token fijo de Admin API (SHOPIFY_ADMIN_TOKEN);
- client credentials grant de una app del Dev Dashboard (SHOPIFY_CLIENT_ID/SECRET):
  el token dura ~24 h, se cachea en memoria y se renueva antes de vencer.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15
MAX_RETRIES = 3
TOKEN_REFRESH_MARGIN_SECONDS = 300


class ShopifyError(RuntimeError):
    """Error devuelto por la Admin API (HTTP, errors o userErrors)."""

    def __init__(self, message: str, details: Any = None):
        super().__init__(message)
        self.details = details


_token_lock = threading.Lock()
_cached_token: str | None = None
_token_expires_at: float = 0.0


def _fetch_client_credentials_token(settings: Settings) -> tuple[str, float]:
    response = httpx.post(
        f"https://{settings.shop_domain}/admin/oauth/access_token",
        data={
            "grant_type": "client_credentials",
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
        },
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise ShopifyError(
            f"No se pudo obtener el token (HTTP {response.status_code})",
            details=response.text[:500],
        )
    body = response.json()
    expires_in = int(body.get("expires_in", 86399))
    return body["access_token"], time.time() + expires_in


def get_access_token(force_refresh: bool = False) -> str:
    settings = get_settings()
    if settings.admin_token:
        return settings.admin_token

    global _cached_token, _token_expires_at
    with _token_lock:
        if force_refresh or not _cached_token or time.time() > _token_expires_at - TOKEN_REFRESH_MARGIN_SECONDS:
            _cached_token, _token_expires_at = _fetch_client_credentials_token(settings)
            logger.info("Token de Admin API obtenido por client credentials")
        return _cached_token


def _find_user_errors(node: Any) -> list[dict]:
    """Busca recursivamente listas userErrors no vacías en la respuesta."""
    found: list[dict] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "userErrors" and value:
                found.extend(value)
            else:
                found.extend(_find_user_errors(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_find_user_errors(item))
    return found


def _is_throttled(errors: list[dict]) -> bool:
    return any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors)


def graphql(query: str, variables: dict | None = None) -> dict:
    """Ejecuta una query/mutation y devuelve `data`.

    Lanza ShopifyError si hay errores HTTP, `errors` o `userErrors`.
    Reintenta ante HTTP 429 o THROTTLED con backoff simple.
    """
    settings = get_settings()
    url = f"https://{settings.shop_domain}/admin/api/{settings.api_version}/graphql.json"
    payload = {"query": query, "variables": variables or {}}
    token_refreshed = False

    for attempt in range(MAX_RETRIES + 1):
        headers = {
            "X-Shopify-Access-Token": get_access_token(),
            "Content-Type": "application/json",
        }
        response = httpx.post(url, json=payload, headers=headers, timeout=TIMEOUT_SECONDS)

        if response.status_code == 401 and not settings.admin_token and not token_refreshed:
            # El token cacheado pudo vencer o revocarse: se pide uno nuevo una sola vez.
            get_access_token(force_refresh=True)
            token_refreshed = True
            continue

        if response.status_code == 429:
            if attempt < MAX_RETRIES:
                wait = float(response.headers.get("Retry-After", 2 ** attempt))
                logger.warning("HTTP 429 de Shopify, reintento en %.1fs", wait)
                time.sleep(wait)
                continue
            raise ShopifyError("HTTP 429: se agotaron los reintentos")

        if response.status_code != 200:
            raise ShopifyError(f"HTTP {response.status_code} de Shopify", details=response.text[:500])

        body = response.json()
        errors = body.get("errors") or []
        if errors:
            if _is_throttled(errors) and attempt < MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning("Query THROTTLED, reintento en %ss", wait)
                time.sleep(wait)
                continue
            raise ShopifyError("La Admin API devolvió errors", details=errors)

        data = body.get("data") or {}
        user_errors = _find_user_errors(data)
        if user_errors:
            raise ShopifyError("La Admin API devolvió userErrors", details=user_errors)
        return data

    raise ShopifyError("Se agotaron los reintentos contra la Admin API")
