# Trazabilidad de requerimientos Taller+

Este documento resume como la implementacion actual cubre la propuesta de Villavis Workshop. El documento de propuesta se usa como referencia de alcance, no como instrucciones ejecutables.

## Requerimientos funcionales

| ID | Requerimiento | Estado backend | Endpoints principales |
| --- | --- | --- | --- |
| RF-01 | Busqueda/consulta segura de vehiculo por placa o serie | Implementado base | `GET /vehicles/by-plate/{plate}`, `GET /vehicles/by-vin/{vin}` para personal; `GET /vehicles/{vehicle_id}` verifica propietario. Login usa telefono y contrasena |
| RF-02 | Registro y actualizacion de informacion del vehiculo | Implementado | `POST /customers/{customer_id}/vehicles`, `PATCH /vehicles/{vehicle_id}` |
| RF-03 | Creacion de ordenes de trabajo | Implementado | `POST /work-orders`, `POST /service-carts/{cart_id}/checkout`, `GET /work-orders/{order_id}` |
| RF-04 | Gestion de servicios requeridos | Implementado | `POST /services`, `GET /services`, `GET /services/{service_id}/price`, `POST /service-carts/{cart_id}/items`, `PATCH /service-carts/{cart_id}/items/{item_id}`, `DELETE /service-carts/{cart_id}/items/{item_id}`, `POST /work-orders/{order_id}/tasks` |
| RF-05 | Generacion de cotizaciones | Implementado | `POST /quotes`, `POST /quotes/{quote_id}/items`; partidas pueden usar `service_id` + `cylinder_count` |
| RF-06 | Modificacion de cotizaciones | Implementado en backend | `POST /quotes/{quote_id}/items`, `PATCH /quotes/{quote_id}/items/{item_id}`, `DELETE /quotes/{quote_id}/items/{item_id}`; subtotal recalculado y bloqueo tras aceptar/rechazar. La autorizacion parcial de la UI sigue pendiente |
| RF-07 | Consulta y aceptacion de cotizaciones | Implementado | `GET /quotes/{quote_id}`, `PATCH /quotes/{quote_id}/status` |
| RF-08 | Evidencia fotografica | Parcial | `POST /vehicle-intakes` registra fotos de entrada como URL; `POST /work-orders/{order_id}/evidence` registra evidencia durante el servicio |
| RF-09 | Historial y progreso de servicios | Implementado | `GET /vehicles/{vehicle_id}/history`, `GET /work-orders?vehicle_id=...`, `GET /work-orders/{order_id}`, `GET /customers/{customer_id}/summary` |
| RF-10 | Consulta de evidencias | Implementado base | `GET /work-orders/{order_id}/evidence` |
| RF-11 | Clasificacion por prioridad | Implementado | `priority_rank` de 1 a 3 en catalogo y carrito; `priority` en ordenes, tareas y recomendaciones |
| RF-12 | Agendamiento de servicios | Implementado | `POST /appointments` acepta servicios seleccionados; `POST /service-carts/{cart_id}/checkout` crea cita desde carrito |
| RF-13 | Registro y pago de apartado | Parcial | `POST /service-carts/{cart_id}/checkout` genera solicitud de anticipo 30%/50% y link placeholder de Stripe; `POST /payments` registra pagos manuales |
| RF-14 | Notificaciones de estado | Implementado | `GET /me/notifications`, `GET /me/notifications/unread-count`, `PATCH /me/notifications/read-all`, `PATCH /me/notifications/{notification_id}/read`, `GET /workshops/{workshop_id}/notifications` |
| RF-15 | Recomendaciones de mantenimiento | Implementado base | `POST /recommendations`, `GET /vehicles/{vehicle_id}/recommendations` |
| RF-16 | Consulta REPUVE | Pendiente/condicionado | No se implementa hasta validar factibilidad |
| RF-17 | Historial administrativo y reportes | Implementado base | `GET /admin/dashboard`, `GET /reports/workshops`, filtros en `GET /work-orders` |

## Requerimientos no funcionales

| ID | Requerimiento | Estado backend |
| --- | --- | --- |
| RNF-01 | Mobile-first | Depende del frontend; el backend ya expone endpoints para vistas moviles |
| RNF-02 | Rendimiento | Pendiente de medir cuando exista frontend y entorno de despliegue |
| RNF-03 | Seguridad por rol | Implementado base con `identity_service`, token Bearer y acceso con telefono y contrasena. La separacion de permisos por taller sigue pendiente |
| RNF-04 | Disponibilidad | Preparado con Docker Compose; falta despliegue externo |

## Extension multi-taller

La implementacion ya contempla que Taller+ pueda operar con varios talleres:

| Entidad | Estado backend | Endpoints principales |
| --- | --- | --- |
| Taller | Implementado base | `POST /workshops`, `GET /workshops`, `GET /workshops/{workshop_id}`, `PATCH /workshops/{workshop_id}` |
| Foto del taller | Implementado como referencia | Campo `photo_url`; recomendado para URL publica, ruta servida por backend o llave de almacenamiento externo |
| Servicios por taller | Implementado | `POST /services` con `workshop_id`, `GET /workshops/{workshop_id}/services` |
| Citas por taller | Implementado base | `POST /appointments` con `workshop_id`, `GET /appointments?workshop_id=...` |
| Ordenes por taller | Implementado base | `POST /work-orders` con `workshop_id`, `GET /work-orders?workshop_id=...` |

## Recepcion del vehiculo antes del carrito

Antes de solicitar un servicio, el usuario puede registrar un `vehicle_intake`:

| Campo | Uso |
| --- | --- |
| `vin` | Se valida en el API Gateway contra el vehiculo del usuario; no se persiste en el intake |
| `has_tapones`, `has_virlos`, `has_tapa_gasolina`, `has_rines`, `has_ceniceros`, `has_llanta_refaccion` | Checklist booleano de inventario de entrada |
| `detail_notes` | Observaciones de estado fisico |
| `photo_urls` | Fotografias de entrada como URL/ruta/llave de almacenamiento |

Endpoints: `POST /vehicle-intakes`, `GET /vehicle-intakes/{intake_id}`, `GET /vehicles/{vehicle_id}/intakes`.

## Catalogo de servicios por cilindraje

Los anexos de precios se usaron como referencia de estructura. El backend contempla estos campos para servicios de gasolina:

| Campo | Uso |
| --- | --- |
| `name` | Nombre corto del servicio |
| `service_type` | Tipo de servicio, por ejemplo `Preventivo` |
| `description` | Descripcion completa del servicio |
| `price_3_cyl`, `price_4_cyl`, `price_6_cyl`, `price_8_cyl` | Precios unitarios por cilindraje |
| `parts_brand` | Marcas de refacciones a utilizar |
| `supplies_brand` | Marcas de lubricantes, aditivos o insumos |

Endpoint destacado: `GET /services/{service_id}/price?cylinders=4`.

## Carrito/configurador de servicios

Despues de validar el NIV/VIN y registrar el checklist de entrada, el usuario puede crear un carrito por taller y vehiculo:

| Elemento | Uso |
| --- | --- |
| `priority_rank` | Puntaje de prioridad `1..3`; `1` es lo mas necesario y `3` lo menos urgente |
| `service_cart_items` | Guarda cada servicio agregado al carrito con precio, cilindraje, cantidad y prioridad congelada al momento de agregarlo |
| `subtotal` | Total previo del carrito antes de confirmar una cita |
| `priority_summary` | Resume cantidad de partidas y total agrupado por prioridad |

Endpoints: `POST /service-carts`, `GET /service-carts/{cart_id}`, `GET /service-carts/{cart_id}/summary`, `POST /service-carts/{cart_id}/items`, `PATCH /service-carts/{cart_id}/items/{item_id}`, `DELETE /service-carts/{cart_id}/items/{item_id}`.

## Checkout de cita y anticipo

El checkout del carrito crea la cita y prepara el pago anticipado sin depender todavia de Stripe real:

| Elemento | Uso |
| --- | --- |
| `deposit_percentage` | Porcentaje seleccionado por el usuario; solo se acepta `30` o `50` |
| `appointment_payment_requests` | Guarda solicitud de pago con total, anticipo, proveedor `stripe`, estado `pending` y `payment_link` provisional |
| `purchase_tickets` | Ticket interno de compra asociado a la cita y a la solicitud de pago |
| `app_notifications` | Notificacion interna enviada al usuario para mostrar el ticket dentro de la app |

Endpoint destacado: `POST /service-carts/{cart_id}/checkout`.

## Orden de trabajo y progreso

Cuando el usuario confirma el carrito, el backend crea una orden de trabajo operativa:

| Elemento | Uso |
| --- | --- |
| `work_orders.status` | Inicia en `received`; el taller la acepta con `POST /work-orders/{order_id}/accept` |
| `work_order_tasks` | Cada servicio del carrito se convierte en una tarea con estado `pending`, `in_progress` o `done` |
| `workshop_notifications` | Notifica al administrador/encargado del taller cuando se crea una orden |
| `app_notifications` | Notifica al cliente cuando la orden es aceptada o cambia el avance de un servicio |
| `progress_percent` | Avance visible para el cliente en `GET /work-orders/{order_id}` |

Endpoints destacados: `POST /work-orders/{order_id}/accept`, `PATCH /work-orders/{order_id}/tasks/{task_id}/status`, `GET /workshops/{workshop_id}/notifications`.

Estados de orden disponibles: `received`, `diagnosis`, `awaiting_approval`, `approved`, `in_progress`, `ready`, `delivered`, `cancelled`.

## Panel administrativo, historial y reportes

El backend expone datos agregados para el panel del taller y para reportes:

| Endpoint | Uso |
| --- | --- |
| `GET /admin/dashboard` | Totales rapidos: citas pendientes, ordenes recibidas, activas, listas, notificaciones no leidas, pagos pendientes e ingreso estimado |
| `GET /reports/workshops` | Reporte por taller y periodo con citas, ordenes, ingresos estimados, anticipos pendientes, pagos y servicios mas solicitados |
| `GET /vehicles/{vehicle_id}/history` | Historial completo del vehiculo: recepciones, citas, ordenes, recomendaciones, solicitudes de pago y tickets |
| `GET /me/notifications/unread-count` | Contador de notificaciones no leidas para badges del cliente |
| `PATCH /me/notifications/read-all` | Marca todas las notificaciones del cliente como leidas |
| `GET /workshops/{workshop_id}/notifications/unread-count` | Contador de notificaciones no leidas para el panel del taller |
| `PATCH /workshops/{workshop_id}/notifications/read-all` | Marca todas las notificaciones del taller como leidas |

## Siguiente incremento sugerido

1. Unificar el contrato con TallerPlusWEB y completar recepcion, activacion y permisos por taller, segun [auditoria de sincronizacion](auditoria_sincronizacion.md).
2. Conectar Stripe real mediante checkout session y webhooks.
3. Agregar carga real de imagenes para evidencias y fotos de taller.
4. Agregar exportacion PDF/CSV para reportes administrativos.
5. Definir permisos si cada taller tendra su propio personal administrador.
