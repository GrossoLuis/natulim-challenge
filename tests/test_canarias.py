import pytest

from app.canarias_tag import handlers
from app.canarias_tag.address import es_canarias, hash_direccion

MADRID = {"address1": "Calle Mayor 1", "address2": "", "city": "Madrid", "zip": "28001",
          "province_code": "M", "country_code": "ES"}
BARCELONA = {"address1": "Carrer Gran 2", "address2": "", "city": "Barcelona", "zip": "08001",
             "province_code": "B", "country_code": "ES"}
LAS_PALMAS = {"address1": "Calle Triana 3", "address2": "", "city": "Las Palmas de Gran Canaria",
              "zip": "35001", "province_code": "GC", "country_code": "ES"}
TAG = "cambio_a_pedido_para_canarias"


@pytest.mark.parametrize("addr, esperado", [
    ({"country_code": "ES", "province_code": "GC", "zip": ""}, True),
    ({"country_code": "ES", "province_code": "TF", "zip": ""}, True),
    ({"country_code": "ES", "province_code": "", "zip": "35001"}, True),
    ({"country_code": "ES", "province_code": None, "zip": " 38400 "}, True),
    ({"countryCodeV2": "ES", "provinceCode": "TF", "zip": "38001"}, True),  # formato GraphQL
    ({"country_code": "ES", "province_code": "M", "zip": "28001"}, False),
    ({"country_code": "PT", "province_code": "", "zip": "3500"}, False),
    (None, False),
])
def test_es_canarias(addr, esperado):
    assert es_canarias(addr) is esperado


def test_hash_estable_ante_mayusculas_y_espacios():
    variante = {**MADRID, "address1": "  calle   MAYOR 1 ", "city": "MADRID"}
    assert hash_direccion(variante) == hash_direccion(MADRID)
    assert hash_direccion(MADRID) != hash_direccion(BARCELONA)
    assert hash_direccion(None) == "none"


class FakeShopify:
    """Reemplaza shopify_client.graphql y registra las llamadas."""

    def __init__(self, metafield_value=None, tags=None):
        self.metafield_value = metafield_value
        self.tags = tags or []
        self.calls: list[str] = []
        self.saved_values: list[str] = []

    def __call__(self, query, variables=None):
        if "tagsAdd" in query:
            self.calls.append("tagsAdd")
            return {"tagsAdd": {"node": {"id": variables["id"]}, "userErrors": []}}
        if "metafieldsSet" in query:
            self.calls.append("metafieldsSet")
            self.saved_values.append(variables["metafields"][0]["value"])
            return {"metafieldsSet": {"metafields": [{"id": "m"}], "userErrors": []}}
        self.calls.append("query")
        metafield = {"value": self.metafield_value} if self.metafield_value else None
        return {"order": {"id": variables["id"], "tags": self.tags, "metafield": metafield}}

    @property
    def writes(self):
        return [c for c in self.calls if c != "query"]


def _payload(addr, updated_at="2026-11-12T10:00:00Z"):
    return {"id": 1, "admin_graphql_api_id": "gid://shopify/Order/1", "updated_at": updated_at,
            "shipping_address": addr}


def _state(addr, updated_at="2026-11-12T09:00:00Z"):
    return f"{hash_direccion(addr)}|{updated_at}"


@pytest.fixture
def fake(monkeypatch):
    def factory(**kwargs):
        f = FakeShopify(**kwargs)
        monkeypatch.setattr(handlers, "graphql", f)
        return f
    return factory


def test_create_guarda_linea_base_sin_tag(fake):
    f = fake()
    assert handlers.handle_create("orders/create", "w", _payload(LAS_PALMAS)) == handlers.BASELINE_SAVED
    assert f.writes == ["metafieldsSet"]
    assert f.saved_values == [f"{hash_direccion(LAS_PALMAS)}|2026-11-12T10:00:00Z"]


def test_pedido_sin_metafield_solo_inicializa(fake):
    f = fake()
    assert handlers.handle_updated("orders/updated", "w", _payload(LAS_PALMAS)) == handlers.BASELINE_INITIALIZED
    assert f.writes == ["metafieldsSet"]


def test_hash_igual_no_escribe_nada(fake):
    f = fake(metafield_value=_state(LAS_PALMAS))
    assert handlers.handle_updated("orders/updated", "w", _payload(LAS_PALMAS)) == handlers.NO_CHANGE
    assert f.writes == []


def test_cambio_madrid_a_las_palmas_agrega_tag(fake):
    f = fake(metafield_value=_state(MADRID))
    assert handlers.handle_updated("orders/updated", "w", _payload(LAS_PALMAS)) == handlers.TAGGED
    assert f.writes == ["tagsAdd", "metafieldsSet"]


def test_evento_siguiente_a_nuestras_escrituras_no_genera_bucle(fake):
    f = fake(metafield_value=_state(MADRID))
    handlers.handle_updated("orders/updated", "w1", _payload(LAS_PALMAS))
    # Nuestro tagsAdd/metafieldsSet dispara otro orders/updated con la misma dirección.
    f.metafield_value, f.tags, f.calls = f.saved_values[-1], [TAG], []
    resultado = handlers.handle_updated("orders/updated", "w2", _payload(LAS_PALMAS, "2026-11-12T10:00:05Z"))
    assert resultado == handlers.NO_CHANGE
    assert f.writes == []


def test_cambio_a_canarias_con_tag_ya_presente(fake):
    f = fake(metafield_value=_state(MADRID), tags=[TAG])
    assert handlers.handle_updated("orders/updated", "w", _payload(LAS_PALMAS)) == handlers.ALREADY_TAGGED
    assert f.writes == ["metafieldsSet"]


def test_cambio_madrid_a_barcelona_no_taggea(fake):
    f = fake(metafield_value=_state(MADRID))
    assert handlers.handle_updated("orders/updated", "w", _payload(BARCELONA)) == handlers.CHANGED_NOT_CANARIAS
    assert f.writes == ["metafieldsSet"]


def test_evento_atrasado_se_ignora(fake):
    f = fake(metafield_value=_state(MADRID, "2026-11-12T11:00:00Z"))
    assert handlers.handle_updated("orders/updated", "w", _payload(LAS_PALMAS, "2026-11-12T10:00:00Z")) \
        == handlers.STALE_EVENT
    assert f.writes == []


def test_metafield_con_formato_ajeno_se_trata_como_ausente(fake):
    f = fake(metafield_value="valor-de-otra-app")
    assert handlers.handle_updated("orders/updated", "w", _payload(LAS_PALMAS)) == handlers.BASELINE_INITIALIZED
    assert f.writes == ["metafieldsSet"]
