# Simulación Natulim: Documento final entregable

Luis Grosso · 12 de noviembre de 2026

En este documento respondo a los cuatro requerimientos que recibí. El código de los requerimientos 3 y 4, junto con su documentación técnica, está en el repositorio https://github.com/GrossoLuis/natulim-challenge. Las decisiones que fui tomando durante el trabajo están registradas en el archivo `log.md` del repositorio.


##  Requerimiento 1: mensaje de Discord para Growth

 Hola, equipo. En los últimos 6 meses (del 13/05 al 12/11) tuvimos 854 suscriptores nuevos en Península y 32 en Canarias. Canarias representa el 3,6 % del total de ambas zonas: por cada suscriptor nuevo en Canarias hay aproximadamente 27 en Península.

 Para el cálculo consideré suscriptor nuevo cada primer pedido de suscripción de Recharge, y asigné la zona según la dirección de envío (Canarias: códigos postales 35 y 38). Baleares, Ceuta y Melilla no están incluidas en Península; suman 34 suscriptores más.

 Una aclaración: estos números salen de la tienda de desarrollo, que solo tiene pedidos del 14 al 21 de mayo. Para tener la cifra real de producción basta con ejecutar el mismo script sobre la tienda productiva.

Para obtener estas cifras escribí el script `scripts/subscribers_report.py`, que consulta la Admin API de Shopify. Recharge no está instalado en la tienda de desarrollo, pero los pedidos replicados conservan los tags que Recharge escribe en Shopify: `Subscription First Order` en el primer pedido de cada suscripción y `Subscription Recurring Order` en las renovaciones. Validé el resultado contra un volcado completo de los 5.497 pedidos de la tienda.


## Requerimiento 2: diagnóstico de bundles para el Lead Tech

 Santiago, te comparto mi diagnóstico sobre los errores de bundles que reportaron Logística y CX.

 **En resumen:** el desglose no falla por el tipo de Pack ni por el software del 3PL. Falla en los pedidos de suscripción que Recharge no terminó de procesar. El pedido #6491 es uno de esos casos y el #6480 no.

 **Qué revisé.** Comparé los pedidos #6491 y #6480 y, para no sacar conclusiones de solo dos casos, revisé también los 5.497 pedidos de la tienda de desarrollo.

 **Qué encontré.** En Shopify los dos Packs se comportan exactamente igual. En los 79 pedidos que tienen el Pack Esenciales del Hogar y en los 44 que tienen el Pack Limpiacristales, el Pack aparece como una sola línea y se envía al 3PL como un único código (`PEHD1` y `PLD1` en el metafield `natulim.line_items`). Además, ningún Pack tiene componentes configurados en Shopify.

 La diferencia entre los dos pedidos está en el tipo de compra:
 - El #6480 es una compra única y no pasa por Recharge.
 - El #6491 es el primer pedido de una suscripción con 7 productos suscritos, entre ellos el Pack Esenciales del Hogar con frecuencia semanal.

 Además, el procesamiento de Recharge del #6491 quedó incompleto. El pedido tiene los identificadores de las suscripciones, pero el identificador del cargo (`rc_charge_id`) está vacío y no tiene los tags `Subscription` ni `Subscription First Order`. De los 921 primeros pedidos de suscripción de la tienda, 920 tienen ambas cosas; el #6491 es el único que no. La edición manual que se hizo sobre este pedido el 10 de noviembre deja justamente ese estado.

 **Mi conclusión.** La aplicación de bundles depende de la información que Recharge escribe en el pedido para identificar y desglosar los pedidos de suscripción. Cuando esa información falta, no desglosa. El Pack llega al 3PL como un código de kit que no existe en su catálogo, el 3PL no puede armarlo y el pedido no sale completo. Por eso el cliente del #6491 no recibió su pedido. El #6480, en cambio, sigue el camino normal: se desglosa y se entrega.

 **Sobre el reporte de Logística.** Logística asoció el problema al nombre del Pack porque los casos que vio coincidían: el de Esenciales falló y el de Limpiacristales no. Pero en Shopify los dos Packs son idénticos; lo que cambia es que el pedido de Esenciales era una suscripción con el procesamiento de Recharge incompleto. Tampoco es un problema del software del 3PL: el 3PL no tiene los kits armados y solo puede preparar lo que recibe desglosado. Si recibe el código del Pack, el error ocurrió antes de llegar a ellos.

 **Sobre el reporte de CX.** CX tiene razón en que el problema está en la aplicación de bundles, pero no falla en todos los pedidos. Falla cuando depende de datos de Recharge que no llegaron, y no tiene un mecanismo alternativo ni avisa cuando no pudo desglosar un pedido.

 **Lo que propongo hacer ahora:**
 1. Desglosar manualmente el Pack del pedido #6491, reenviarlo al 3PL y pedirle a CX que contacte al cliente con una fecha estimada de entrega.
 2. Revisar en Recharge que las 7 suscripciones del #6491 estén activas y que el cargo inicial haya quedado registrado. Si no, los próximos envíos de este cliente pueden fallar de la misma manera.
 3. Buscar otros pedidos en la misma situación: con suscripciones de Recharge pero sin cargo o sin tags, que contengan un Pack y que todavía no se hayan entregado.

 **Lo que propongo para que no vuelva a ocurrir:**
 1. Que la aplicación de bundles desglose según el SKU del Pack, a partir de una tabla de Packs y sus componentes, sin depender de los tags ni de los datos de Recharge. Debería poder procesar un mismo pedido más de una vez sin duplicar nada y cubrir también los pedidos recurrentes.
 2. Agregar un control antes del envío al 3PL: si un pedido contiene un SKU de Pack sin desglosar, se retiene y se avisa a Tech y a Logística.
 3. Mantener un inventario de los Packs que soporta la aplicación, con sus componentes, validado contra el catálogo del 3PL.
 4. Configurar una alerta cuando un primer pedido de suscripción no reciba el cargo y los tags de Recharge en un tiempo razonable, por ejemplo 15 minutos.
 5. Revisar el orden en que escriben sobre el pedido las distintas aplicaciones (Recharge, AfterSell, UpCart y la de regalos), para descartar que se pisen entre sí durante el desglose.

 El detalle completo del análisis está en `docs/diagnostico_pedidos.md`. Para confirmarlo al cien por ciento necesitaría revisar los registros de la aplicación de bundles y de Recharge, que no están disponibles en la tienda de desarrollo.


## Requerimiento 3: sincronización de pedidos

### ¿Lo ponemos ya en producción?

Sí. La aplicación está terminada y probada. Además de los tests automáticos, la probé con pedidos reales en la tienda de desarrollo y funcionó en todos los casos:

- Al crear un pedido, se guardó en la base de datos con todas sus líneas.
- Al quitar un producto, la base reflejó el cambio y el total se actualizó de 72 a 33 euros.
- Al cancelar el pedido, la cancelación quedó registrada.

También manejó correctamente dos situaciones que ocurren en la práctica: notificaciones de Shopify que llegan casi al mismo tiempo y notificaciones que llegan en un orden distinto al real.

Lo único que hace falta para activarla es ejecutarla en un servidor en lugar de en mi equipo. Durante la prueba funcionó en mi computadora a través de un túnel temporal, lo cual sirve para validar pero no para operar en producción. No hay que desarrollar nada nuevo: son tareas de puesta en marcha que se pueden hacer en el mismo día.

### ¿Cómo lo ponemos en producción?

1. Crear la aplicación en el Dev Dashboard para la tienda Plus, solo con los permisos necesarios (`read_orders`, `write_orders` y `read_all_orders`), solicitar el acceso a los datos protegidos de clientes (nombre, email y dirección) e instalarla. En la tienda de desarrollo usé una aplicación compartida con más permisos de los necesarios, lo cual no es recomendable en producción.
2. Desplegar el servicio en un servidor con HTTPS y disco persistente, por ejemplo una máquina virtual pequeña o un servicio como Railway o Fly.io con volumen. El disco persistente es necesario porque la base SQLite tiene que conservarse entre reinicios.
3. Cargar las variables de entorno en el gestor de secretos del proveedor. Las credenciales nunca van en el repositorio.
4. Fijar `SYNC_START_AT` en el momento exacto de la puesta en marcha. Este valor es el que garantiza lo acordado con el área solicitante: no se sincronizan los pedidos anteriores.
5. Registrar los webhooks con la URL definitiva (`register_webhooks.py`) y verificarlos (`list_webhooks.py`).
6. Programar la reconciliación (`reconcile.py`) cada 15 minutos. Shopify no garantiza que todas sus notificaciones lleguen, y este proceso recupera cualquier pedido que se haya perdido.
7. Hacer una prueba con un pedido real: crearlo, editarlo, cancelarlo, verificar que todo quede registrado en la base y luego eliminarlo.
8. Configurar alertas ante errores del servicio y ante fallos de la reconciliación, y programar un respaldo diario de la base de datos. Si en el futuro crece mucho el volumen de pedidos o hace falta más de un servidor, recomiendo migrar de SQLite a Postgres.


## Requerimiento 4: marcado de pedidos con cambio de dirección a Canarias

### ¿Lo ponemos ya en producción?

Sí, junto con el requerimiento 3, porque comparten el mismo servicio. No necesita infraestructura propia: no usa base de datos y la información que necesita la guarda en el propio pedido. Lo probé en la tienda de desarrollo con estos resultados:

- Al cambiar la dirección de un pedido de Madrid a Las Palmas, se agregó el tag `cambio_a_pedido_para_canarias` una sola vez.
- Un pedido creado directamente con dirección en Tenerife no recibió el tag, que es lo correcto, porque no hubo un cambio de dirección.

Antes de activarlo, conviene tener en cuenta tres puntos:

- **Pedidos anteriores a la puesta en marcha.** Para detectar un cambio de dirección, el servicio necesita conocer la dirección anterior, y la registra cuando se crea el pedido. Los pedidos que ya existían no tienen ese registro, así que la primera vez que se modifiquen solo se guardará su dirección y no se agregará el tag. Para evitarlo, propongo ejecutar al momento de la puesta en marcha un script que registre la dirección actual de los pedidos abiertos.
- **Cambios hechos por otras aplicaciones.** Shopify no informa de forma confiable quién hizo el cambio. Si una aplicación modifica la dirección (por ejemplo, un validador de direcciones), el pedido también recibirá el tag. Si fuera necesario distinguirlo, se puede consultar el historial de eventos del pedido.
- **Comunicación a los equipos.** Hay que avisar a CX y a Logística del nuevo tag y de lo que significa: que el pedido tuvo un cambio de dirección a Canarias. El tag se mantiene aunque después la dirección vuelva a la Península.

### ¿Cómo lo ponemos en producción?

Los pasos son los mismos del requerimiento 3, porque es el mismo servicio. Además:

1. Verificar que la aplicación tenga el permiso `write_orders`, necesario para agregar tags y guardar datos en los pedidos.
2. Opcionalmente, crear en el admin de Shopify la definición del metafield `natulim.shipping_address_hash`, para que se vea con un nombre descriptivo y no se elimine por error.
3. Ejecutar el registro inicial de direcciones en los pedidos abiertos.
4. Hacer una prueba real: cambiar a Canarias la dirección de un pedido de prueba y verificar que el tag aparezca una sola vez.
5. Comunicar el nuevo tag a CX y a Logística.


## Alcance

### Qué incluí

Para el requerimiento 1, calculé la cifra con un script reproducible y dejé explícitos los criterios de "suscriptor nuevo" y de cada zona.

Para el requerimiento 2, escribí un script para inspeccionar pedidos, analicé los dos pedidos reportados y el total de pedidos de la tienda, y redacté un diagnóstico con la evidencia y un plan de acción inmediato y de fondo.

Para el requerimiento 3, desarrollé un servicio que recibe las notificaciones de Shopify, verifica su autenticidad y sincroniza los pedidos en SQLite. Cubre la creación, las ediciones de productos, la cancelación y el borrado, y tolera notificaciones duplicadas o desordenadas. Incluí además un proceso de reconciliación que recupera los pedidos cuya notificación se haya perdido. Lo validé con tests automáticos y con pruebas en la tienda de desarrollo.

Para el requerimiento 4, desarrollé el marcado con el tag a partir de la dirección guardada en el propio pedido, protegido contra repeticiones y contra notificaciones atrasadas. También lo validé con tests y con pruebas reales.

Por último, documenté todo: el `README.md` explica cómo instalar y ejecutar el proyecto desde cero en Windows, macOS o Linux; `docs/arquitectura.md` describe el diseño; y `log.md` registra cada decisión.

### Qué dejé fuera y por qué

**Servidor de producción, tareas programadas y monitoreo.** El enunciado permite ejecutar la solución en local o en un servicio gratuito, y por la urgencia prioricé que la lógica estuviera completa y probada. En la realidad lo desplegaría en un servidor con disco persistente, programaría la reconciliación con el cron del proveedor y configuraría alertas sobre los errores del servicio.

**Migración a Postgres.** Para un solo servidor y el volumen actual, SQLite es suficiente y es lo que se pidió. Si en el futuro hiciera falta más de un servidor o el volumen creciera mucho, migraría a Postgres. Las consultas son SQL estándar, por lo que el cambio sería acotado.

**Procesamiento en segundo plano.** Shopify espera una respuesta en menos de 5 segundos, y en las pruebas el servicio respondió en un máximo de 2,2 segundos, así que hoy no es necesario. Con más volumen, el servicio respondería de inmediato y procesaría las notificaciones desde una cola. El código ya está preparado para eso, porque procesar dos veces la misma notificación no genera errores ni duplicados.

**Verificar que el cambio de dirección lo hizo alguien de CX (requerimiento 4).** Shopify no envía esa información de forma confiable en sus notificaciones. Si se necesitara, consultaría el historial de eventos del pedido para identificar quién hizo el cambio.

**Registro inicial de direcciones en pedidos existentes (requerimiento 4).** Es un paso de la puesta en marcha más que de la lógica. Lo resolvería con un script que se ejecuta una sola vez sobre los pedidos abiertos.

**Confirmar el diagnóstico del requerimiento 2 con los registros de las aplicaciones.** La aplicación de bundles y Recharge no están instaladas en la tienda de desarrollo. En la realidad revisaría los registros de la aplicación de bundles para el pedido #6491 y consultaría en Recharge el estado de su cargo.

**Cifras del requerimiento 1 con datos de producción.** La tienda de desarrollo solo tiene una semana de pedidos de mayo. En la realidad ejecutaría el mismo script sobre la tienda productiva.

### Ajustes respecto del plan inicial

Durante el trabajo encontré cuatro situaciones que me llevaron a ajustar el plan. Todas están justificadas en `log.md`:

- La aplicación de la tienda de desarrollo es compartida con otra persona que ya tenía webhooks registrados. Para no modificar los suyos, marqué los míos con un identificador en la URL y el script de registro solo gestiona esos.
- La reconciliación parte de la fecha de su última ejecución exitosa. Si partiera del último pedido sincronizado, un pedido cuya notificación se perdió podría no recuperarse nunca.
- Guardo la cantidad vigente de cada línea, además de la original. Así, cuando se quita un producto con la opción Editar, la base lo refleja.
- Junto con la dirección, el pedido guarda la fecha de la última notificación procesada, para descartar notificaciones que lleguen atrasadas.
