# Log de decisiones: simulación Natulim

Registro cronológico de las decisiones técnicas y de análisis que fui tomando durante el trabajo.


## 2026-11-12. Inicio

- Recibí del Lead el acceso a la tienda de desarrollo y las credenciales.
- Plan de trabajo: un único servicio FastAPI que recibe los webhooks de Shopify y resuelve los requerimientos 3 y 4, más scripts auxiliares para registrar los webhooks, reconciliar pedidos e inspeccionar pedidos.


## 2026-11-12. Credenciales y entorno

- Recibí un Client ID y un Client secret de una aplicación del Dev Dashboard instalada en la tienda. Es lo esperable: desde 2026, las aplicaciones propias nuevas ya no se crean desde *Settings > Develop apps*, sino en el Dev Dashboard.
- Para obtener el token uso el *client credentials grant* (`POST https://{tienda}/admin/oauth/access_token` con `grant_type=client_credentials`), según la documentación oficial. El token dura 24 horas, así que `shopify_client.py` lo guarda en memoria, lo renueva 5 minutos antes de que venza y, si recibe un 401, pide uno nuevo una vez. También dejé soporte para un token fijo `shpat_` (`SHOPIFY_ADMIN_TOKEN`), por si el entorno productivo usa ese esquema.
- Este mecanismo tiene una limitación: solo funciona si la aplicación y la tienda pertenecen a la misma organización de Shopify.
- En las aplicaciones del Dev Dashboard, los webhooks se firman con el client secret. Por eso `SHOPIFY_WEBHOOK_SECRET` es opcional: si está vacío, se usa `SHOPIFY_CLIENT_SECRET`.
- Uso la versión `2026-10` de la Admin API, la última estable a la fecha, con soporte hasta octubre de 2027.
- Fijé las versiones de las dependencias en `requirements.txt` para que la instalación sea reproducible.
- Agregué `.gitattributes` con finales de línea LF. Desarrollo en Windows y el equipo puede usar macOS o Linux, y así se evitan diferencias falsas en los archivos.
- Trabajo con Python 3.12 en un entorno virtual `.venv`.
- `check_connection.py` muestra el nombre de la tienda y los permisos concedidos, y avisa si falta `read_orders`, `write_orders` o `read_all_orders`. Sin `read_all_orders` solo se ven los pedidos de los últimos 60 días, lo que afectaría al requerimiento 1 y posiblemente al 2.
- Verifiqué la conexión: la tienda responde y el token se obtiene correctamente.
- La aplicación de la tienda de desarrollo tiene muchos más permisos de los necesarios. Para producción recomiendo una aplicación con solo `read_orders`, `write_orders` y `read_all_orders`.


## 2026-11-12. Inspección de pedidos (requerimiento 2)

- `scripts/inspect_orders.py` funciona con la API 2026-10 sin cambios en los campos. Agregué `cancelReason`, `customer`, `lineItems.sellingPlan` y `lineItems.lineItemGroup` para detectar suscripciones y bundles nativos.
- La tienda tiene 5.497 pedidos replicados de producción, del 14 al 21 de mayo de 2026. Decidí analizar el total y no solo los dos pedidos reportados, para no sacar conclusiones a partir de un caso aislado.
- Primer hallazgo: los dos Packs llegan al 3PL de la misma forma, como un único código (`PEHD1` y `PLD1`) en el metafield `natulim.line_items`, en el 100 % de los pedidos. Ningún Pack tiene componentes configurados en Shopify.
- Segundo hallazgo: el #6491 es el único de los 4.988 pedidos con `rc_subscription_ids` que no tiene el tag `Subscription` y que tiene vacío `rc_charge_id`. El #6480 es una compra única, sin relación con Recharge.
- Tercer hallazgo, que afecta a los requerimientos 3 y 4: la tienda y la aplicación `sevica-dev` se comparten con otras personas. Ya había suscripciones de webhooks de otra persona dirigidas a su propio túnel, y también pedidos de prueba recientes de terceros (#6498 a #6501). Por eso ajusté el plan: el script de registro no modificará suscripciones ajenas, sino que identificará las propias con un marcador en la URL y solo creará o eliminará esas. Además, los procesos tienen que tolerar que otras personas modifiquen los mismos pedidos.
- Para el requerimiento 1: los pedidos conservan los tags que Recharge escribe en Shopify (`Subscription First Order` y `Subscription Recurring Order`), así que se puede responder con números a partir de la tienda.
- El detalle y las conclusiones están en `docs/diagnostico_pedidos.md`.


## 2026-11-12. Conclusiones del requerimiento 2

- El historial del #6491 muestra que el 10 de noviembre de 2026 se modificaron sus atributos `rc_charge_id`, `rc_address_id`, `rc_subscription_ids`, `rc_payment_transaction_id` y los de seguimiento web. El escenario reproduce un primer pedido de suscripción que Recharge no terminó de registrar.
- Lo comparé con el resto de la tienda: de los 921 primeros pedidos de suscripción pagados en el checkout de Shopify, 920 tienen `rc_charge_id` y el tag `Subscription First Order`. El #6491 es el único que no tiene ninguno de los dos.
- Decidí basar el diagnóstico en el estado de Recharge del pedido y no en el tipo de Pack, porque los dos Packs se comportan igual en Shopify en el 100 % de los pedidos.
- Fundamenté las respuestas con los datos de la tienda y dejé explícitos los supuestos, sin hacer consultas adicionales al Lead Tech.


## 2026-11-12. Suscriptores nuevos (requerimiento 1)

- Definí "suscriptor nuevo" como un pedido con el tag de Recharge `Subscription First Order`, que Recharge agrega al primer pedido de cada suscripción. Reporto tanto pedidos como clientes únicos; en estos datos coinciden.
- Asigno la zona según la dirección de envío. Canarias: España con código postal 35 o 38, o provincia GC o TF. Península: España sin Canarias, Baleares (07), Ceuta (51) ni Melilla (52). Reporto Baleares, Ceuta y Melilla por separado para que el total cuadre.
- El período son los últimos 6 meses (unos 183 días) desde la fecha de ejecución. Excluyo los pedidos cancelados por defecto; se pueden incluir con `--include-cancelled`. En estos datos no hay cancelados.
- Ubiqué la clasificación por zona en `app/canarias_tag/address.py` para reutilizarla en el requerimiento 4, de modo que los dos usen el mismo criterio de "Canarias".
- Resultado del 13/05/2026 al 12/11/2026: Península 854, Canarias 32, Baleares, Ceuta y Melilla 34; total 920. Lo verifiqué contra un volcado completo de pedidos.
- El #6491 no se cuenta porque no tiene el tag. Es de Baleares, así que no afecta la comparación.
- Algunas líneas tienen atributos `stayai_*`, de otra aplicación de suscripciones. Verifiqué que los 1.568 pedidos con esas líneas tienen el tag `Subscription` y que todos son renovaciones, no primeros pedidos, así que no quedan suscriptores nuevos fuera del criterio.


## 2026-11-12. Servidor de webhooks

- El servicio FastAPI expone `POST /webhooks` y `GET /health`. La firma HMAC se calcula sobre el contenido original de la notificación, antes de interpretar el JSON, y se compara con `hmac.compare_digest`. Rechazo la notificación con 401 si la firma no es válida o si la tienda de origen (`X-Shopify-Shop-Domain`) no es la configurada.
- Los procesos usan httpx y sqlite3, que son síncronos, así que los ejecuto en un hilo aparte (`run_in_threadpool`) para no bloquear el servidor.
- El dispatcher ejecuta cada proceso por separado: si uno falla, el otro se ejecuta igual, y el servicio responde 500 para que Shopify reintente. Por eso todos los procesos tienen que poder ejecutarse más de una vez sin efectos indeseados, ya que un reintento también vuelve a ejecutar el que había funcionado. El requerimiento 3 lo resuelve con la tabla `processed_webhooks` y el requerimiento 4 con la comparación de la huella de la dirección.
- Los tests nunca leen el `.env` real: `conftest.py` define variables ficticias antes de cargar la aplicación.
- Lo verifiqué con el servidor en funcionamiento: una firma inválida devuelve 401 y una firma válida devuelve 200.


## 2026-11-12. Registro de webhooks

- En la API 2026-10, el destino de la suscripción se indica con el campo `uri`, según la documentación. El formato es JSON.
- Como la aplicación `sevica-dev` es compartida y ya tenía suscripciones de otra persona, actualizar la suscripción de cada topic le habría cambiado la URL a esa persona. Por eso cada suscripción propia lleva el marcador `?owner={WEBHOOK_OWNER}` en la URL, y `register_webhooks.py` solo crea, actualiza o elimina las que lo tienen. En producción, con una aplicación dedicada, el marcador no molesta y el comportamiento es el mismo.
- `register_webhooks.py --delete` elimina las suscripciones propias, para no dejar notificaciones dirigidas a un túnel apagado.
- `list_webhooks.py` indica si cada suscripción es propia o de otra persona.
- El primer intento de crear un túnel de Cloudflare devolvió un error 429 (límite de solicitudes). Lo resolví reintentando más tarde.


## 2026-11-12. Sincronización en SQLite (requerimiento 3)

- Al esquema planificado le agregué dos elementos:
  - La columna `order_lines.current_quantity`. Cuando se quita un producto con la opción Editar, la notificación de Shopify lo sigue incluyendo, pero con `current_quantity = 0`. Si solo guardara `quantity`, que es la cantidad original, la base no reflejaría la edición. Guardo ambas.
  - La tabla `sync_state`, que guarda la fecha de inicio de la última reconciliación.
- Guardo los precios como texto, tal como los envía Shopify, para no perder precisión decimal. Uso los totales vigentes (`current_*`), que reflejan ediciones y reembolsos parciales.
- Comparo las fechas como fechas con zona horaria y no como texto. El test `test_comparacion_con_zonas_horarias_distintas` cubre un caso en que la comparación como texto daría un resultado incorrecto.
- El registro de la notificación procesada (`X-Shopify-Webhook-Id`) se hace en la misma transacción que el guardado del pedido. Las notificaciones que se ignoran por ser anteriores a la puesta en marcha o por estar atrasadas también quedan registradas como procesadas.
- Unifiqué los estados entre las notificaciones y la API GraphQL: `financial_status` en minúsculas, y en `fulfillment_status` el valor vacío pasa a `unfulfilled` y `partial` pasa a `partially_fulfilled`.
- `SYNC_START_AT` es obligatorio para iniciar el servicio. Sin ese valor se sincronizarían pedidos anteriores, lo que contradice lo acordado con el área solicitante.
- La reconciliación parte de la fecha de inicio de su última ejecución exitosa, menos 10 minutos; la primera vez, parte de `SYNC_START_AT`. Descarté partir de la fecha del último pedido sincronizado (`MAX(synced_at)`), porque si una notificación se pierde y después llegan otras, esa fecha avanza y el pedido perdido no se recuperaría nunca.
- Lo verifiqué contra la tienda: `reconcile.py` guardó el pedido de prueba más reciente con sus líneas, y una segunda ejecución no generó duplicados.


## 2026-11-12. Marcado por cambio de dirección a Canarias (requerimiento 4)

- La notificación `orders/updated` se envía ante cualquier cambio del pedido y no indica qué cambió. Si solo verificara que la dirección actual es de Canarias, marcaría también los pedidos que se crearon con dirección canaria, y eso no es un cambio. Por eso necesito conocer la dirección anterior. Como el requerimiento no usa base de datos, guardo esa información en el propio pedido, en el metafield `natulim.shipping_address_hash`. Un metafield es un dato nativo de Shopify, no una base externa.
- El metafield guarda la huella SHA-256 de la dirección y la fecha de la notificación (`<huella>|<fecha>`). La fecha me permite descartar notificaciones que lleguen atrasadas, porque Shopify no garantiza el orden de llegada. Así, una notificación antigua no reemplaza información más reciente.
- Cuando el servicio agrega el tag o actualiza el metafield, Shopify envía otra notificación `orders/updated`. Esa notificación trae la misma dirección, la huella coincide y el servicio no escribe nada, lo que evita un ciclo infinito. Hay un test específico para este caso.
- Decido si agregar el tag a partir de los tags que consulto por API en ese momento, no de los que trae la notificación, que pueden estar desactualizados.
- Uso el mismo criterio de Canarias que en el requerimiento 1 (provincia GC o TF, o código postal 35 o 38, solo en España).
- Como la aplicación es compartida, si el metafield tiene un valor con otro formato (por ejemplo, de otra persona que usa la misma clave), el servicio lo trata como si no existiera y registra la dirección actual, en lugar de fallar. El nombre del metafield es configurable (`ADDRESS_METAFIELD_*`).
- Decisiones de alcance:
  - El tag no se quita si después la dirección deja de ser de Canarias, porque su objetivo es registrar que hubo un cambio a Canarias.
  - Un cambio entre dos direcciones canarias (por ejemplo, de Las Palmas a Tenerife) sí agrega el tag. Es la lectura literal del requerimiento: se editó la dirección y la nueva es de Canarias.
  - No verifico que el cambio lo haya hecho alguien de CX, porque la notificación no lo informa de forma confiable. Una alternativa sería consultar el historial de eventos del pedido; lo dejé fuera del alcance.
  - Los pedidos anteriores a la puesta en marcha no tienen la dirección registrada, así que su primera actualización solo la registra y no agrega el tag. Una solución posible es ejecutar, al momento del despliegue, un script que registre la dirección de los pedidos abiertos.


## 2026-11-12. Pruebas en la tienda de desarrollo

- Usé un túnel de Cloudflare. Las suscripciones se registraron sin necesidad de aprobar el acceso a datos protegidos. Una segunda ejecución de `register_webhooks.py` no cambió nada, y las suscripciones de la otra persona quedaron intactas.
- Pedido #6502, con dirección en Madrid (28001):
  - al crearlo, se guardó en SQLite con sus dos líneas, se registró su dirección en el metafield y no recibió el tag;
  - al quitarle un producto, la línea quedó con `current_quantity = 0` y el total bajó de 72,00 a 33,00;
  - al cambiar la dirección a Las Palmas (35001), el tag se agregó una sola vez, y la notificación siguiente, generada por esa escritura, indicó "sin cambios de dirección";
  - al cancelarlo, se registró `cancelled_at`.
- El pedido #6503, creado directamente con dirección en Santa Cruz de Tenerife (38001), no recibió el tag.
- Observé dos comportamientos reales que el diseño ya contemplaba:
  - Las notificaciones `orders/create` y `orders/updated` llegan casi al mismo tiempo. En el #6503, la de actualización llegó antes que la de creación, y los dos procesos lo manejaron correctamente.
  - El servicio respondió en tiempos de entre 0,1 y 2,2 segundos, por debajo del límite de 5 segundos de Shopify. La mayor parte del tiempo corresponde a las consultas a la API del requerimiento 4. Con más volumen, convendría responder de inmediato y procesar las notificaciones desde una cola.


## 2026-11-12. Documentación

- Redacté la documentación sin tablas, en párrafos y listas simples, para que se lea bien tanto en GitHub como en un editor de texto.
- En el documento final entregable (`docs/DOCUMENTO_FINAL_ENTREGABLE.md`), respondí que los requerimientos 3 y 4 pueden pasar a producción: la lógica está terminada y probada, y lo que falta son tareas de puesta en marcha (servidor, aplicación en la tienda productiva y tareas programadas), no desarrollo.
