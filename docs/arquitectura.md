# Arquitectura

## Flujo

```
                      ┌──────────────────────────────── Shopify ───────────────────────────────┐
                      │  orders/create · orders/updated · orders/cancelled · orders/delete     │
                      └───────────────┬──────────────────────────────────────▲─────────────────┘
                                      │ POST (HMAC-SHA256)                   │ GraphQL Admin API
                                      ▼                                      │ (tagsAdd, metafieldsSet,
                            ┌───────────────────┐                            │  order query, reconcile)
                            │   Túnel HTTPS     │                            │
                            └─────────┬─────────┘                            │
                                      ▼                                      │
                  ┌──────────────── FastAPI (app/main.py) ────────────────┐  │
                  │ 1. lee el body crudo   2. verifica HMAC y tienda      │  │
                  │ 3. parsea JSON         4. dispatcher.dispatch()       │  │
                  │ 200 si todo OK · 401 firma inválida · 500 → reintento │  │
                  └───────────────────────────┬───────────────────────────┘  │
                                              ▼                              │
                               ┌────── dispatcher.py ──────┐                 │
                               │ cada feature, aislado     │                 │
                               └─────┬───────────────┬─────┘                 │
                                     ▼               ▼                       │
                           ┌──────────────┐   ┌──────────────────┐           │
                           │ order_sync   │   │ canarias_tag     │───────────┘
                           │ (req. 3)     │   │ (req. 4)         │
                           └──────┬───────┘   └──────────────────┘
                                  ▼
                           ┌──────────────┐        ┌─────────────────────┐
                           │ SQLite       │◀───────│ scripts/reconcile.py│──▶ GraphQL Admin API
                           │ orders.db    │        │ (cron)              │
                           └──────────────┘        └─────────────────────┘
```

## Por qué webhooks y no polling

- **Tiempo casi real:** el pedido está en la base segundos después de crearse o modificarse.
- **Costo:** solo hay tráfico cuando algo cambia. Con polling habría que consultar la API cada pocos minutos, consumir rate limit y aun así tener retraso.
- **Cobertura de cambios:** Shopify emite `orders/updated` ante cualquier cambio (ediciones, dirección, tags, pagos, fulfillment) y `orders/cancelled` / `orders/delete` para los estados finales.

## Por qué también una reconciliación

Shopify no garantiza la entrega de los webhooks: reintenta durante un tiempo y después elimina la suscripción si el endpoint sigue fallando. Además, durante un deploy o una caída del servicio se pierden eventos.

`reconcile.py` trae por API los pedidos con `updated_at` posterior a la última reconciliación exitosa y aplica **el mismo upsert** que los webhooks:
- `from_webhook()` y `from_graphql()` normalizan las dos fuentes al mismo `dict`, así que no hay lógica duplicada.
- El punto de partida es el inicio de la última corrida y no `MAX(synced_at)`, porque si un webhook se pierde y después llegan otros, `MAX(synced_at)` avanza y el pedido perdido no se recuperaría nunca.

## Idempotencia y orden de los eventos

Shopify puede entregar un evento más de una vez y en cualquier orden. En la tienda dev se observó un `orders/updated` que llegó **antes** que el `orders/create` del mismo pedido.

| Riesgo | Mitigación |
|---|---|
| Evento duplicado o reintento | `processed_webhooks` (por `X-Shopify-Webhook-Id`), registrado en la misma transacción que el upsert |
| Evento atrasado | Se compara `updated_at` (como datetime con zona horaria). Si es anterior al guardado, se ignora |
| Ediciones de líneas | Cada upsert reemplaza todas las líneas y guarda `current_quantity`: una línea quitada con *Edit* queda con 0 |
| Un feature falla y el otro no | El dispatcher ejecuta ambos, responde 500 y Shopify reintenta. El que ya funcionó es idempotente |

## Por qué un metafield para el requerimiento 4

`orders/updated` no indica **qué** cambió. Para saber si la dirección *cambió a* Canarias, y no si *es* de Canarias, hace falta la dirección anterior. El requerimiento pide no usar base de datos, así que el estado se guarda en el propio pedido:

```
natulim.shipping_address_hash = "<sha256 de la dirección normalizada>|<updated_at del evento>"
```

- `orders/create` guarda la línea base. Un pedido que nace en Canarias no recibe el tag.
- `orders/updated`:
  - **sin metafield:** inicializa la línea base;
  - **evento más viejo que el estado guardado:** lo ignora;
  - **mismo hash:** no hace **ninguna** escritura;
  - **hash distinto:** si la nueva dirección es de Canarias, agrega el tag (salvo que ya esté); en todos los casos actualiza el metafield.

La regla "mismo hash, ninguna escritura" es la que corta el bucle: `tagsAdd` y `metafieldsSet` generan a su vez un `orders/updated`, que llega con la misma dirección y por lo tanto no escribe nada.

Un metafield es un dato nativo de Shopify: viaja con el pedido, no requiere infraestructura y se puede consultar desde el admin o la API.

## Criterio de "Canarias"

`app/canarias_tag/address.py` es la única fuente del criterio. La comparten el req. 1 (reporte) y el req. 4 (tag):

- Canarias: país `ES` y (provincia `GC`/`TF` **o** CP `35xxx`/`38xxx`). Se usan las dos señales porque la provincia puede venir vacía o mal cargada; el CP es la más robusta.
- Península: `ES` sin Canarias, Baleares (`07`/`PM`), Ceuta (`51`/`CE`) ni Melilla (`52`/`ML`).

## Respuesta a Shopify

Shopify espera respuesta en menos de 5 segundos. En las pruebas, el tiempo fue de 0,1 a 2,2 s. La mayor parte corresponde a las llamadas a la Admin API del req. 4. Con más volumen, el paso siguiente es responder 200 tras validar el HMAC y procesar los eventos en una cola (Redis, SQS, o una tabla de pendientes). La idempotencia que ya tienen los handlers lo permite sin cambios de lógica.
