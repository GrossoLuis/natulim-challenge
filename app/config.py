"""Carga y validación de la configuración desde variables de entorno (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


class ConfigError(RuntimeError):
    """Falta o es inválida alguna variable de entorno."""


@dataclass(frozen=True)
class Settings:
    shop_domain: str
    api_version: str
    admin_token: str | None
    client_id: str | None
    client_secret: str | None
    webhook_secret: str
    public_base_url: str | None
    webhook_owner: str | None
    database_path: Path
    sync_start_at: datetime | None
    canarias_tag: str
    address_metafield_namespace: str
    address_metafield_key: str


def _get(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, "").strip()
    return value or default


def parse_iso_datetime(value: str) -> datetime:
    """Parsea ISO 8601 aceptando el sufijo "Z". Exige zona horaria."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"la fecha {value!r} no tiene zona horaria")
    return parsed


def load_settings() -> Settings:
    missing: list[str] = []

    shop_domain = _get("SHOPIFY_SHOP_DOMAIN")
    if not shop_domain:
        missing.append("SHOPIFY_SHOP_DOMAIN")
    else:
        shop_domain = shop_domain.removeprefix("https://").removeprefix("http://").rstrip("/")

    admin_token = _get("SHOPIFY_ADMIN_TOKEN")
    client_id = _get("SHOPIFY_CLIENT_ID")
    client_secret = _get("SHOPIFY_CLIENT_SECRET")
    if not admin_token and not (client_id and client_secret):
        missing.append("SHOPIFY_ADMIN_TOKEN o el par SHOPIFY_CLIENT_ID/SHOPIFY_CLIENT_SECRET")

    # En apps del Dev Dashboard los webhooks se firman con el client secret.
    webhook_secret = _get("SHOPIFY_WEBHOOK_SECRET") or client_secret
    if not webhook_secret:
        missing.append("SHOPIFY_WEBHOOK_SECRET (o SHOPIFY_CLIENT_SECRET)")

    if missing:
        raise ConfigError(
            "Faltan variables de entorno: " + ", ".join(missing) + ". Revisá el archivo .env (ver .env.example)."
        )

    sync_start_raw = _get("SYNC_START_AT")
    try:
        sync_start_at = parse_iso_datetime(sync_start_raw) if sync_start_raw else None
    except ValueError as exc:
        raise ConfigError(f"SYNC_START_AT inválido: {exc}") from exc

    database_path = Path(_get("DATABASE_PATH", "data/orders.db"))
    if not database_path.is_absolute():
        database_path = BASE_DIR / database_path

    public_base_url = _get("PUBLIC_BASE_URL")

    return Settings(
        shop_domain=shop_domain,
        api_version=_get("SHOPIFY_API_VERSION", "2026-10"),
        admin_token=admin_token,
        client_id=client_id,
        client_secret=client_secret,
        webhook_secret=webhook_secret,
        public_base_url=public_base_url.rstrip("/") if public_base_url else None,
        webhook_owner=_get("WEBHOOK_OWNER"),
        database_path=database_path,
        sync_start_at=sync_start_at,
        canarias_tag=_get("CANARIAS_TAG", "cambio_a_pedido_para_canarias"),
        address_metafield_namespace=_get("ADDRESS_METAFIELD_NAMESPACE", "natulim"),
        address_metafield_key=_get("ADDRESS_METAFIELD_KEY", "shipping_address_hash"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def webhook_url(settings: Settings) -> str:
    """URL de destino de los webhooks propios: {PUBLIC_BASE_URL}/webhooks?owner={WEBHOOK_OWNER}."""
    if not settings.public_base_url:
        raise ConfigError("Falta PUBLIC_BASE_URL (URL pública del túnel).")
    if not settings.webhook_owner:
        raise ConfigError("Falta WEBHOOK_OWNER (identificador de las suscripciones propias).")
    return f"{settings.public_base_url}/webhooks?owner={settings.webhook_owner}"


def mask_secret(value: str | None) -> str:
    """Enmascara un secreto para mostrarlo en consola: shpat_****1234."""
    if not value:
        return "(vacío)"
    if len(value) <= 8:
        return "****"
    prefix = value.split("_", 1)[0] + "_" if "_" in value[:8] else ""
    return f"{prefix}****{value[-4:]}"
