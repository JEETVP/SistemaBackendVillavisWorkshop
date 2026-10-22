# Sistema Backend Villavis Workshop

> **Estado actual:** PostgreSQL 17 y despliegue en Render. No se migran bases SQLite. Consultar [configuraci?n PostgreSQL/Render](docs/postgresql-render.md) y la gu?a de Cloudflare Pages en TallerPlusWEB. Los procedimientos anteriores de Azure/SQLite que permanezcan m?s abajo son hist?ricos.


Backend distribuido en Python para un taller mecanico. La solucion esta organizada como microservicios independientes con un API Gateway al frente.

## Estado de integracion con TallerPlusWEB

La primera fase de migracion ya conecta TallerPlusWEB con FastAPI para registro de talleres, acceso, sesiones, recepcion, activacion y directorio. Las 9 rutas HTTP del cliente web estan cubiertas bajo `/api`. Los registros existentes de la API Node se pueden importar conservando sus IDs y credenciales. Consulta [Migracion desde Node](docs/migracion_node_fastapi.md) para arranque, `.env`, importacion y limites de esta fase. Catalogo, avances y otros adaptadores locales todavia requieren migracion.

## Arquitectura

- `api_gateway`: entrada principal del sistema. Agrega respuestas y coordina llamadas entre servicios.
- `identity_service`: administra usuarios, sesiones y roles.
- `customer_service`: administra clientes y vehiculos.
- `workshop_service`: administra catalogo de servicios, citas, ordenes, cotizaciones, evidencias, recomendaciones y apartados.
- Cada servicio tiene su propia base de datos SQLite para mantener independencia de datos.

## Requisitos

- Python 3.11+
- Docker y Docker Compose, opcional pero recomendado

## Ejecutar con Docker Compose

Crear `.env` con `python scripts/create_env.py` antes de arrancar. Este archivo contiene la configuracion local y un token interno aleatorio; no se versiona. `.env.example` es la plantilla sin secretos reales. Para produccion, configurar `APP_ENV=production` y `APP_ORIGIN` con el dominio HTTPS.

```bash
docker compose up --build
```

Servicios:

- Gateway: `http://localhost:8000`
- Clientes: interno en la red de Docker (`customer_service:8001`)
- Taller: interno en la red de Docker (`workshop_service:8002`)
- Identidad: interno en la red de Docker (`identity_service:8003`)

Documentacion interactiva:

- `http://localhost:8000/docs`

En Docker Compose solo se expone el gateway para evitar saltarse las validaciones de sesion y roles.

## Ejecutar localmente sin Docker

En Windows, despues de instalar dependencias:

```powershell
python scripts/create_env.py
.\.venv\Scripts\python.exe scripts/dev.py
```

El lanzador inicia los cuatro procesos y los detiene con Ctrl+C. En otra terminal, desde TallerPlusWEB, `npm.cmd run dev` inicia Vite y su proxy a FastAPI. El frontend ya no inicia Node como API.

En Ubuntu/WSL puede ser necesario instalar soporte de entornos virtuales:

```bash
sudo apt install python3.12-venv python3-pip
```

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Terminal 1:

```bash
uvicorn services.identity_service.app:app --reload --port 8003
```

Terminal 2:

```bash
uvicorn services.customer_service.app:app --reload --port 8001
```

Terminal 3:

```bash
uvicorn services.workshop_service.app:app --reload --port 8002
```

Terminal 4:

```bash
uvicorn services.api_gateway.app:app --reload --port 8000
```

## Flujo de prueba

Crear cuenta de cliente con datos del vehiculo:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "name":"Carlos Ramirez",
    "phone":"555-0101",
    "password":"CambiaEstaClave123",
    "plate":"ABC-123",
    "vin":"3N1CN7AD0KL000001",
    "brand":"Nissan",
    "model":"Versa",
    "year":2020,
    "vehicle_type":"Automovil",
    "color":"gris",
    "engine_number":"MR2000001",
    "service_type":"particular",
    "owner_name":"Carlos Ramirez"
  }'
```

Guarda el `access_token` de la respuesta y usalo como token Bearer. El cliente inicia sesion con telefono y contrasena; el registro vincula la cuenta con el primer vehiculo.

Iniciar sesion con telefono y contrasena:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"phone":"555-0101","password":"CambiaEstaClave123"}'
```

Consultar vehiculos vinculados al cliente:

```bash
curl http://localhost:8000/me/vehicles \
  -H "Authorization: Bearer TOKEN"
```

Vincular otro vehiculo al mismo cliente:

```bash
curl -X POST http://localhost:8000/me/vehicles \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "plate":"XYZ-789",
    "vin":"3N1CN7AD0KL000002",
    "brand":"Toyota",
    "model":"Corolla",
    "year":2021,
    "vehicle_type":"Automovil",
    "color":"blanco",
    "engine_number":"2ZR000002",
    "service_type":"particular",
    "owner_name":"Carlos Ramirez"
  }'
```

Iniciar sesion con el administrador de desarrollo para tareas del taller:

```bash
curl -X POST http://localhost:8000/auth/staff/login \
  -H "Content-Type: application/json" \
  -d '{"phone":"5550000000","password":"password123"}'
```

Este ejemplo requiere configurar previamente las variables opcionales `IDENTITY_BOOTSTRAP_ADMIN_PHONE` y `IDENTITY_BOOTSTRAP_ADMIN_PASSWORD` del `.env`; no se crean administradores ni credenciales demo automaticamente. El endpoint `POST /auth/staff/login` acepta telefono y contrasena. La web registra al encargado del taller con correo y usa `POST /api/auth/login`.

Las contrasenas nuevas se guardan con PBKDF2-HMAC-SHA256, sal aleatoria por usuario y 120,000 iteraciones; las importadas de Node conservan su verificador scrypt. Las sesiones son JWT RS256 con expiracion configurable por `JWT_TTL_SECONDS` (12 horas en la plantilla local). Identidad firma con la clave privada persistida y el gateway valida firma, emisor, audiencia, expiracion y revocacion. La API de navegador entrega el JWT exclusivamente en una cookie HttpOnly; la API nativa acepta Bearer.

Crear taller:

```bash
curl -X POST http://localhost:8000/workshops \
  -H "Authorization: Bearer TOKEN_ADMIN" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"Villavis Workshop",
    "address":"Av. Principal 123, Puebla",
    "photo_url":"https://cdn.example.com/villavis-workshop.jpg",
    "phone":"222-555-0101",
    "description":"Taller mecanico con servicios preventivos, correctivos y esteticos"
  }'
```

La fotografia del taller se guarda como `photo_url`, no como binario dentro de SQLite. Esto permite usar una URL publica, una ruta local servida por el backend o una llave de almacenamiento externo en una etapa futura.

Consultar talleres disponibles:

```bash
curl http://localhost:8000/workshops
```

Crear servicio de catalogo asociado a un taller:

```bash
curl -X POST http://localhost:8000/services \
  -H "Authorization: Bearer TOKEN_ADMIN" \
  -H "Content-Type: application/json" \
  -d '{
    "workshop_id":"WORKSHOP_ID",
    "name":"Cambio de aceite multigrado mineral",
    "service_type":"Preventivo",
    "description":"Cambio de aceite multigrado mineral de motor y cambio de filtro de aceite",
    "priority_rank":1,
    "price_3_cyl":2248,
    "price_4_cyl":2491,
    "price_6_cyl":2757,
    "price_8_cyl":2920,
    "parts_brand":"STP, Gonher, Castrol, Valvoline",
    "supplies_brand":"Fram, Gonher, Tecfil",
    "estimated_minutes":45
  }'
```

`priority_rank` va de `1` a `3`; `1` representa lo mas necesario para el vehiculo y se usa para ordenar el resumen del carrito.

Consultar servicios de un taller:

```bash
curl http://localhost:8000/workshops/WORKSHOP_ID/services
```

Consultar precio por cilindraje:

```bash
curl "http://localhost:8000/services/SERVICE_ID/price?cylinders=4"
```

Verificar NIV/VIN y registrar inventario de entrada:

```bash
curl -X POST http://localhost:8000/vehicle-intakes \
  -H "Authorization: Bearer TOKEN_CLIENTE" \
  -H "Content-Type: application/json" \
  -d '{
    "workshop_id":"WORKSHOP_ID",
    "vehicle_id":"VEHICLE_ID",
    "vin":"3N1CN7AD0KL000001",
    "has_tapones":true,
    "has_virlos":true,
    "has_tapa_gasolina":true,
    "has_rines":true,
    "has_ceniceros":false,
    "has_llanta_refaccion":true,
    "detail_notes":"Rayon leve en defensa trasera",
    "photo_urls":[
      "https://cdn.example.com/intake/frente.jpg",
      "https://cdn.example.com/intake/defensa-trasera.jpg"
    ]
  }'
```

El gateway valida que el NIV/VIN corresponda al vehiculo vinculado al usuario antes de guardar el checklist. Las fotografias se guardan como `photo_urls`; la carga binaria real puede agregarse despues con almacenamiento local o externo.

Crear carrito de servicios despues del intake:

```bash
curl -X POST http://localhost:8000/service-carts \
  -H "Authorization: Bearer TOKEN_CLIENTE" \
  -H "Content-Type: application/json" \
  -d '{
    "workshop_id":"WORKSHOP_ID",
    "vehicle_id":"VEHICLE_ID",
    "intake_id":"INTAKE_ID"
  }'
```

Agregar servicios uno por uno al carrito:

```bash
curl -X POST http://localhost:8000/service-carts/CART_ID/items \
  -H "Authorization: Bearer TOKEN_CLIENTE" \
  -H "Content-Type: application/json" \
  -d '{"service_id":"SERVICE_ID","cylinder_count":4,"quantity":1}'
```

Editar cantidad o cilindraje de un servicio del carrito:

```bash
curl -X PATCH http://localhost:8000/service-carts/CART_ID/items/ITEM_ID \
  -H "Authorization: Bearer TOKEN_CLIENTE" \
  -H "Content-Type: application/json" \
  -d '{"quantity":2,"cylinder_count":6}'
```

Consultar resumen con prioridades y total previo:

```bash
curl http://localhost:8000/service-carts/CART_ID/summary \
  -H "Authorization: Bearer TOKEN_CLIENTE"
```

Eliminar un servicio del carrito:

```bash
curl -X DELETE http://localhost:8000/service-carts/CART_ID/items/ITEM_ID \
  -H "Authorization: Bearer TOKEN_CLIENTE"
```

Crear la cita desde el carrito y generar anticipo:

```bash
curl -X POST http://localhost:8000/service-carts/CART_ID/checkout \
  -H "Authorization: Bearer TOKEN_CLIENTE" \
  -H "Content-Type: application/json" \
  -d '{
    "requested_at":"2026-10-20T10:00:00-06:00",
    "deposit_percentage":30,
    "notes":"Primera visita del vehiculo"
  }'
```

`deposit_percentage` solo acepta `30` o `50`. La respuesta incluye la cita creada, el `payment_request` con `payment_link` provisional para Stripe, el ticket de compra y la notificacion interna generada para el usuario.
Tambien se crea una orden de trabajo en estado `received`, con una tarea por cada servicio del carrito, y una notificacion interna para el taller.

Consultar notificaciones del taller:

```bash
curl http://localhost:8000/workshops/WORKSHOP_ID/notifications \
  -H "Authorization: Bearer TOKEN_ADMIN"
```

Aceptar orden de trabajo:

```bash
curl -X POST http://localhost:8000/work-orders/ORDER_ID/accept \
  -H "Authorization: Bearer TOKEN_ADMIN"
```

Actualizar avance de un servicio de la orden:

```bash
curl -X PATCH http://localhost:8000/work-orders/ORDER_ID/tasks/TASK_ID/status \
  -H "Authorization: Bearer TOKEN_ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"status":"in_progress"}'
```

Los estados de servicio aceptados son `pending`, `in_progress` y `done`. Cada cambio genera una notificacion interna para el cliente y el detalle de la orden devuelve `progress_percent`, `total_tasks` y `completed_tasks`.
Los estados de orden disponibles son `received`, `diagnosis`, `awaiting_approval`, `approved`, `in_progress`, `ready`, `delivered` y `cancelled`.

Consultar tablero administrativo:

```bash
curl "http://localhost:8000/admin/dashboard?workshop_id=WORKSHOP_ID" \
  -H "Authorization: Bearer TOKEN_ADMIN"
```

Consultar reporte operativo por taller y periodo:

```bash
curl "http://localhost:8000/reports/workshops?workshop_id=WORKSHOP_ID&date_from=2026-10-01&date_to=2026-10-31" \
  -H "Authorization: Bearer TOKEN_ADMIN"
```

Consultar historial completo del vehiculo:

```bash
curl http://localhost:8000/vehicles/VEHICLE_ID/history \
  -H "Authorization: Bearer TOKEN_CLIENTE"
```

Consultar notificaciones dentro de la app:

```bash
curl http://localhost:8000/me/notifications \
  -H "Authorization: Bearer TOKEN_CLIENTE"
```

Marcar una notificacion como leida:

```bash
curl -X PATCH http://localhost:8000/me/notifications/NOTIFICATION_ID/read \
  -H "Authorization: Bearer TOKEN_CLIENTE"
```

Consultar contador de notificaciones no leidas:

```bash
curl http://localhost:8000/me/notifications/unread-count \
  -H "Authorization: Bearer TOKEN_CLIENTE"
```

Marcar todas las notificaciones del cliente como leidas:

```bash
curl -X PATCH http://localhost:8000/me/notifications/read-all \
  -H "Authorization: Bearer TOKEN_CLIENTE"
```

Solicitar primer servicio para un vehiculo nuevo usando el intake:

```bash
curl -X POST http://localhost:8000/appointments \
  -H "Authorization: Bearer TOKEN_CLIENTE" \
  -H "Content-Type: application/json" \
  -d '{
    "workshop_id":"WORKSHOP_ID",
    "customer_id":"CLIENT_ID",
    "vehicle_id":"VEHICLE_ID",
    "intake_id":"INTAKE_ID",
    "requested_at":"2026-10-20T10:00:00-06:00",
    "notes":"Primera visita del vehiculo",
    "services":[
      {
        "service_id":"SERVICE_ID",
        "cylinder_count":4,
        "quantity":1
      }
    ]
  }'
```

La respuesta incluye `estimated_total`. Esta solicitud todavia no es historial de servicio realizado; queda en estado `requested` hasta que el taller confirme y genere la orden.

Crear orden de trabajo desde la solicitud:

```bash
curl -X POST http://localhost:8000/work-orders \
  -H "Authorization: Bearer TOKEN_ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"workshop_id":"WORKSHOP_ID","customer_id":"CLIENT_ID","vehicle_id":"VEHICLE_ID","appointment_id":"APPOINTMENT_ID","description":"Cambio de aceite y revision de frenos","priority":"normal"}'
```

Crear cotizacion:

```bash
curl -X POST http://localhost:8000/quotes \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"work_order_id":"ORDER_ID","notes":"Cotizacion inicial","items":[{"service_id":"SERVICE_ID","cylinder_count":4,"description":"Cambio de aceite","quantity":1}]}'
```

Aceptar cotizacion:

```bash
curl -X PATCH http://localhost:8000/quotes/QUOTE_ID/status \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"accepted"}'
```

## Endpoints principales

Gateway:

- `GET /api/health`
- `POST /api/auth/workshops`
- `POST /api/auth/login`
- `GET /api/auth/session`
- `POST /api/auth/logout`
- `GET /api/workshops`
- `POST /api/workshop/intake`
- `POST /api/workshop/activation`
- `POST /api/activation/validate`
- `POST /api/activation/complete`
- `GET /health`
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/staff/login`
- `POST /auth/staff/register`
- `POST /auth/logout`
- `GET /auth/me`
- `GET /admin/dashboard`
- `GET /reports/workshops`
- `GET /me/vehicles`
- `POST /me/vehicles`
- `POST /workshops`
- `GET /workshops`
- `GET /workshops/{workshop_id}`
- `PATCH /workshops/{workshop_id}`
- `GET /workshops/{workshop_id}/services`
- `POST /customers`
- `GET /customers`
- `GET /customers/{customer_id}`
- `POST /customers/{customer_id}/vehicles`
- `GET /customers/{customer_id}/vehicles`
- `GET /vehicles/{vehicle_id}`
- `GET /vehicles/by-plate/{plate}`
- `GET /vehicles/by-vin/{vin}`
- `PATCH /vehicles/{vehicle_id}`
- `GET /customers/{customer_id}/summary`
- `POST /services`
- `GET /services`
- `GET /services/{service_id}`
- `PATCH /services/{service_id}`
- `GET /services/{service_id}/price?cylinders=4`
- `POST /service-carts`
- `GET /service-carts/{cart_id}`
- `GET /service-carts/{cart_id}/summary`
- `POST /service-carts/{cart_id}/items`
- `PATCH /service-carts/{cart_id}/items/{item_id}`
- `DELETE /service-carts/{cart_id}/items/{item_id}`
- `POST /service-carts/{cart_id}/checkout`
- `GET /me/notifications`
- `GET /me/notifications/unread-count`
- `PATCH /me/notifications/read-all`
- `PATCH /me/notifications/{notification_id}/read`
- `POST /vehicle-intakes`
- `GET /vehicle-intakes/{intake_id}`
- `GET /vehicles/{vehicle_id}/intakes`
- `GET /vehicles/{vehicle_id}/history`
- `POST /appointments`
- `GET /appointments`
- `GET /appointments/{appointment_id}`
- `PATCH /appointments/{appointment_id}/status`
- `POST /work-orders`
- `GET /work-orders`
- `GET /work-orders/{order_id}`
- `PATCH /work-orders/{order_id}/status`
- `POST /work-orders/{order_id}/accept`
- `POST /work-orders/{order_id}/tasks`
- `PATCH /work-orders/{order_id}/tasks/{task_id}/status`
- `POST /quotes`
- `GET /quotes/{quote_id}`
- `POST /quotes/{quote_id}/items`
- `PATCH /quotes/{quote_id}/items/{item_id}`
- `DELETE /quotes/{quote_id}/items/{item_id}`
- `PATCH /quotes/{quote_id}/status`
- `POST /work-orders/{order_id}/evidence`
- `GET /work-orders/{order_id}/evidence`
- `POST /recommendations`
- `GET /vehicles/{vehicle_id}/recommendations`
- `GET /workshops/{workshop_id}/notifications`
- `GET /workshops/{workshop_id}/notifications/unread-count`
- `PATCH /workshops/{workshop_id}/notifications/read-all`
- `PATCH /workshop-notifications/{notification_id}/read`
- `POST /payments`

## Roles

- `client`: entra con telefono y contrasena, consulta sus vehiculos, citas, ordenes, cotizaciones, evidencias y recomendaciones vinculadas.
- `staff`: inicia sesion con telefono y contrasena; registra clientes, vehiculos, servicios, citas, ordenes, cotizaciones, evidencias, recomendaciones y pagos/apartados.
- `admin`: tiene los mismos permisos operativos del personal para el piloto.

El registro publico crea cuentas `client` a partir de los datos del vehiculo y requiere telefono y contrasena. La creacion de usuarios `staff` y `admin` esta protegida por token de administrador y `POST /auth/staff/register` tambien solicita telefono y contrasena.

## Decision de diseno

El sistema usa HTTP entre servicios para demostrar comunicacion distribuida y bases de datos separadas para evitar acoplamiento directo. SQLite permite correr el proyecto sin infraestructura adicional, pero la separacion facilita migrar cada servicio a PostgreSQL u otro motor cuando el proyecto crezca.

El alcance actual registra apartados/pagos de forma manual. La integracion real con Stripe queda preparada como siguiente fase mediante un proveedor externo y webhooks, tal como plantea la propuesta.

## Verificacion

Con las dependencias instaladas en el entorno virtual:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/audit_endpoints.py --frontend ..\TallerPlusWEB --check
```

Las 20 pruebas usan los tres microservicios reales a traves de HTTP ASGI, sus validaciones, JWT y SQLite temporales dentro de `data/test-runs`; incluyen el contrato web, compensacion de fallos e importacion desde Node. No utilizan bases existentes ni servicios externos. El auditor compara las rutas del cliente HTTP del frontend con las declaraciones del gateway; las 10 llamadas actuales (9 rutas distintas) tienen coincidencia directa. Solo comprueba presencia de rutas; las pruebas de integracion verifican ademas contratos y sesiones.

La edicion de partidas acepta `description`, `quantity` y `unit_price`, recalcula el subtotal y devuelve la cotizacion completa. Las cotizaciones aceptadas o rechazadas no permiten cambios de partidas ni reapertura; un cambio de precio requiere una cotizacion nueva. Repetir el mismo estado es idempotente.

## Despliegue en Azure y CI/CD

La configuraci?n de producci?n est? en `TallerPlusWEB/deploy/`: VM de Ubuntu, Docker Compose, HTTPS, Azure Container Registry y publicaci?n conjunta de ambos repositorios. El backend conserva sus tres bases SQLite y su clave de firma en vol?menes sobre un disco administrado local de la VM. No se utiliza MongoDB ni se han convertido las bases a Azure SQL.

`.github/workflows/ci.yml` ejecuta las pruebas SQL y construye este Dockerfile en cada push o pull request. El flujo `Azure VM release` del frontend descarga la revisi?n elegida de este repositorio, prueba ambos proyectos, publica sus im?genes y despliega mediante Azure Run Command. Requiere subir los cambios de ambos repositorios antes de lanzarlo. Consultar `TallerPlusWEB/docs/azure-vm.md` para crear los recursos y configurar OIDC, permisos y variables.

La imagen no incluye datos, archivos `.env` ni claves privadas. Se ejecuta como UID 10001. En instalaciones Docker anteriores, revisar la propiedad de los vol?menes antes de cambiar desde una imagen que se ejecutaba como root. El procedimiento de Azure inicializa vol?menes nuevos; no importa autom?ticamente el contenido de las bases de desarrollo.
