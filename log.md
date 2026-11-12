# Log de decisiones — Simulación Natulim

Registro cronológico de decisiones técnicas y de análisis.

## 2026-11-12 — Inicio
- Acceso a la tienda dev y credenciales recibidas del Lead Tech.
- Plan: un único servicio FastAPI que recibe webhooks de Shopify y resuelve los requerimientos 3 y 4; scripts auxiliares para registro de webhooks, reconciliación e inspección de pedidos.

## 2026-11-12 — Fase 0: credenciales y entorno
- **Tipo de credencial:** Client ID + Client secret de una app del Dev Dashboard instalada en la tienda dev. Desde 2026 las custom apps nuevas ya no se crean desde *Settings → Develop apps* sino en el Dev Dashboard, por lo que este es el caso esperable.
- **Autenticación:** client credentials grant (`POST https://{shop}/admin/oauth/access_token`, `grant_type=client_credentials`), verificado en la documentación oficial. El token dura ~24 h (`expires_in: 86399`): `shopify_client.py` lo cachea en memoria, lo renueva 5 minutos antes de vencer y reintenta una vez si recibe 401. Se mantiene compatibilidad con un token fijo `shpat_` (`SHOPIFY_ADMIN_TOKEN`) por si el entorno productivo usa ese esquema.
- **Limitación conocida del grant:** solo funciona si la app y la tienda pertenecen a la misma organización de Shopify.
- **Secret de webhooks:** en apps del Dev Dashboard los webhooks se firman con el client secret. `SHOPIFY_WEBHOOK_SECRET` es opcional y, si está vacío, se usa `SHOPIFY_CLIENT_SECRET`.
- **Versión de la API:** `2026-10`, última estable a la fecha (soportada hasta octubre de 2027).
- **Dependencias con versión fija** en `requirements.txt`, para que la instalación sea reproducible por el equipo.
- **`.gitattributes` con `eol=lf`:** el desarrollo es en Windows y el equipo puede usar macOS/Linux; se evitan diffs por finales de línea.
- **Python 3.12** en un entorno virtual `.venv`.
- `check_connection.py` además de mostrar la tienda lista los scopes concedidos y avisa si falta `read_orders`, `write_orders` o `read_all_orders` (sin este último solo se ven pedidos de los últimos 60 días, lo que afecta al requerimiento 1 y posiblemente al 2).
- **Conexión verificada** con `check_connection.py`: tienda dev accesible, token obtenido por client credentials.
- **Scopes:** la app de la tienda dev tiene concedidos muchos más scopes de los necesarios (incluye `read_orders`, `write_orders` y `read_all_orders`). Para producción se recomienda una app con solo los scopes mínimos: `read_orders`, `write_orders` y `read_all_orders`.

## 2026-11-12 — Fase 1: inspección de pedidos (requerimiento 2)
- `scripts/inspect_orders.py` funciona con la API 2026-10 sin cambios en los campos. Se agregaron `cancelReason`, `customer`, `lineItems.sellingPlan` y `lineItems.lineItemGroup` para detectar suscripciones y bundles nativos.
- La tienda dev tiene 5.497 pedidos replicados de producción (14–21 de mayo de 2026). Se analizó el total, no solo los dos pedidos, para no sacar conclusiones de un caso aislado.
- **Hallazgo 1:** los dos Packs llegan al 3PL igual: un único código (`PEHD1` / `PLD1`) en el metafield `natulim.line_items`, en el 100 % de los pedidos. Ningún Pack tiene componentes nativos configurados.
- **Hallazgo 2:** #6491 es el único de 4.988 pedidos con `rc_subscription_ids` que no tiene el tag `Subscription` y tiene `rc_charge_id` vacío. #6480 es una compra única sin Recharge.
- **Hallazgo 3 (impacta en las fases 3–5):** la tienda dev y la app `sevica-dev` son **compartidas**. Ya existen suscripciones `ORDERS_CREATE/UPDATED/DELETE` de otra persona apuntando a su propio túnel, y hay pedidos de prueba recientes de terceros (#6498–#6501). **Desvío del plan:** `register_webhooks.py` no va a actualizar suscripciones que no sean propias. Va a identificar las nuestras por un marcador en la URL y solo va a crear o borrar esas. Además, los handlers deben tolerar cambios hechos por otros procesos sobre los mismos pedidos.
- Requerimiento 1: los pedidos tienen los tags de Recharge `Subscription First Order` / `Subscription Recurring Order`, de modo que se puede responder con números a partir de la tienda (ver fase correspondiente).
- Detalle y conclusiones en `docs/diagnostico_pedidos.md`.

## 2026-11-12 — Requerimiento 2: conclusiones revisadas
- El evento de edición de #6491 (2026-11-10) modificó los atributos `rc_charge_id`, `rc_address_id`, `rc_subscription_ids`, `rc_payment_transaction_id` y los de tracking web. El escenario reproduce un primer pedido de suscripción que Recharge no terminó de registrar.
- Se comparó contra la base: de 921 primeros pedidos de suscripción pagados en Shopify Checkout, 920 tienen `rc_charge_id` y tag `Subscription First Order`. #6491 es el único sin ambos.
- **Decisión:** el diagnóstico se basa en la variable "estado de Recharge del pedido" y no en "tipo de Pack", porque los dos Packs se comportan igual en Shopify en el 100 % de los pedidos.
- Se trabaja sin consultas adicionales al Lead Tech: las respuestas se fundamentan con los datos de la tienda y los supuestos quedan explícitos.

## 2026-11-12 — Requerimiento 1: suscriptores nuevos
- **Definición:** suscriptor nuevo = pedido con el tag de Recharge `Subscription First Order`. Recharge pone ese tag en el primer pedido de cada suscripción. Se reportan pedidos y clientes únicos; en estos datos coinciden.
- **Zonas** (por dirección de envío): Canarias = ES con CP 35/38 o provincia GC/TF. Península = ES sin Canarias, Baleares (07), Ceuta (51) ni Melilla (52). Baleares, Ceuta y Melilla se reportan aparte para que el total cuadre.
- **Ventana:** últimos 6 meses (~183 días) desde la ejecución. Se excluyen cancelados por defecto (`--include-cancelled` para incluirlos); en estos datos no hay cancelados.
- La clasificación de zona vive en `app/canarias_tag/address.py` y se reutiliza en el requerimiento 4, para que ambos usen el mismo criterio de "Canarias".
- **Resultado** (2026-05-13 → 2026-11-12): Península 854, Canarias 32, Baleares/Ceuta/Melilla 34; total 920. Se verificó contra un volcado completo de pedidos.
- **Limitación:** #6491 no se cuenta porque no tiene el tag (es Baleares, no afecta a la comparación). Algunas líneas tienen atributos `stayai_*`, otra app de suscripciones. Se verificó que los 1.568 pedidos con esas líneas tienen el tag `Subscription` y todos son recurrentes (ninguno es primer pedido), así que no hay suscriptores nuevos fuera del criterio.

## 2026-11-12 — Fase 2: servidor de webhooks
- FastAPI con `POST /webhooks` y `GET /health`. El HMAC se calcula sobre el body crudo antes de parsear el JSON y se compara con `hmac.compare_digest`. Se rechaza con 401 si la firma es inválida o si `X-Shopify-Shop-Domain` no es la tienda configurada.
- Los handlers son síncronos (httpx y sqlite3) y se ejecutan en el threadpool (`run_in_threadpool`) para no bloquear el event loop.
- El dispatcher aísla cada feature: si uno falla, el otro corre igual, y se responde 500 para que Shopify reintente. Consecuencia: **todos los handlers tienen que ser idempotentes**, porque un reintento vuelve a ejecutar también el que ya había funcionado. El req. 3 lo resuelve con `processed_webhooks` y el req. 4 con la comparación de hash.
- Los tests nunca leen el `.env` real: `conftest.py` define variables ficticias antes de importar la app (`load_dotenv` no pisa variables existentes).
- Verificado con el servidor real: HMAC inválido → 401, HMAC válido → 200.

## 2026-11-12 — Fase 3: registro de webhooks
- En la API 2026-10 el destino de `WebhookSubscriptionInput` es `uri` (verificado en la documentación); `format: JSON`.
- **Desvío del brief:** la app `sevica-dev` es compartida y ya tiene suscripciones de otra instalación. Actualizar "la suscripción del topic" le cambiaría la URL a otra persona. Por eso cada suscripción propia lleva el marcador `?owner={WEBHOOK_OWNER}` en la URL, y `register_webhooks.py` solo crea, actualiza o borra las que lo tienen; las demás no se tocan. En producción, con una app dedicada, el marcador no molesta y deja el mismo comportamiento.
- `register_webhooks.py --delete` elimina las suscripciones propias, para no dejar webhooks apuntando a un túnel muerto al terminar.
- `list_webhooks.py` marca cada suscripción como `propia` u `otra`.
- **Túnel:** Cloudflare respondió 429 al pedir un *quick tunnel*; se reintenta manualmente o se usa ngrok.

## 2026-11-12 — Fase 4: sincronización a SQLite
- **Esquema:** el del brief más dos agregados.
  - `order_lines.current_quantity`: en los webhooks REST, una línea quitada con *Edit* sigue en `line_items` con `current_quantity = 0`. Guardar solo `quantity` (la original) no reflejaría las ediciones. Se guardan ambas.
  - Tabla `sync_state`: guarda el inicio de la última reconciliación.
- **Precios:** se guardan como TEXT, tal como los manda Shopify, para no perder precisión decimal. Se usan los totales `current_*`, que reflejan ediciones y reembolsos parciales.
- **Fechas:** se comparan como `datetime` con zona horaria. El test `test_comparacion_con_zonas_horarias_distintas` cubre el caso en que la comparación como string da el resultado equivocado.
- **Transacciones:** dedup por `X-Shopify-Webhook-Id` en la misma transacción que el upsert (`BEGIN IMMEDIATE`). Los webhooks omitidos por corte temporal o por antigüedad igual quedan registrados como procesados.
- **Estados normalizados** entre webhook y GraphQL: `financial_status` en minúsculas. `fulfillment_status`: `null` → `unfulfilled`, `partial` → `partially_fulfilled`.
- **`SYNC_START_AT` es obligatorio** para arrancar el servicio: si faltara, se sincronizarían pedidos viejos, lo que contradice lo acordado.
- **Reconciliación, desvío del brief:** el brief proponía partir de `MAX(synced_at) - 10 min`. Si un webhook se pierde y después llegan otros, `MAX(synced_at)` avanza y el pedido perdido no se recupera nunca. Se parte del **inicio de la última reconciliación exitosa** menos 10 minutos (guardado en `sync_state`); la primera vez, de `SYNC_START_AT`.
- Verificado contra la tienda dev: `reconcile.py` insertó el pedido de prueba más reciente con sus líneas; una segunda corrida no duplica.
