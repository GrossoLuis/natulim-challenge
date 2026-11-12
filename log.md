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
