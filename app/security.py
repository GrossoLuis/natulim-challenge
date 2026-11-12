"""Verificación de la firma HMAC de los webhooks de Shopify."""

from __future__ import annotations

import base64
import hashlib
import hmac


def compute_hmac(raw_body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_webhook(raw_body: bytes, hmac_header: str | None, secret: str) -> bool:
    """HMAC-SHA256 del body crudo en base64, comparado en tiempo constante."""
    if not hmac_header or not secret:
        return False
    return hmac.compare_digest(compute_hmac(raw_body, secret), hmac_header.strip())
