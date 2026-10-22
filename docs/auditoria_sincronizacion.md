> Actualización del 20 de octubre de 2026: los módulos solicitados de taller y conductor ya tienen persistencia y sincronización en SQL. Consultar [estado de la integración web](sincronizacion_web_sql.md). Las limitaciones de fases anteriores descritas a continuación son históricas.

# Auditoria de endpoints y sincronizacion

Fecha: 19 de octubre de 2026. Proyectos revisados: `SistemaBackendVillavisWorkshop` y el estado local de `../TallerPlusWEB`, incluidos sus cambios sin commit.

> Actualizacion posterior: la primera fase de migracion implementa las 9 rutas del cliente web en FastAPI, cambia el proxy y migra los datos de Node. Ver [estado actual y arranque](migracion_node_fastapi.md). El inventario JSON se regenera con el codigo actual; las cifras y hallazgos siguientes describen la auditoria anterior a la migracion.

## Resultado inicial

**La auditoria inicial encontro que no existia sincronizacion entre ambos proyectos.** El gateway tenia 72 operaciones HTTP y TallerPlusWEB enviaba sus peticiones a otra API, implementada en `server/app.mjs` y `server/database.mjs`, con otra base SQLite. Muchas operaciones de sus paneles solo modificaban `localStorage`.

Se revisaron rutas, esquemas de entrada/salida, autenticacion, persistencia y modulos del frontend. Se ejecutaron pruebas de integracion del backend y las pruebas, compilacion y lint del frontend. No se modificaron fuentes del frontend ni se migraron datos. No se realizo despliegue ni una prueba de navegador conectado a FastAPI, porque actualmente no existe esa conexion.

## Contrato HTTP actual de la web

Fuente: `TallerPlusWEB/src/services/customerApi.ts`. Hay 10 llamadas exportadas y 9 combinaciones distintas de metodo y ruta: cliente y taller comparten login. El [inventario generado](endpoints-inventario.json) contiene las declaraciones de todos los servicios y sus lineas de origen.

| Peticion del frontend | Backend FastAPI | Diferencia que impide usarlo directamente |
| --- | --- | --- |
| `POST /api/auth/login` (cliente) | `POST /auth/login` | Web envia `{type, telefono, password}`; backend requiere `{phone, password}`. Web espera `SessionData`; backend devuelve token, usuario y vehiculo |
| `POST /api/auth/login` (taller) | `POST /auth/staff/login` | Web usa email; backend requiere telefono. Las cuentas de ambas bases son independientes |
| `POST /api/auth/workshops` | No existe | Crear un taller con `POST /workshops` exige personal autenticado y no crea su encargado ni una sesion |
| `GET /api/auth/session` | No existe | `GET /auth/me` devuelve solo el usuario, no `{user, users, vehicles, orders, workshops}` |
| `POST /api/auth/logout` | `POST /auth/logout` | Web envia cookie y espera JSON `{success:true}`; backend exige Bearer y responde 204 sin cuerpo |
| `GET /api/workshops` | `GET /workshops` | Web espera `{workshops:[...]}` con `nombre`, `ubicacion` y ocupacion agregada; backend devuelve lista con `name`, `address` y sin ocupacion |
| `POST /api/workshop/intake` | No existe | Web requiere alta de cliente pendiente, vehiculo, solicitud y enlace de activacion. `/vehicle-intakes` es solo el checklist de un vehiculo ya registrado |
| `POST /api/workshop/activation` | No existe | No hay renovacion de enlaces ni cuenta pendiente de activacion |
| `POST /api/activation/validate` | No existe | No hay tokens de activacion temporal |
| `POST /api/activation/complete` | No existe | No hay establecimiento inicial de contrasena mediante token de un solo uso |

Son **6 rutas ausentes incluso eliminando `/api`**. Las otras 3 rutas distintas tampoco tienen contrato compatible. Vite dirige `/api` a `127.0.0.1:3001`; el script `scripts/dev.mjs` inicia Node, no FastAPI. Cambiar solamente el puerto del proxy no resuelve estas diferencias.

La API web usa cookie HttpOnly `tallerplus_session` con expiracion de 12 horas. FastAPI usa JWT RS256 en `Authorization: Bearer`, expiracion de 1 hora y validacion de revocacion en identidad. El cliente web no envia esa cabecera. Se necesita una estrategia comun de sesion y un adaptador de datos; no debe almacenarse el token en las colecciones publicas del navegador.

## Cobertura funcional y pendientes

Las rutas siguientes son las existentes del gateway, sin prefijo `/api`. Las rutas mencionadas como propuestas son trabajo pendiente, no funcionalidad implementada.

| Modulo visible en la web | Cobertura actual de FastAPI | Trabajo necesario para sincronizar |
| --- | --- | --- |
| Acceso y activacion | Login por telefono, registro publico de cliente con vehiculo, registro de personal protegido | Implementar el flujo de recepcion y activacion usado por la web, registro taller/encargado y recuperacion de sesion agregada |
| Clientes y vehiculos | `/customers`, `/customers/{id}/vehicles`, `/me/vehicles`, consultas y edicion de vehiculo | Adaptar nombres y UUID; persistir combustible, cilindros, odometro, foto y autor del registro. La web admite electricos y placas opcionales con VIN; backend exige placa y VIN |
| Kilometraje y combustible | No existen recursos correspondientes | Persistir registros de distancia y cargas con sus validaciones. Propuestas: `GET/POST /vehicles/{id}/mileage` y `GET/POST /vehicles/{id}/fuel` |
| Directorio y talleres guardados | `/workshops`, `/workshops/{id}/services` | Devolver perfil publico compatible y ocupacion agregada. Persistir favoritos por conductor; actualmente `savedWorkshops.ts` solo usa el navegador |
| Especificaciones del taller | Nombre, direccion libre, descripcion, telefono y URL de foto | Persistir ubicacion estructurada, horario, puestos de trabajo, vehiculos por dia y equipamiento. Propuesta: `GET/PATCH /workshops/{id}/configuration` |
| Personal y permisos | Roles globales `client`, `staff`, `admin` | Crear membresias por taller, puesto, especialidad, administracion y baja de personal. Faltan `workshop_id` y tecnico asignado; un rol staff actualmente permite operar sobre cualquier taller |
| Catalogo | `/services`, precios por 3/4/6/8 cilindros y activacion | Adaptar precios de pesos a centavos y prioridad; cubrir variantes con nombre propio, precio sin definir y servicios sin cilindros. `tallerServices.ts` sigue guardando catalogos locales |
| Solicitudes/citas | `/appointments`, `/service-carts`, checkout | Reemplazar escrituras de `useFirestore.tsx`/`useSolicitud.tsx` con llamadas a servidor, adaptar servicios/variantes y controlar solicitudes activas por auto |
| Cotizacion | Crear, consultar, agregar, editar y quitar partidas; aceptar/rechazar | La UI permite seleccionar servicios individuales y forma de pago al autorizar. El backend acepta/rechaza la cotizacion completa; falta esa autorizacion parcial y el contrato correspondiente |
| Avance y entrega | Estados de orden, tareas, porcentaje, aceptacion | La UI usa etapas, tareas por etapa, evidencias obligatorias, entrega estimada y restricciones por tecnico. Hace falta persistir esos campos y validar transiciones en servidor; traducir estados no basta |
| Evidencias y fotos | URLs en recepcion y ordenes | La UI almacena imagenes `data:` por etapa/auto; faltan carga binaria, almacenamiento y vinculacion por etapa. Una cadena `data:` de la UI supera el limite de 500 caracteres de `file_url` |
| Historial y recomendaciones | `/vehicles/{id}/history`, recomendaciones, resumen de cliente | Conectar consultas al servidor y sustituir las colecciones locales; establecer que hacer con los datos anteriores de cada navegador |
| Notificaciones | Cliente y taller: listado, contador y marcado de lectura | Conectar lectura/refresco a estos recursos y respetar aislamiento por taller |
| Pagos y reportes | Pagos manuales, tablero y reporte por taller/periodo | El enlace Stripe del checkout es provisional. No hay checkout de Stripe real ni webhooks; registrar un pago manual no confirma automaticamente una solicitud de anticipo |

Otros contratos que requieren traduccion explicita:

- Usuario: web usa `uid`, `role:user/taller/admin`, `estado`, `celular`, `tallerId`; backend usa `id`, `role:client/staff/admin`, `phone`, `customer_id` y no tiene estado de activacion ni membresia de taller.
- Vehiculo: web usa `marca`, `modelo`, `anio`, `placas`, `numeroSerie`, `conductorId`; backend usa `brand`, `model`, `year`, `plate`, `vin`, `customer_id`.
- Precio: web usa enteros `precioCentavos` en MXN; backend usa `float` en pesos. Copiar directamente los importes produce un factor de 100 de diferencia.
- Estado: `SolicitudEstado` y `EtapaServicio` no coinciden con `WorkOrderStatus`; se necesita una representacion compartida y reglas de transicion, no una sustitucion textual.
- Cache: `cacheSession` conserva vehiculos y solicitudes locales existentes al mezclar la respuesta del servidor. Incluso con un contrato adaptado, una copia antigua puede ocultar cambios posteriores de otro dispositivo.

## Correcciones realizadas en este backend

1. **Arranque de identidad:** `POST /auth/logout` devuelve `Response(204)` explicitamente. La declaracion anterior impedia importar/iniciar el servicio con la version de FastAPI del proyecto.
2. **Checkout, dashboard y reportes:** se agregaron los imports faltantes de `Priority` y `PaymentStatus`; provocaban `NameError` y respuestas 500.
3. **Consultas faltantes del gateway:** `GET /vehicles/{vehicle_id}`, `GET /vehicles/by-vin/{vin}` y `GET /customers/{customer_id}/vehicles`. Las consultas por propietario verifican acceso; busqueda por VIN exige personal.
4. **Edicion de cotizaciones:** `PATCH /quotes/{quote_id}/items/{item_id}` y `DELETE /quotes/{quote_id}/items/{item_id}` recalculan subtotales dentro de la transaccion. Los clientes no pueden editar partidas. Cotizaciones aceptadas/rechazadas quedan bloqueadas y repetir el mismo estado no reinicia una orden ya entregada.
5. **Integridad cliente/vehiculo:** crear una cita rechaza un vehiculo que no pertenece al cliente indicado, tambien cuando lo solicita personal.
6. **Contrato de actualizacion de vehiculo:** gateway y customer_service comparten esquema. VIN de mas de 17 caracteres y `null` en campos obligatorios se rechazan antes de persistir; anteriormente podian producir errores 500 o dejar datos incompatibles con la respuesta.
7. Se corrigio la trazabilidad que describia el login como placa+VIN; el acceso implementado es telefono+contrasena.

Estas correcciones fortalecen el backend existente; no implementan los flujos faltantes de la tabla anterior ni conectan la web.

## Verificacion reproducible

Desde la raiz del backend, despues de instalar `requirements.txt`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/audit_endpoints.py --frontend ..\TallerPlusWEB --output docs/endpoints-inventario.json
.\.venv\Scripts\python.exe scripts/audit_endpoints.py --frontend ..\TallerPlusWEB --check
```

- **Backend: 9 pruebas pasan.** Arranque real de las apps, JWT y revocacion, aislamiento entre clientes, permisos por rol, consultas de vehiculos, validacion sin escrituras parciales del PATCH, consistencia de citas, edicion/bloqueo de cotizaciones, carrito, anticipo, orden y tareas, evidencias, notificaciones y reporte de pagos. HTTP ASGI conecta gateway y microservicios con SQLite y claves temporales; no se simulan respuestas de negocio. No equivale a haber probado individualmente las 72 operaciones ni el despliegue Docker.
- **Auditor estatico:** inventaria 72 operaciones del gateway; confirma 6 rutas ausentes del cliente HTTP. `--check` devuelve 1 por esas incompatibilidades esperadas. No evalua por si solo esquemas, permisos, cookies ni persistencia.
- **Frontend: 79 pruebas pasan** con `npm.cmd test`; `npm.cmd run build` termina correctamente. `npm.cmd run lint` termina con 5 advertencias existentes. La compilacion avisa de un bundle JS mayor de 500 kB. Esas comprobaciones verifican el frontend actual con su API Node y adaptadores locales.
- Docker no esta instalado en el entorno revisado; no se valido la red de Compose.

## Orden de integracion propuesto

1. Hacer de este backend la fuente de datos del producto y definir el contrato compartido de identidad, taller y sesion. Implementar recepcion y activacion con unicidad, tokens de un solo uso y compensacion de fallos entre microservicios; el registro publico actual no ofrece una transaccion distribuida.
2. Implementar membresias por taller y autorizacion de recursos en el gateway antes de usar varios talleres reales. Agregar configuracion, personal y campos de vehiculo que la web necesita.
3. Conectar los adaptadores de la web a recursos persistentes para catalogo, solicitudes, cotizaciones, evidencias, avance, kilometraje, combustible y favoritos. Establecer una migracion explicita de Node y datos locales, y una politica de cache que permita ver cambios de otro dispositivo.
4. Cambiar el proxy de desarrollo y despliegue al contrato integrado. Verificar en dos navegadores: taller registra → conductor activa → inicia sesion → ve auto/orden → taller cotiza → conductor autoriza → taller actualiza → conductor ve el mismo progreso → entrega.

La sincronizacion se puede dar por verificada cuando ese flujo use la misma fuente persistente y sus cambios sean visibles desde ambos perfiles y dispositivos.
