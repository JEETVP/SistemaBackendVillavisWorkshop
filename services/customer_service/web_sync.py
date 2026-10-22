"""Owner-scoped vehicle writes backed by canonical customer SQL tables."""
import json
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from services.common.database import Connection, IntegrityError, table_columns, write_lock, connect
from services.common.internal import require_service_token
from services.common.time import utc_now_iso
from services.common.web_schemas import WebVehicle
from services.common.sync_contracts import InternalOperation, Mileage, Fuel, parse

def create_router(db_path):
    router = APIRouter(prefix='/internal/web/sync', dependencies=[Depends(require_service_token)])

    @router.post('/vehicles')
    def register(payload: InternalOperation):
        actor = payload.actor
        if actor.get('role') != 'client' or not actor.get('customer_id'):
            raise HTTPException(403, 'Solo el conductor puede registrar sus vehículos.')
        vehicle = parse(WebVehicle, payload.data)
        extra = {'cilindros': vehicle.cilindros, 'combustible': vehicle.combustible, 'kilometraje': vehicle.kilometraje,
                 'registradoPor': actor['id'], **({'foto': vehicle.foto} if vehicle.foto else {})}
        id = f'vehiculo-{uuid4()}'
        with connect(db_path()) as db:
            try:
                db.execute('INSERT INTO vehicles (id, customer_id, plate, vin, brand, model, year, color, owner_name, created_at, web_details) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (id, actor['customer_id'], vehicle.placas or None, vehicle.numeroSerie, vehicle.marca, vehicle.modelo, vehicle.anio, vehicle.color, actor['name'], utc_now_iso(), json.dumps(extra)))
            except IntegrityError as error:
                raise HTTPException(409, 'Ya existe un vehículo con estas placas o VIN.') from error
            return dict(db.execute('SELECT * FROM vehicles WHERE id=%s', (id,)).fetchone())

    @router.post('/vehicles/{vehicle_id}/{action}')
    def update(vehicle_id: str, action: str, payload: InternalOperation):
        actor = payload.actor
        if actor.get('role') != 'client':
            raise HTTPException(403, 'Solo el conductor puede actualizar su vehículo.')
        model = parse(Mileage if action == 'mileage' else Fuel, payload.data) if action in ('mileage', 'fuel') else None
        if model is None:
            raise HTTPException(404, 'Operación no disponible.')
        with connect(db_path()) as db:
            write_lock(db)
            row = db.execute('SELECT * FROM vehicles WHERE id=%s AND customer_id=%s', (vehicle_id, actor.get('customer_id'))).fetchone()
            if not row:
                raise HTTPException(403, 'No tienes acceso a este vehículo.')
            extra = json.loads(row['web_details'] or '{}')
            records = extra.setdefault('cargas' if action == 'mileage' else 'combustibleRegistros', [])
            if any(item['id'] == model.operationId for item in records):
                return dict(row)
            previous = extra.get('kilometraje', 0)
            if action == 'mileage':
                total = previous + model.kilometros
                if total > 10_000_000:
                    raise HTTPException(422, 'El kilometraje total supera el límite permitido.')
                records.append({'id': model.operationId, 'fecha': utc_now_iso(), 'kilometros': model.kilometros, 'kilometrajeAnterior': previous, 'kilometrajeTotal': total})
            else:
                if extra.get('combustible') == 'Eléctrico':
                    raise HTTPException(422, 'Este vehículo no utiliza combustible.')
                if model.kilometraje < previous or (records and model.kilometraje <= records[-1]['kilometraje']):
                    raise HTTPException(422, 'La lectura del odómetro no puede disminuir y debe superar la carga anterior.')
                total = model.kilometraje
                records.append({'id': model.operationId, 'fecha': utc_now_iso(), 'kilometraje': total, 'litros': model.litros, 'tanqueLleno': model.tanqueLleno})
            extra['kilometraje'] = total
            db.execute('UPDATE vehicles SET web_details=%s WHERE id=%s', (json.dumps(extra), vehicle_id))
            return dict(db.execute('SELECT * FROM vehicles WHERE id=%s', (vehicle_id,)).fetchone())
    return router
