# Natulim: servicio de webhooks de pedidos

Este servicio, escrito en Python, recibe las notificaciones (webhooks) de pedidos de Shopify y resuelve dos requerimientos:

- **Sincronización de pedidos (requerimiento 3).** Mantiene en una base SQLite una copia de cada pedido nuevo y de sus líneas, y la actualiza cuando el pedido se edita, se cancela o se elimina en Shopify.
- **Marcado de Canarias (requerimiento 4).** Cuando se edita la dirección de envío de un pedido y la nueva dirección es de Canarias, agrega al pedido el tag `cambio_a_pedido_para_canarias`. No usa base de datos.

El repositorio incluye también los scripts de análisis que usé para los requerimientos 1 (suscriptores nuevos por zona) y 2 (diagnóstico de pedidos con Packs).

```
Shopify --> túnel HTTPS --> FastAPI /webhooks --> dispatcher --+--> order_sync   --> SQLite
                            (verifica la firma)                +--> canarias_tag --> Admin API (tag y metafield)
```

El diseño está explicado en detalle en [docs/arquitectura.md](docs/arquitectura.md).


## 1. Requisitos

- Python 3.11 o superior.
- git.
- Un túnel HTTPS hacia `localhost` para que Shopify pueda enviar las notificaciones al equipo local. Sirve [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/), que no requiere cuenta, o [ngrok](https://ngrok.com/download).
- Una tienda Shopify con una aplicación propia instalada (ver el punto 2).


## 2. Crear la aplicación en Shopify

Las aplicaciones propias se crean en el Dev Dashboard de Shopify:

1. Entrar a [dev.shopify.com](https://dev.shopify.com), ir a *Apps* y elegir *Create app*.
2. En la versión de la aplicación, configurar estos permisos (scopes):
   - `read_orders`, para leer pedidos y recibir sus notificaciones;
   - `write_orders`, para agregar tags y guardar metafields en los pedidos;
   - `read_all_orders`, para consultar pedidos de más de 60 días (lo necesitan los scripts de análisis).
3. Habilitar el acceso a los datos protegidos de clientes (*protected customer data*), con los campos de nombre, email y dirección. Las notificaciones de pedidos incluyen esos datos. En una tienda de desarrollo basta con seleccionarlos; en una tienda de producción hay que completar el formulario de uso de datos.
4. Instalar la aplicación en la tienda.
5. Copiar el Client ID y el Client secret desde la configuración (*Settings*) de la aplicación.

El servicio usa esas dos credenciales para obtener el token de acceso a la Admin API y lo renueva automáticamente antes de que venza (dura 24 horas). Este mecanismo, llamado *client credentials grant*, solo funciona si la aplicación y la tienda pertenecen a la misma organización de Shopify. Si se cuenta con un token fijo (empieza con `shpat_`), también se puede usar, con la variable `SHOPIFY_ADMIN_TOKEN`.


## 3. Instalación

Clonar el repositorio:

```bash
git clone https://github.com/GrossoLuis/natulim-challenge.git
cd natulim-challenge
```

Crear el entorno virtual, instalar las dependencias y crear el archivo de configuración.

En macOS o Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

En Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### Variables de configuración (`.env`)

Obligatorias:

- `SHOPIFY_SHOP_DOMAIN`: dominio de la tienda, con el formato `xxx.myshopify.com` y sin `https://`.
- `SHOPIFY_CLIENT_ID` y `SHOPIFY_CLIENT_SECRET`: credenciales de la aplicación del Dev Dashboard. Como alternativa, se puede usar un token fijo en `SHOPIFY_ADMIN_TOKEN`.
- `SYNC_START_AT`: fecha y hora de inicio en formato ISO 8601 UTC, por ejemplo `2026-11-12T00:00:00Z`. Los pedidos creados antes de esa fecha no se sincronizan.

Necesarias para registrar los webhooks:

- `PUBLIC_BASE_URL`: URL pública del túnel o del servidor, sin barra final.
- `WEBHOOK_OWNER`: un identificador de esta instalación, por ejemplo el nombre de usuario. Se agrega a la URL de los webhooks (`?owner=...`) para que el script de registro solo modifique las suscripciones propias, aunque la aplicación de Shopify se comparta con otras personas.

Opcionales:

- `SHOPIFY_API_VERSION`: versión de la Admin API. Por defecto, `2026-10`.
- `SHOPIFY_WEBHOOK_SECRET`: secreto para verificar la firma de las notificaciones. Si está vacío, se usa `SHOPIFY_CLIENT_SECRET`, que es el que usa Shopify en las aplicaciones del Dev Dashboard.
- `DATABASE_PATH`: ruta de la base SQLite. Por defecto, `data/orders.db`.
- `CANARIAS_TAG`: tag que se agrega a los pedidos. Por defecto, `cambio_a_pedido_para_canarias`.
- `ADDRESS_METAFIELD_NAMESPACE` y `ADDRESS_METAFIELD_KEY`: metafield donde se guarda la dirección anterior de cada pedido. Por defecto, `natulim.shipping_address_hash`.

El archivo `.env` está excluido de git y nunca debe subirse al repositorio.


## 4. Ejecución

Con el entorno virtual activado y desde la carpeta del repositorio:

1. Verificar las credenciales y los permisos:
   ```bash
   python scripts/check_connection.py
   ```
2. Iniciar el servicio:
   ```bash
   uvicorn app.main:app --port 8000
   ```
3. En otra terminal, iniciar el túnel, copiar la URL `https://...` que muestra y pegarla en la variable `PUBLIC_BASE_URL` del archivo `.env`:
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
   También se puede usar `ngrok http 8000`.
4. Registrar los webhooks:
   ```bash
   python scripts/register_webhooks.py
   ```
5. Verificar que hayan quedado registrados:
   ```bash
   python scripts/list_webhooks.py
   ```

Se registran cuatro notificaciones (`ORDERS_CREATE`, `ORDERS_UPDATED`, `ORDERS_CANCELLED` y `ORDERS_DELETE`), todas dirigidas a `POST /webhooks`. El servicio también responde en `GET /health` con `{"status": "ok"}`.

Algunas aclaraciones:

- Los túneles gratuitos de cloudflared cambian de URL cada vez que se inician. Si eso ocurre, hay que actualizar `PUBLIC_BASE_URL` y volver a ejecutar `register_webhooks.py`, que actualiza las suscripciones con la URL nueva.
- Al terminar las pruebas, conviene ejecutar `python scripts/register_webhooks.py --delete` para eliminar las suscripciones propias y no dejar notificaciones dirigidas a un túnel apagado.


## 5. Cómo probar cada requerimiento

Para consultar la base de datos se puede usar el programa `sqlite3` o directamente Python:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/orders.db'); print(c.execute('SELECT id, name, updated_at, financial_status, total_price, cancelled_at, tags FROM orders').fetchall())"
python -c "import sqlite3; c=sqlite3.connect('data/orders.db'); print(c.execute('SELECT order_id, sku, title, quantity, current_quantity FROM order_lines').fetchall())"
```

### Requerimiento 3: sincronización

1. En el admin de Shopify, ir a *Pedidos* y elegir *Crear pedido*. Agregar dos productos, asignar un cliente con dirección y elegir *Marcar como pagado*. El pedido se crea en ese momento; mientras es un borrador (`#D...`), Shopify no envía notificaciones.
2. Verificar que el pedido y sus dos líneas aparezcan en las tablas `orders` y `order_lines`.
3. Editar el pedido y quitar un producto. La línea quitada queda con `current_quantity = 0` y el total se actualiza.
4. Cancelar el pedido. Se completa el campo `cancelled_at`.
5. Si se elimina el pedido, queda marcado con `deleted = 1`, sin borrarse de la base, para conservar el historial.

### Requerimiento 4: marcado de Canarias

1. Crear un pedido con dirección en Madrid (código postal 28001). Verificar que no tenga el tag y que tenga el metafield `natulim.shipping_address_hash`.
2. Editar la dirección de envío a Las Palmas de Gran Canaria, código postal 35001, provincia Las Palmas. Al recargar la página aparece el tag `cambio_a_pedido_para_canarias`.
3. Revisar el registro del servicio: debe aparecer una sola vez "tag agregado", y la notificación siguiente debe indicar "sin cambios de dirección".
4. Crear un pedido directamente con dirección en Tenerife (código postal 38001). No debe recibir el tag.


## 6. Scripts auxiliares

- `scripts/check_connection.py`: verifica las credenciales y muestra los permisos concedidos a la aplicación.
- `scripts/register_webhooks.py`: crea o actualiza las suscripciones propias. Con `--delete`, las elimina.
- `scripts/list_webhooks.py`: lista las suscripciones de la aplicación e indica cuáles son propias.
- `scripts/reconcile.py`: consulta por API los pedidos modificados desde la última reconciliación (con 10 minutos de margen) y los sincroniza. Recupera los pedidos cuya notificación se haya perdido y está pensado para ejecutarse como tarea programada. Con `--since` se puede indicar una fecha de inicio.
- `scripts/subscribers_report.py`: calcula los suscriptores nuevos (tag de Recharge `Subscription First Order`) por zona: Península, Canarias y Baleares, Ceuta y Melilla. Con `--months` se puede cambiar el período, que por defecto es de 6 meses.
- `scripts/inspect_orders.py`: muestra un resumen comparativo de los pedidos indicados (por ejemplo, `6491 6480`) y guarda sus datos completos en la carpeta `inspect_output/`.


## 7. Tests

```bash
pytest -v
```

Los tests no usan el archivo `.env` ni se conectan a Shopify: trabajan con una configuración ficticia, una base SQLite temporal y una simulación de la API.


## 8. Estructura del repositorio

- `app/main.py`: servicio FastAPI, con el endpoint `POST /webhooks` (verifica la firma) y `GET /health`.
- `app/config.py`: carga y validación de la configuración.
- `app/security.py`: verificación de la firma HMAC de las notificaciones.
- `app/shopify_client.py`: cliente de la Admin API de Shopify (GraphQL), con renovación del token y reintentos.
- `app/dispatcher.py`: envía cada notificación a los procesos que corresponden y aísla sus errores.
- `app/order_sync/`: requerimiento 3 (esquema de la base, conversión de datos y guardado de pedidos).
- `app/canarias_tag/`: requerimiento 4 (clasificación de direcciones y lógica del tag).
- `scripts/`: registro de webhooks, reconciliación y scripts de análisis.
- `tests/`: tests de la verificación de firma, la sincronización y el marcado.
- `docs/`: arquitectura, diagnóstico del requerimiento 2 y documento de entrega.
- `data/`: carpeta donde se crea la base `orders.db` (excluida de git).
- `log.md`: registro cronológico de las decisiones que tomé durante el trabajo.


## 9. Decisiones y limitaciones

El razonamiento completo está en [log.md](log.md) y en [docs/arquitectura.md](docs/arquitectura.md). En resumen:

- Usé webhooks para que los pedidos se sincronicen casi en tiempo real, y agregué la reconciliación porque Shopify no garantiza la entrega de todas las notificaciones.
- El servicio tolera notificaciones repetidas o desordenadas: registra cada notificación procesada, compara fechas de actualización y reemplaza todas las líneas del pedido en cada actualización.
- Los pedidos creados antes de la puesta en marcha no se sincronizan (`SYNC_START_AT`), tal como se acordó.
- Para el requerimiento 4, la dirección anterior se guarda en un metafield del propio pedido. Así se puede detectar el cambio sin usar una base de datos.
- Limitaciones del requerimiento 4:
  - los pedidos anteriores a la puesta en marcha no tienen dirección registrada, así que su primer cambio solo la registra y no agrega el tag;
  - no se verifica que el cambio lo haya hecho alguien de CX;
  - el tag no se quita si la dirección deja de ser de Canarias.
- SQLite es suficiente para un solo servidor y el volumen actual. Si se necesitara más de un servidor o el volumen creciera mucho, recomiendo migrar a Postgres.
