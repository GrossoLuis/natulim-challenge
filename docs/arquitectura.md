# Arquitectura

En este documento explico cómo está organizado el servicio y por qué tomé cada una de las decisiones principales de diseño.


## Flujo general

```
Shopify (orders/create, orders/updated, orders/cancelled, orders/delete)
   |
   |  notificación firmada con HMAC-SHA256
   v
Túnel o servidor HTTPS
   |
   v
FastAPI  POST /webhooks  (app/main.py)
   |  1. lee el contenido original de la notificación
   |  2. verifica la firma y la tienda de origen
   |  3. pasa la notificación al dispatcher
   v
Dispatcher  (app/dispatcher.py)
   |
   +--> order_sync    (requerimiento 3) --> base SQLite  data/orders.db
   |
   +--> canarias_tag  (requerimiento 4) --> Admin API de Shopify (tag y metafield)

scripts/reconcile.py  (tarea programada) --> Admin API de Shopify --> base SQLite
```

El servicio responde a Shopify con 200 si procesó la notificación correctamente, con 401 si la firma no es válida y con 500 si falló el procesamiento. En este último caso, Shopify vuelve a enviar la notificación más tarde.


## Por qué usé webhooks y no consultas periódicas

Con webhooks, Shopify avisa al servicio cada vez que un pedido se crea o cambia, y el pedido queda guardado en la base pocos segundos después. Si en cambio el servicio consultara la API cada pocos minutos, habría siempre un retraso, se consumiría el límite de consultas de la API aunque no hubiera cambios y sería más difícil detectar todas las modificaciones. Además, Shopify envía `orders/updated` ante cualquier cambio del pedido (productos, dirección, tags, pagos o envío), y `orders/cancelled` y `orders/delete` para la cancelación y el borrado.


## Por qué agregué una reconciliación

Shopify no garantiza que todas sus notificaciones lleguen. Si el servicio no responde, Shopify reintenta durante un tiempo, y si los fallos continúan, termina eliminando la suscripción. También se pueden perder notificaciones durante un despliegue o una caída del servidor.

Por eso agregué `scripts/reconcile.py`, que consulta por API los pedidos modificados desde la última reconciliación y los guarda con exactamente la misma lógica que usan los webhooks. Para no duplicar código, el servicio tiene dos funciones que convierten los datos de cada fuente al mismo formato: `from_webhook()` para las notificaciones y `from_graphql()` para las consultas.

La reconciliación toma como punto de partida la fecha de su última ejecución exitosa, con 10 minutos de margen. Descarté usar la fecha del último pedido sincronizado: si una notificación se pierde y después llegan otras, esa fecha avanza y el pedido perdido no se recuperaría nunca.


## Cómo manejo duplicados y notificaciones desordenadas

Shopify puede enviar la misma notificación más de una vez y no garantiza el orden de llegada. En la tienda de desarrollo lo comprobé: la notificación de actualización de un pedido llegó antes que la de su creación. Para que esto no genere errores, el servicio se protege de cuatro formas:

- **Notificaciones repetidas.** Cada notificación tiene un identificador único (`X-Shopify-Webhook-Id`). El servicio lo registra en la tabla `processed_webhooks`, en la misma transacción en que guarda el pedido, e ignora cualquier notificación que ya haya procesado.
- **Notificaciones atrasadas.** El servicio compara la fecha de actualización de la notificación con la del pedido guardado y, si es anterior, la ignora. La comparación se hace sobre fechas con zona horaria, no sobre texto, porque Shopify puede expresar la misma hora con distintas zonas.
- **Ediciones de productos.** Cada vez que se actualiza un pedido, se reemplazan todas sus líneas. Además, cada línea guarda la cantidad vigente: si un producto se quita con la opción Editar, su cantidad queda en 0.
- **Fallo parcial.** Si uno de los dos procesos falla y el otro no, el servicio responde con un error para que Shopify reintente. Esto no genera duplicados, porque los dos procesos pueden ejecutarse varias veces con el mismo resultado.


## Por qué uso un metafield en el requerimiento 4

La notificación `orders/updated` no indica qué cambió en el pedido. Para saber si la dirección de envío *cambió a* Canarias, y no simplemente si *es* de Canarias, el servicio necesita conocer la dirección anterior. Como el requerimiento no usa base de datos, guardo esa información en el propio pedido, en un metafield:

```
natulim.shipping_address_hash = "<huella de la dirección>|<fecha de la notificación>"
```

La huella es un código SHA-256 calculado a partir de la dirección normalizada (en minúsculas y sin espacios repetidos), de modo que dos direcciones iguales escritas con distintas mayúsculas o espacios dan la misma huella.

El funcionamiento es el siguiente:

- **Al crearse un pedido,** el servicio guarda la huella de su dirección y no agrega el tag, porque un pedido que nace con dirección en Canarias no tuvo un cambio de dirección.
- **Al actualizarse un pedido:**
  - si no tiene metafield, el servicio guarda la huella de la dirección actual;
  - si la notificación es más antigua que la información guardada, la ignora;
  - si la huella es la misma, no escribe nada;
  - si la huella cambió y la nueva dirección es de Canarias, agrega el tag (si no lo tenía) y actualiza el metafield. Si no es de Canarias, solo actualiza el metafield.

La regla de no escribir nada cuando la huella no cambió evita un ciclo infinito. Cuando el servicio agrega el tag o actualiza el metafield, Shopify envía una nueva notificación `orders/updated`. Esa notificación trae la misma dirección, así que el servicio no escribe nada y el ciclo se detiene. En la prueba real, el tag se agregó una sola vez.

Elegí un metafield porque es un dato nativo de Shopify: viaja con el pedido, no requiere infraestructura adicional y se puede consultar desde el admin o la API.


## Criterio para identificar Canarias y Península

El criterio está definido en un solo lugar, `app/canarias_tag/address.py`, y lo usan tanto el reporte del requerimiento 1 como el marcado del requerimiento 4, para que ambos den siempre el mismo resultado.

- **Canarias:** dirección en España con provincia Las Palmas (`GC`) o Santa Cruz de Tenerife (`TF`), o con código postal que empieza por 35 o 38. Uso las dos señales porque la provincia puede venir vacía o mal cargada, mientras que el código postal es más confiable.
- **Península:** dirección en España que no es de Canarias, Baleares (código postal 07), Ceuta (51) ni Melilla (52).


## Tiempo de respuesta

Shopify espera una respuesta en menos de 5 segundos. En las pruebas, el servicio respondió en tiempos de entre 0,1 y 2,2 segundos. La mayor parte de ese tiempo corresponde a las consultas a la Admin API del requerimiento 4. Si el volumen crece, el siguiente paso sería responder a Shopify inmediatamente después de verificar la firma y procesar las notificaciones desde una cola. El código ya está preparado para ese cambio, porque procesar dos veces la misma notificación no genera errores ni duplicados.
