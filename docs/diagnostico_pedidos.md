# Diagnóstico de pedidos #6491 y #6480 (requerimiento 2)

Fuentes:
- `python scripts/inspect_orders.py 6491 6480`;
- un análisis del total de pedidos de la tienda dev: 5.497 pedidos replicados de producción, del 14 al 21 de mayo de 2026;
- el detalle del evento de edición de #6491 en el admin.

## Comparativa

| | #6491 (CX: **no recibido**) | #6480 (CX: **recibido**) |
|---|---|---|
| Pack | Pack Esenciales del Hogar (SKU 300246, "2 de cada") | Pack Limpiacristales (SKU 300259, "2") |
| Otras líneas | 11 líneas más: 4 productos, Pack Lavavajillas a Mano y 6 regalos (`_gwp: aniv_gift_1..5`) | Pack Desengrasante y Eco Pastillas Lavavajillas |
| ¿Pack desglosado en Shopify? | No: el Pack es una única línea | No: el Pack es una única línea |
| Envío al 3PL (`natulim.line_items`) | `...-PEHD1-...`: el Pack va como un único código | `PLD1-PDD1-VD1`: el Pack va como un único código |
| Tipo de compra | **Primer pedido de suscripción Recharge** (pago en Shopify Checkout, 7 suscripciones; el Pack se compró con frecuencia "1 vez por semana") | **Compra única** (`_recharge-subscription-upsell: none`, sin atributos `rc_*`) |
| `rc_charge_id` | **Vacío** | No aplica |
| Tags de Recharge | **Ninguno** (faltan `Subscription` y `Subscription First Order`) | No aplica |
| Edición manual | 2026-11-10: se modificaron los atributos del pedido (`rc_charge_id`, `rc_address_id`, `rc_subscription_ids`, `rc_payment_transaction_id` y los de tracking web) | Ninguna |
| Otras apps en el pedido | Post-purchase (AfterSell), UpCart, regalos GWP | Ninguna |
| Dirección | Sa Pobla, Baleares (07420) | Madrid (28036) |
| Courier / tracking | PQ / `PQ7NAW041278367L` | PQ / `PQ7NAW041275177S` |

## Lo que dicen los datos del total de pedidos

1. **El tipo de Pack no es la variable.**
   - En el 100 % de los pedidos con Pack Esenciales del Hogar (79) y con Pack Limpiacristales (44), el Pack figura en Shopify como una única línea y como un único código en `natulim.line_items`.
   - Los dos Packs se compran tanto en suscripción como en compra única.
   - Ningún producto Pack tiene componentes nativos configurados.
   - En Shopify, los dos Packs se comportan igual. Si en el 3PL uno llega desglosado y el otro no, la diferencia la introduce otra cosa.
2. **El circuito normal de Recharge en los primeros pedidos es consistente.** De los 921 primeros pedidos de suscripción pagados en Shopify Checkout, **920 tienen `rc_charge_id` y el tag `Subscription First Order`**. El único que no tiene ninguna de las dos cosas es #6491.
3. **#6491 tiene la "huella" de una suscripción sin el "cierre" de Recharge.** Tiene `rc_subscription_ids` (el cliente se suscribió), pero no tiene `rc_charge_id` ni tags: Recharge no terminó de registrar el pedido. La edición manual de los atributos `rc_*` del 10/11 reproduce justamente ese estado.
4. **#6480 no pasa por Recharge** en ningún momento.

## Conclusiones

**Qué está pasando realmente.** El desglose de Packs falla en los pedidos de suscripción que Recharge no terminó de procesar, no en un Pack concreto. La app de bundles distingue o dispara el desglose de los pedidos de suscripción a partir de lo que Recharge escribe en el pedido: el `rc_charge_id`, los tags `Subscription*` o el evento de Recharge asociado al cargo. Cuando eso falta, como en #6491, la app no desglosa:
- el Pack llega al 3PL como un SKU de kit que no existe en su catálogo;
- el 3PL no puede armarlo;
- el pedido no se completa y el cliente no lo recibe.

#6480 es una compra única, entra por el camino estándar de la app, se desglosa y se recibe.

**Por qué Logística se equivoca en la causa.** Generaliza por nombre de Pack a partir de los casos que vio ("Esenciales no, Limpiacristales sí"). Pero los dos Packs se comportan igual en Shopify. La coincidencia viene de que el caso de Esenciales que falló era una suscripción con Recharge incompleto. Tampoco es un fallo del software del 3PL: el 3PL no tiene los kits y solo puede armar lo que recibe desglosado. Si recibe el SKU del Pack, el error está antes.

**Qué tiene de cierto CX.** El problema sí está en la integración de la app de bundles, pero no falla siempre: falla cuando depende de datos de Recharge que no llegaron. La app no tiene un comportamiento de respaldo, por ejemplo desglosar igual cualquier línea que sea un Pack conocido, ni avisa del fallo. Eso la hace frágil.

**Factores que agravan el problema y hay que revisar.** #6491 tiene muchas apps escribiendo sobre el mismo pedido: post-purchase de AfterSell, UpCart, regalos GWP y Recharge. Si la app de bundles desglosa en `orders/create` y otra app edita el pedido después, pueden darse condiciones de carrera.

## Qué se debe hacer

**Inmediato**
1. **#6491:**
   - desglosar a mano el Pack Esenciales del Hogar en sus componentes y reenviar el pedido al 3PL;
   - revisar el tracking `PQ7NAW041278367L` en Correos;
   - que CX contacte al cliente con una fecha estimada.
2. **Revisar en Recharge:**
   - si las 7 suscripciones de #6491 están activas;
   - si el cargo inicial quedó registrado.

   Sin el cargo, los envíos recurrentes de este cliente pueden fallar igual.
3. **Buscar más pedidos afectados:** pedidos con `rc_subscription_ids` y sin `rc_charge_id`, o sin tag `Subscription`, que contengan un Pack y estén sin entregar.

**De fondo**
1. **En la app de bundles:**
   - desglosar por **SKU del Pack**, con una tabla Pack → componentes, sin depender de tags ni de datos de Recharge;
   - ser idempotente;
   - procesar también los pedidos recurrentes de Recharge.
2. **Alerta antes del 3PL:** si un pedido sale con un SKU de Pack sin desglosar, se bloquea y se avisa a Tech y Logística.
3. **Inventario de Packs soportados** por la app, con sus componentes, revisado contra el catálogo del 3PL.
4. **Monitoreo de Recharge:** alertar si un primer pedido de suscripción no recibe `rc_charge_id` o el tag `Subscription First Order` en un plazo razonable (ej. 15 minutos).
