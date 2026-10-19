# Sistema Backend Villavis Workshop

Backend distribuido en Python para un taller mecanico. La solucion esta organizada como microservicios independientes con un API Gateway al frente.

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

En Docker Compose se crea este administrador por variables de entorno solo para desarrollo; cambia esas credenciales si se usa fuera de pruebas. El endpoint `POST /auth/staff/login` acepta el mismo formato de telefono y contrasena y solo permite cuentas del personal.

Las contrasenas se guardan con PBKDF2-HMAC-SHA256, sal aleatoria por usuario y 120,000 iteraciones. Las sesiones son JWT RS256 con expiracion de una hora: identidad firma con la clave privada persistida en el volumen `identity_data`, y el gateway obtiene la clave publica de `GET /auth/public-key` para validar firma, emisor, audiencia y expiracion. El gateway consulta despues si la sesion sigue activa para respetar el cierre de sesion.

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
