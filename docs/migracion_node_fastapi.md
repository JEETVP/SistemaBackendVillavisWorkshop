> Actualización del 20 de octubre de 2026: los módulos solicitados de taller y conductor ya tienen persistencia y sincronización en SQL. Consultar [estado de la integración web](sincronizacion_web_sql.md). Las limitaciones de fases anteriores descritas a continuación son históricas.

# Migracion de Node a FastAPI: primera fase

TallerPlusWEB ya usa FastAPI para todas las operaciones que antes atendia `server/app.mjs`: registro de taller/encargado, login, restauracion de sesion, cierre de sesion, recepcion de cliente/vehiculo/orden, renovacion de enlace, validacion/activacion y directorio. Se conserva el contrato `/api`, los nombres de campos y las respuestas que consume React.

Los datos se escriben en las tablas canonicas `users`, `customers`, `vehicles`, `workshops` y `work_orders` de los tres microservicios. Los campos adicionales de vehiculos y ordenes se conservan como metadatos en esos mismos registros. No se crea otra base de negocio para la web.

## Configuracion y arranque local

En el backend:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
python scripts/create_env.py
.\.venv\Scripts\python.exe scripts/dev.py
```

En otra terminal, desde TallerPlusWEB:

```powershell
npm.cmd run dev
```

En Linux/macOS, usar `.venv/bin/python` y `npm`. El lanzador del backend inicia identidad (8003), clientes (8001), taller (8002) y gateway (8000), vinculados a loopback. Ctrl+C detiene los cuatro. No incluye autoreload. `npm run dev` inicia solamente Vite; la API Node queda disponible exclusivamente como referencia con `npm run server:legacy`.

- Backend: `.env`, generado con una clave interna aleatoria. Plantilla versionada: `.env.example`.
- Frontend: `.env` con `FASTAPI_URL=http://127.0.0.1:8000` y `VITE_PORT=5173`; su plantilla tambien esta versionada.
- Navegador: abrir `http://localhost:5173`. `APP_ORIGIN` debe coincidir exactamente con ese origen. Si se cambia host/puerto de Vite, actualizar ambos proyectos.
- El frontend usa el proxy `/api` en desarrollo y preview. En produccion se debe configurar el proxy inverso del mismo origen hacia el gateway, junto con el fallback a `index.html` para `/registro/activar`.
- Solo la configuracion publica del proxy pertenece al frontend. `INTERNAL_SERVICE_TOKEN`, contrasenas y claves privadas permanecen en el backend.

| Variable del backend | Funcion |
| --- | --- |
| `APP_ENV` | `development` local; `production` exige origen HTTPS |
| `APP_ORIGIN` | Origen exacto permitido en escrituras y base para enlaces de activacion |
| `API_HOST`, `API_PORT` | Puerto del gateway local; el lanzador mantiene los servicios internos en loopback |
| `IDENTITY_SERVICE_URL`, `CUSTOMERS_SERVICE_URL`, `WORKSHOP_SERVICE_URL` | URLs internas; Docker Compose las reemplaza por sus nombres de servicio |
| `INTERNAL_SERVICE_TOKEN` | Clave compartida para las nuevas rutas internas; no se expone al navegador |
| `IDENTITY_DB_PATH`, `CUSTOMERS_DB_PATH`, `WORKSHOP_DB_PATH` | Archivos SQLite persistentes |
| `IDENTITY_PRIVATE_KEY_PATH` | Clave privada RSA persistente |
| `JWT_TTL_SECONDS` | Duracion de la sesion/cookie; 43200 en el `.env` local |
| `ACTIVATION_TTL_SECONDS` | Vigencia de activacion; 86400 segundos |
| `IDENTITY_BOOTSTRAP_ADMIN_*` | Administrador nativo opcional; deshabilitado por defecto |

Los `.env` reales estan excluidos de Git; `create_env.py` nunca reemplaza uno existente. Compose usa el mismo archivo y expone solamente el gateway. El despliegue Docker no se ha ejecutado en este equipo.

## Seguridad y coherencia del flujo

La web recibe una cookie HttpOnly `tallerplus_session`, SameSite=Lax, limitada a `/api` y Secure con origen HTTPS. El JWT no aparece en el JSON ni se guarda como credencial en localStorage. Acceso y restauracion se comprueban siempre con FastAPI; se retiro el acceso alternativo mediante verificadores locales antiguos. Los perfiles cacheados siguen sirviendo a los paneles, pero no abren una sesion del servidor.

Identidad valida firma, expiracion, estado activo y revocacion. Se comprueba `Origin` en escrituras, JSON, limite real de 1.5 MB y 30 intentos por IP/ruta publica cada 15 minutos en cada proceso gateway. Los errores web no devuelven cuerpos de validacion con contrasenas ni tokens. En varias replicas se necesitara un limitador compartido.

La cuenta del encargado queda vinculada a un taller; la recepcion y sus snapshots solo acceden a ese taller. Un cliente ve sus propios vehiculos y ordenes. Otro taller no puede renovar su activacion ni acceder a sus datos privados a traves de estas rutas. Los permisos globales de la API Bearer nativa no se han convertido todavia en membresias completas por taller: el gateway deniega sus rutas autenticadas a las cuentas de taller vinculadas, incluso si extraen su propio token. Esas cuentas usan las rutas `/api` con alcance por taller; administradores nativos anteriores conservan sus permisos operativos.

Recepcion crea primero una identidad provisional. Clientes registra cliente y vehiculo en una transaccion; taller registra la orden en Diagnostico. Solo despues se publica la cuenta pendiente y su activacion. Si falla una llamada, el gateway compensa los registros provisionados. Si identidad ya confirmo o no responde, evita borrar recursos potencialmente activos y registra la necesidad de reconciliacion. Este mecanismo no sustituye una transaccion distribuida ni una cola duradera de recuperacion ante caidas del gateway.

Los enlaces guardan un hash SHA-256, duran 24 horas, se reemplazan al renovar y solo se consumen una vez. La activacion comprueba vigencia y estado de nuevo bajo bloqueo de escritura SQLite despues de derivar la contrasena; dos solicitudes concurrentes no consumen el mismo enlace.

## Importar la base anterior de Node

Detener los servicios de destino y dejar de escribir en la API Node antes de la importacion final. El comando lee una instantanea de la fuente en modo de solo lectura.

```powershell
.\.venv\Scripts\python.exe scripts/migrate_node_sqlite.py --source ..\TallerPlusWEB\server\data\tallerplus-dev.sqlite
.\.venv\Scripts\python.exe scripts/migrate_node_sqlite.py --source ..\TallerPlusWEB\server\data\tallerplus-dev.sqlite --apply
```

La primera llamada solo informa cantidades. `--apply` usa `data/identity.db`, `data/customers.db` y `data/workshop.db`; `--target-directory` permite preparar otro destino. Si el despliegue usa rutas distintas en `.env`, seleccionar un directorio de preparacion y trasladar los archivos con los servicios detenidos; el importador no interpreta ubicaciones arbitrarias de cada archivo.

Se respaldan los destinos existentes mediante la API de backup de SQLite antes de cambiar esquemas. La importacion usa una transaccion con bases adjuntas y journals DELETE. Un conflicto revierte los registros de las tres bases; las migraciones de esquema anteriores a esa transaccion permanecen, con el respaldo disponible. Los registros con el mismo ID e identidad compatible se conservan sin sobrescribirlos; IDs incompatibles o unicidad en conflicto detienen la importacion.

Se conservan UUID, propietario, taller, datos del vehiculo, metadatos de la orden, importes convertidos de centavos a pesos, credenciales scrypt y enlaces pendientes. Las contrasenas nuevas/activadas usan PBKDF2. No se importan cookies de sesion de Node: **es necesario iniciar sesion nuevamente con las credenciales existentes**. No se importan datos que solo estaban en el navegador. Si una cuenta antigua carece de VIN, propietario o relacion valida con taller/vehiculo, corregirla en la fuente o preparar una migracion especifica; el importador no inventa relaciones.

Importacion realizada en este equipo: **2 cuentas, 1 taller, 1 cliente, 1 vehiculo y 1 orden** desde el SQLite de desarrollo de Node. No habia enlaces pendientes. La fuente se conservo. Se comprobo acceso de la cuenta demo importada y recuperacion de su vehiculo y orden a traves del proxy Vite → gateway → microservicios.

## Verificaciones y alcance pendiente

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/audit_endpoints.py --frontend ..\TallerPlusWEB --check
```

Pasan **20 pruebas de backend**, que cubren los flujos nativos anteriores, la API del navegador, concurrencia de activacion, duplicados, compensacion de fallos, aislamiento, importacion repetible, compatibilidad scrypt y rollback entre las tres bases. El gateway expone 82 operaciones; las 10 llamadas actuales de `customerApi.ts` tienen su ruta exacta. El auditor por si solo comprueba presencia, no comportamiento.

El frontend pasa sus **79 pruebas** y compila; lint conserva 5 advertencias existentes y el build avisa de un bundle JS mayor de 500 kB. Las pruebas antiguas de `server/` se conservan como referencia del contrato anterior.

La siguiente fase debe persistir configuracion y personal del taller, catalogo, nuevas solicitudes posteriores a la recepcion, cotizaciones y autorizacion parcial, avances, fotos adicionales, kilometraje/combustible y favoritos. Esos adaptadores siguen siendo locales. La mezcla de cache tambien conserva ediciones locales; todavia no acredita sincronizacion de esos modulos entre dispositivos.
