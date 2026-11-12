# Natulim · Servicio de webhooks de pedidos

Servicio en Python que recibe los webhooks de pedidos de Shopify y resuelve dos requerimientos:

- **Sincronización de pedidos (req. 3):** mantiene en SQLite una copia de cada pedido nuevo y de sus líneas, y refleja sus cambios: ediciones, cancelación y borrado.
- **Marcado de Canarias (req. 4):** cuando la dirección de envío de un pedido se edita y la nueva es de Canarias, agrega el tag `cambio_a_pedido_para_canarias`. No usa base de datos.

Incluye también scripts de análisis para los requerimientos 1 (suscriptores nuevos por zona) y 2 (diagnóstico de pedidos con Packs).

```
Shopify ──webhook──▶ túnel HTTPS ──▶ FastAPI /webhooks ──▶ dispatcher ─┬─▶ order_sync   ──▶ SQLite
                                     (verificación HMAC)                └─▶ canarias_tag ──▶ Admin API (tag + metafield)
```

Más detalle en [docs/arquitectura.md](docs/arquitectura.md).

---

## 1. Requisitos

- Python **3.11+**
- git
- Un túnel HTTPS hacia `localhost`: [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) (sin cuenta) o [`ngrok`](https://ngrok.com/download)
- Una tienda Shopify con una app propia instalada (ver punto 2)

## 2. Crear la app en Shopify

Las custom apps nuevas se crean en el **Dev Dashboard** de Shopify:

1. Entrar a [dev.shopify.com](https://dev.shopify.com) → *Apps* → *Create app*.
2. En la versión de la app, configurar los **scopes**:
   - `read_orders`: leer pedidos y recibir sus webhooks;
   - `write_orders`: `tagsAdd` y `metafieldsSet` sobre pedidos;
   - `read_all_orders`: ver pedidos de más de 60 días (lo necesitan los scripts de análisis).
3. **Protected customer data:** los webhooks de pedidos incluyen datos personales (email, dirección). En la configuración de la app hay que habilitar el acceso a protected customer data con los campos de **nombre, email y dirección**. En una tienda de desarrollo basta con seleccionarlo. En una tienda de producción requiere completar el formulario de uso de datos.
4. Instalar la app en la tienda.
5. Copiar el **Client ID** y el **Client secret** (*Settings* de la app).

El servicio obtiene el token de Admin API solo, con el *client credentials grant*, y lo renueva antes de que venza (24 h). Este grant funciona cuando la app y la tienda pertenecen a la misma organización. Si se dispone de un token fijo `shpat_...`, se puede usar en su lugar con `SHOPIFY_ADMIN_TOKEN`.

## 3. Instalación

```bash
git clone https://github.com/GrossoLuis/natulim-challenge.git
cd natulim-challenge
```

| | macOS / Linux | Windows (PowerShell) |
|---|---|---|
| Entorno virtual | `python3 -m venv .venv && source .venv/bin/activate` | `python -m venv .venv; .venv\Scripts\Activate.ps1` |
| Dependencias | `pip install -r requirements.txt` | `pip install -r requirements.txt` |
| Configuración | `cp .env.example .env` | `Copy-Item .env.example .env` |

### Variables de entorno (`.env`)

| Variable | Obligatoria | Descripción |
|---|---|---|
| `SHOPIFY_SHOP_DOMAIN` | Sí | Dominio `xxx.myshopify.com`, sin `https://` |
| `SHOPIFY_API_VERSION` | No | Versión de la Admin API. Por defecto `2026-10` |
| `SHOPIFY_CLIENT_ID` / `SHOPIFY_CLIENT_SECRET` | Sí\* | Credenciales de la app del Dev Dashboard |
| `SHOPIFY_ADMIN_TOKEN` | Sí\* | Alternativa: token fijo `shpat_...` |
| `SHOPIFY_WEBHOOK_SECRET` | No | Secret para verificar el HMAC. Si está vacío se usa `SHOPIFY_CLIENT_SECRET` |
| `PUBLIC_BASE_URL` | Para registrar webhooks | URL pública del túnel, sin barra final |
| `WEBHOOK_OWNER` | Para registrar webhooks | Identificador de esta instalación (ej. tu usuario). Va en la URL de los webhooks (`?owner=...`) para que el script de registro gestione solo las suscripciones propias si la app es compartida |
| `DATABASE_PATH` | No | Ruta de la base SQLite. Por defecto `data/orders.db` |
| `SYNC_START_AT` | Sí | ISO 8601 UTC (ej. `2026-11-12T00:00:00Z`). Los pedidos **creados antes** no se sincronizan |
| `CANARIAS_TAG` | No | Por defecto `cambio_a_pedido_para_canarias` |
| `ADDRESS_METAFIELD_NAMESPACE` / `ADDRESS_METAFIELD_KEY` | No | Metafield donde se guarda el estado de la dirección. Por defecto `natulim.shipping_address_hash` |

\* Uno de los dos: el par client ID/secret **o** el token fijo.

El archivo `.env` está en `.gitignore`. **Nunca se sube al repositorio.**

## 4. Ejecución

Con el entorno virtual activado, desde la raíz del repo:

```bash
# 1. Validar credenciales y scopes
python scripts/check_connection.py

# 2. Levantar el servicio
uvicorn app.main:app --port 8000

# 3. En otra terminal, levantar el túnel y copiar la URL https://... a PUBLIC_BASE_URL en .env
cloudflared tunnel --url http://localhost:8000      # o: ngrok http 8000

# 4. Registrar los webhooks (idempotente)
python scripts/register_webhooks.py

# 5. Verificar
python scripts/list_webhooks.py
```

- **Si la URL del túnel cambia** (los *quick tunnels* cambian en cada arranque), se vuelve a ejecutar `register_webhooks.py`: actualiza las suscripciones propias a la URL nueva.
- **Al terminar,** `python scripts/register_webhooks.py --delete` elimina las suscripciones propias, para no dejar webhooks apuntando a un túnel muerto.
- `GET /health` responde `{"status": "ok"}`.

Se registran los topics `ORDERS_CREATE`, `ORDERS_UPDATED`, `ORDERS_CANCELLED` y `ORDERS_DELETE`, todos hacia `POST /webhooks`.

## 5. Cómo probar cada requerimiento

Para consultar la base se puede usar el CLI `sqlite3` o Python:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/orders.db'); print(c.execute('SELECT id, name, updated_at, financial_status, total_price, cancelled_at, tags FROM orders').fetchall())"
python -c "import sqlite3; c=sqlite3.connect('data/orders.db'); print(c.execute('SELECT order_id, sku, title, quantity, current_quantity FROM order_lines').fetchall())"
```

### Requerimiento 3: sincronización

1. En el admin: *Pedidos → Crear pedido*, con 2 productos, un cliente con dirección y *Marcar como pagado*. El pedido se crea al marcarlo como pagado; un borrador `#D...` todavía no dispara webhooks.
2. El pedido y sus 2 líneas aparecen en `orders` y `order_lines`.
3. *Editar* el pedido y quitar un producto: la línea queda con `current_quantity = 0` y `total_price` se actualiza.
4. *Cancelar* el pedido: se completa `cancelled_at`.
5. Si se borra el pedido, queda con `deleted = 1` (soft delete).

### Requerimiento 4: tag de Canarias

1. Crear un pedido con dirección en Madrid (`28001`). **No** tiene el tag y tiene el metafield `natulim.shipping_address_hash`.
2. Editar la dirección de envío a Las Palmas de Gran Canaria, CP `35001`, provincia Las Palmas. Al recargar, aparece el tag `cambio_a_pedido_para_canarias`.
3. En los logs del servicio aparece **un solo** "tag agregado", y el evento siguiente muestra "sin cambios de dirección" (no hay bucle).
4. Crear un pedido directamente con dirección en Tenerife (`38001`). **No** recibe el tag.

## 6. Scripts auxiliares

| Script | Uso |
|---|---|
| `scripts/check_connection.py` | Valida credenciales y muestra los scopes concedidos |
| `scripts/register_webhooks.py [--delete]` | Crea, actualiza o elimina las suscripciones propias |
| `scripts/list_webhooks.py` | Lista las suscripciones, marcando las propias |
| `scripts/reconcile.py [--since ISO8601]` | Red de seguridad del req. 3: trae por API los pedidos actualizados desde la última reconciliación (menos 10 minutos de margen) y los sincroniza con el mismo upsert. Pensado para correr en un cron |
| `scripts/subscribers_report.py [--months 6]` | Req. 1: suscriptores nuevos (tag de Recharge `Subscription First Order`) por zona: Península, Canarias, Baleares/Ceuta/Melilla |
| `scripts/inspect_orders.py 6491 6480` | Req. 2: vuelca pedidos (JSON crudo en `inspect_output/`) y muestra un resumen comparativo |

## 7. Tests

```bash
pytest -v
```

Los tests no usan el `.env` real ni llaman a Shopify: usan variables ficticias, una base SQLite temporal y un cliente de Shopify simulado.

## 8. Estructura del repositorio

```
app/
  main.py              FastAPI: POST /webhooks (verificación HMAC) y GET /health
  config.py            carga y validación de variables de entorno
  security.py          verificación HMAC de webhooks
  shopify_client.py    cliente GraphQL Admin API (token por client credentials, reintentos)
  dispatcher.py        enruta cada topic a los features; aísla sus fallos
  order_sync/          req. 3: esquema SQLite, normalización webhook/GraphQL, upsert
  canarias_tag/        req. 4: clasificación de direcciones y lógica de tagging
scripts/               registro de webhooks, reconciliación y scripts de análisis
tests/                 tests de HMAC, sincronización y marcado
docs/                  arquitectura, diagnóstico del req. 2 y documento de entrega
data/                  aquí se crea orders.db (ignorado por git)
log.md                 registro cronológico de decisiones
```

## 9. Decisiones y limitaciones

El razonamiento completo está en [log.md](log.md) y [docs/arquitectura.md](docs/arquitectura.md). Resumen:

- **Webhooks + reconciliación:** los webhooks dan tiempo casi real, pero Shopify no garantiza la entrega. `reconcile.py` cubre los huecos.
- **Idempotencia:** dedup por `X-Shopify-Webhook-Id`, comparación de `updated_at` como datetime y reemplazo completo de líneas en cada upsert. Un reintento o un evento duplicado no rompe nada.
- **Pedidos anteriores al despliegue:** no se sincronizan (`SYNC_START_AT`), como se acordó.
- **Estado del req. 4 en un metafield del pedido:** permite saber si la dirección *cambió* sin usar una base de datos.
- **Limitaciones del req. 4:**
  - los pedidos previos al despliegue no tienen línea base, así que su primer cambio solo la inicializa;
  - no se verifica que el autor del cambio sea alguien de CX;
  - el tag no se quita si la dirección deja de ser canaria.
- **SQLite** es suficiente para el volumen actual y para un único proceso. Con varios workers o más volumen, conviene migrar a Postgres.
