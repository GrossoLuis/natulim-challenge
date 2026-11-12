"""Clasificación de direcciones de envío españolas por zona.

Acepta direcciones en formato webhook/REST (country_code, province_code, zip)
o GraphQL (countryCodeV2, provinceCode, zip).
"""

from __future__ import annotations

import hashlib

CANARIAS_PROVINCE_CODES = {"GC", "TF"}  # Las Palmas, Santa Cruz de Tenerife
CANARIAS_ZIP_PREFIXES = ("35", "38")

# Zonas de España que no son Península: Baleares, Canarias, Ceuta y Melilla.
NO_PENINSULA_PROVINCE_CODES = {"PM", "GC", "TF", "CE", "ML"}
NO_PENINSULA_ZIP_PREFIXES = ("07", "35", "38", "51", "52")


def _norm(value: str | None) -> str:
    return (value or "").strip().upper()


def _campos(addr: dict) -> tuple[str, str, str]:
    country = _norm(addr.get("country_code") or addr.get("countryCodeV2") or addr.get("countryCode"))
    province = _norm(addr.get("province_code") or addr.get("provinceCode"))
    zip_code = _norm(addr.get("zip")).replace(" ", "")
    return country, province, zip_code


def es_canarias(addr: dict | None) -> bool:
    """True si la dirección es de Canarias.

    Se usan dos señales: el código de provincia (puede venir vacío o mal cargado)
    y el código postal (35xxx / 38xxx), que es la más robusta.
    """
    if not addr:
        return False
    country, province, zip_code = _campos(addr)
    if country != "ES":
        return False
    return province in CANARIAS_PROVINCE_CODES or zip_code.startswith(CANARIAS_ZIP_PREFIXES)


def zona_espana(addr: dict | None) -> str:
    """Devuelve "canarias", "peninsula", "otras_es" (Baleares, Ceuta, Melilla), "extranjero" o "sin_direccion"."""
    if not addr:
        return "sin_direccion"
    country, province, zip_code = _campos(addr)
    if country != "ES":
        return "extranjero"
    if es_canarias(addr):
        return "canarias"
    if province in NO_PENINSULA_PROVINCE_CODES or zip_code.startswith(NO_PENINSULA_ZIP_PREFIXES):
        return "otras_es"
    return "peninsula"


HASH_FIELDS = ("address1", "address2", "city", "zip", "province_code", "country_code")
_GRAPHQL_ALIASES = {"province_code": "provinceCode", "country_code": "countryCodeV2"}


def _norm_hash_field(value) -> str:
    return " ".join(str(value or "").split()).lower()


def hash_direccion(addr: dict | None) -> str:
    """SHA-256 de los campos de la dirección normalizados (minúsculas, espacios colapsados).

    Dirección ausente → "none". Es estable ante mayúsculas y espacios.
    """
    if not addr:
        return "none"
    parts = []
    for field in HASH_FIELDS:
        value = addr.get(field)
        if value is None and field in _GRAPHQL_ALIASES:
            value = addr.get(_GRAPHQL_ALIASES[field])
        parts.append(_norm_hash_field(value))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
