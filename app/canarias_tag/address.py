"""Clasificación de direcciones de envío españolas por zona.

Acepta direcciones en formato webhook/REST (country_code, province_code, zip)
o GraphQL (countryCodeV2, provinceCode, zip).
"""

from __future__ import annotations

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
