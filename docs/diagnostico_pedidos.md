# Diagnóstico de los pedidos #6491 y #6480 (requerimiento 2)

Para este análisis usé tres fuentes:

- la salida de `python scripts/inspect_orders.py 6491 6480`;
- un análisis de los 5.497 pedidos de la tienda de desarrollo, replicados de producción entre el 14 y el 21 de mayo de 2026;
- el historial de eventos del pedido #6491 en el admin.


## Comparación de los dos pedidos

### Pedido #6491 (según CX, no fue recibido)

- **Pack:** Pack Esenciales del Hogar, variante "2 de cada" (SKU 300246).
- **Resto del pedido:** 11 líneas más. Incluye cuatro productos, el Pack Lavavajillas a Mano y seis regalos de una promoción de aniversario.
- **Cómo figura el Pack:** en Shopify aparece como una sola línea. En el metafield `natulim.line_items`, que es la información que se envía al 3PL, aparece como un único código: `PEHD1`.
- **Tipo de compra:** es el primer pedido de una suscripción de Recharge. Se pagó en el checkout de Shopify, incluye 7 productos suscritos y el Pack se compró con frecuencia semanal.
- **Estado de Recharge:** incompleto. El identificador del cargo (`rc_charge_id`) está vacío y le faltan los tags `Subscription` y `Subscription First Order`.
- **Historial:** el 10 de noviembre de 2026 se editaron manualmente los atributos del pedido, entre ellos `rc_charge_id`, `rc_address_id`, `rc_subscription_ids` y `rc_payment_transaction_id`.
- **Otras aplicaciones que intervinieron:** AfterSell (oferta posterior a la compra), UpCart y la de regalos promocionales.
- **Dirección de envío:** Sa Pobla, Baleares (07420).
- **Envío:** transportista PQ, con número de seguimiento `PQ7NAW041278367L`.

### Pedido #6480 (según CX, fue recibido)

- **Pack:** Pack Limpiacristales, variante "2" (SKU 300259).
- **Resto del pedido:** dos líneas más, el Pack Desengrasante y las Eco Pastillas Lavavajillas.
- **Cómo figura el Pack:** en Shopify aparece como una sola línea. En `natulim.line_items` aparece como un único código: `PLD1`.
- **Tipo de compra:** compra única. No tiene ningún atributo de Recharge.
- **Historial:** sin ediciones manuales.
- **Otras aplicaciones que intervinieron:** ninguna.
- **Dirección de envío:** Madrid (28036).
- **Envío:** transportista PQ, con número de seguimiento `PQ7NAW041275177S`.


## Lo que muestra el total de pedidos

**El tipo de Pack no explica la diferencia.** En los 79 pedidos que contienen el Pack Esenciales del Hogar y en los 44 que contienen el Pack Limpiacristales, el Pack siempre aparece como una sola línea y como un único código en la información que va al 3PL. Los dos Packs se compran tanto en suscripción como en compra única, y ninguno tiene componentes configurados en Shopify. Desde Shopify se comportan exactamente igual, así que si en el 3PL uno llega desglosado y el otro no, la diferencia la produce otra cosa.

**En los primeros pedidos de suscripción, Recharge funciona de forma consistente.** De los 921 primeros pedidos de suscripción pagados en el checkout de Shopify, 920 tienen el identificador del cargo y el tag `Subscription First Order`. El único que no tiene ninguna de las dos cosas es el #6491.

**El #6491 tiene las suscripciones registradas, pero no el cierre del proceso.** Los identificadores de suscripción muestran que el cliente se suscribió, pero falta el cargo y faltan los tags, que es lo que Recharge escribe cuando termina de procesar el pedido. La edición manual del 10 de noviembre reproduce exactamente ese estado.

**El #6480 no tiene ninguna relación con Recharge.**


## Conclusiones

**Qué está pasando.** El desglose de Packs falla en los pedidos de suscripción que Recharge no terminó de procesar, no en un Pack en particular. Mi hipótesis es que la aplicación de bundles usa la información que Recharge escribe en el pedido (el cargo, los tags o el evento asociado) para identificar los pedidos de suscripción y desglosarlos. Cuando esa información falta, como en el #6491, la aplicación no desglosa. El Pack llega al 3PL como un código de kit que no existe en su catálogo, el 3PL no puede armarlo y el pedido no se completa. El #6480 es una compra única, sigue el camino normal de la aplicación, se desglosa y se entrega.

**Por qué la causa que señala Logística no es la correcta.** Logística generalizó a partir del nombre del Pack en los casos que vio: el de Esenciales falló y el de Limpiacristales no. Pero en Shopify los dos Packs se comportan igual, y la coincidencia se explica porque el pedido de Esenciales era una suscripción con el procesamiento de Recharge incompleto. Tampoco es un fallo del software del 3PL. El 3PL no tiene los kits armados y solo puede preparar lo que recibe desglosado; si recibe el código del Pack, el error ocurrió antes.

**En qué tiene razón CX.** El problema está efectivamente en la aplicación de bundles, pero no falla siempre: falla cuando depende de datos de Recharge que no llegaron. Además, la aplicación no tiene un mecanismo alternativo, como desglosar cualquier línea que corresponda a un Pack conocido, ni avisa cuando no pudo hacerlo. Eso la hace frágil.

**Un factor adicional para revisar.** En el #6491 escriben varias aplicaciones sobre el mismo pedido: AfterSell, UpCart, la de regalos y Recharge. Si la aplicación de bundles desglosa el pedido al crearse y otra aplicación lo modifica después, pueden pisarse entre sí.


## Qué propongo hacer

**De inmediato:**

1. Desglosar manualmente el Pack Esenciales del Hogar del #6491, reenviar el pedido al 3PL, revisar el número de seguimiento `PQ7NAW041278367L` y pedirle a CX que contacte al cliente con una fecha estimada.
2. Revisar en Recharge que las 7 suscripciones del #6491 estén activas y que el cargo inicial haya quedado registrado. Si no, los próximos envíos de este cliente pueden fallar igual.
3. Buscar otros pedidos afectados: con suscripciones de Recharge pero sin cargo o sin el tag `Subscription`, que contengan un Pack y que todavía no se hayan entregado.

**Para que no vuelva a ocurrir:**

1. Que la aplicación de bundles desglose según el SKU del Pack, con una tabla de Packs y sus componentes, sin depender de tags ni de datos de Recharge. Debería poder procesar un mismo pedido más de una vez sin duplicar nada y cubrir también los pedidos recurrentes.
2. Agregar un control antes del envío al 3PL: si un pedido contiene un SKU de Pack sin desglosar, se retiene y se avisa a Tech y a Logística.
3. Mantener un inventario de los Packs que soporta la aplicación, con sus componentes, validado contra el catálogo del 3PL.
4. Configurar una alerta para cuando un primer pedido de suscripción no reciba el cargo y los tags de Recharge dentro de un tiempo razonable, por ejemplo 15 minutos.

**Lo que haría falta para confirmar el diagnóstico.** Para confirmarlo al cien por ciento necesitaría acceso a información que no está en la tienda de desarrollo: los registros de la aplicación de bundles, la información que recibió realmente el 3PL para el #6491 y el estado del envío en Correos.
