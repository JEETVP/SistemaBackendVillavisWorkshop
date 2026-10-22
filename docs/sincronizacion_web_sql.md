# Sincronización web con SQL

La web TallerPlusWEB usa la sesión HttpOnly del gateway y las bases SQLite de identidad, clientes y taller. No usa MongoDB. Los módulos de configuración, personal, catálogo, solicitudes, cotizaciones, autorización, forma de pago, avances, fotos, registro independiente de vehículos, kilometraje, combustible y favoritos tienen escrituras en servidor.

`services/*/web_sync.py` implementa los adaptadores SQL. `services/common/sync_contracts.py` valida los contratos. Las rutas internas requieren el token de servicio; el navegador nunca puede enviar su propia identidad efectiva. El gateway obtiene el actor de la sesión y devuelve `{result, snapshot}` después de cada operación.

Las tablas nuevas se crean durante el arranque sin eliminar los registros existentes. El catálogo conserva las referencias canónicas al eliminar mediante una marca; los precios por variante se guardan en centavos y se reflejan en los importes canónicos. Las órdenes mantienen tareas y totales canónicos además de los detalles por etapa en SQL. Los historiales del vehículo viven en `vehicles.web_details`; favoritos y configuración tienen tablas propias.

El encargado administra el personal de su taller. Las contraseñas se guardan con hash en identidad. Los perfiles ausentes se desactivan y sus sesiones dejan de ser válidas. La configuración coordina la actualización de personal con un registro interno de compensación; si falla la escritura del perfil del taller, revierte los perfiles que preparó.

Los administrativos gestionan cotización y avance. El personal técnico solo actualiza tareas y fotos de diagnóstico o servicio de su propio taller y técnico asignado. El conductor autoriza únicamente sus órdenes y puede seleccionar servicios y efectivo o transferencia. Esa selección no procesa ni confirma un cobro.

El frontend sustituye su vista local por la del servidor después de guardar, cada diez segundos y al recuperar el foco. Versiones anteriores a una escritura no reemplazan la vista actual. Las operaciones de orden admiten `expectedUpdatedAt` y rechazan versiones antiguas. Kilometraje y combustible admiten identificadores de operación para evitar repetir una carga al reintentar.

Los datos que solo existían en localStorage no se importan automáticamente; el frontend conserva una copia anterior en IndexedDB. Las fotos por etapa se guardan como data URL en SQL; no se ha incorporado un almacén de objetos ni un proceso de eliminación automática de fotos.

Ejecutar `.venv/Scripts/python.exe -m unittest discover -s tests -v`. `tests/test_web_sync.py` usa SQLite aislado y los cuatro servicios reales mediante transportes ASGI, con sesiones independientes. Verifica el ciclo completo de una orden, permisos, cargas repetidas, favoritos, importación atómica de catálogo y compensación de personal.
