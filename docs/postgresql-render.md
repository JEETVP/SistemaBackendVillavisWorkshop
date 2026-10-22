# PostgreSQL y Render

El runtime utiliza Psycopg 3 y pools de conexiones PostgreSQL. No acepta rutas de archivos SQLite. Las consultas usan par?metros PostgreSQL, metadatos `information_schema`, transacciones y bloqueos transaccionales para las operaciones de lectura/validaci?n/escritura. No se ejecuta ninguna importaci?n de datos antiguos.

## Render

`render.yaml` crea un web service Docker y Render Postgres 17. El Dockerfile inicia `scripts/render_start.py`, que crea los esquemas `identity`, `customers` y `workshop` y supervisa los cuatro servicios. Solo el gateway escucha en `0.0.0.0:$PORT`; los otros tres usan loopback. Si uno termina, el supervisor sale para que Render reinicie el conjunto.

Configurar `APP_ORIGIN` con la URL HTTPS exacta de Cloudflare Pages. El Blueprint proporciona `DATABASE_URL`, genera `INTERNAL_SERVICE_TOKEN` y `BACKEND_PROXY_TOKEN`, y establece el health check `/health`. Las Pages Functions deben tener `BACKEND_ORIGIN` y el mismo `BACKEND_PROXY_TOKEN` como secreto. En Render solo se publica `/api/*` a trav?s de ese proxy autenticado y `/health` para los monitores. Los endpoints nativos sin `/api` se conservan para desarrollo local, pero no est?n publicados en Render.

La clave de firma RSA vive en la tabla `identity.signing_keys` de PostgreSQL. No depende de un disco persistente ni se vuelve a generar en cada despliegue. Proteger los respaldos de la base: incluyen la clave de firma y los verificadores de contrase?a.

## Local

1. Instalar `requirements.txt` y ejecutar `python scripts/create_env.py`.
2. Arrancar PostgreSQL: `docker compose up -d postgres`, o una instalaci?n local con las tres bases y roles de `scripts/postgres-init.sh`.
3. Ejecutar `.venv/Scripts/python.exe scripts/dev.py` y arrancar Vite en el frontend.

Se utilizan `IDENTITY_DATABASE_URL`, `CUSTOMERS_DATABASE_URL` y `WORKSHOP_DATABASE_URL`. El Docker Compose local crea tres bases separadas; Render usa tres esquemas del mismo servidor/base administrada. Los contratos HTTP son iguales en ambos casos. Las cuentas nuevas empiezan vac?as y deben registrarse de nuevo.

La instancia de desarrollo PostgreSQL nativa preparada en este equipo se encuentra en `data/postgresql-dev`; sus binarios est?n en `data/postgresql-tools`. Para volver a iniciarla despu?s de reiniciar Windows, desde la ra?z del backend:

```powershell
.\data\postgresql-tools\bin\pg_ctl.exe -D .\data\postgresql-dev -l .\data\postgresql-dev.log -o "-h 127.0.0.1 -p 5432" -w start
```

No iniciar simult?neamente esa instancia y Docker en el mismo puerto. Las credenciales de desarrollo est?n en `.env`, no en Git. Esta instalaci?n local no es necesaria para desplegar en Render.

## Pruebas y CI

`TEST_DATABASE_URL` debe apuntar a una base PostgreSQL de prueba. La suite crea esquemas con prefijo UUID y los elimina al terminar; no usa los esquemas de la aplicaci?n. CI proporciona PostgreSQL 17 real y prueba transacciones, sesiones, cotizaci?n, autorizaci?n, avances, concurrencia y aislamiento. Ejecutar `python -m unittest discover -s tests -v`.

El workflow espera los checks correctos antes de que Render publique la rama `main`. Tambi?n construye la imagen y comprueba el arranque tipo Render con PostgreSQL. El flujo anterior de despliegue cruzado a Azure fue retirado de este repositorio. La configuraci?n detallada del frontend est? en `TallerPlusWEB/docs/render-cloudflare.md`.
