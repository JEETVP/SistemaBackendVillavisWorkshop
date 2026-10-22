"""SQL persistence for workshop setup, catalogs, favorites and service workflow."""
import json
import re
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from services.common.database import Connection, IntegrityError, table_columns, write_lock, connect
from services.common.internal import require_service_token
from services.common.time import utc_now_iso
from services.common.sync_contracts import Configuration, CatalogService, QuoteService, InternalOperation, parse, transfer
from services.api_gateway.web_mapping import web_order, initial_progress

STAGES = ['Diagnóstico', 'Cotización', 'Autorización', 'Servicio', 'Entrega']

def init_schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS web_workshop_configuration (workshop_id TEXT PRIMARY KEY REFERENCES workshops(id), payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS web_favorites (customer_id TEXT NOT NULL, workshop_id TEXT NOT NULL REFERENCES workshops(id), PRIMARY KEY(customer_id, workshop_id))')
    columns = table_columns(db, "service_catalog")
    for name in ('web_service_id', 'web_payload'):
        if name not in columns:
            db.execute(f'ALTER TABLE service_catalog ADD COLUMN {name} TEXT')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_web_service_id ON service_catalog(workshop_id, web_service_id) WHERE web_service_id IS NOT NULL')

def manager(db, actor, workshop_id):
    row = db.execute('SELECT * FROM workshops WHERE id=%s AND active=1', (workshop_id,)).fetchone()
    if not row or actor.get('role') not in ('staff','admin') or actor.get('id') != row['owner_id'] or actor.get('workshop_id') != workshop_id:
        raise HTTPException(403, 'Solo el encargado puede modificar este taller.')
    return dict(row)

def mechanic(actor):
    return actor.get('web_cargo') == 'personal_taller' and actor.get('web_position') != 'Personal administrativo'

def order_manager(actor, workshop_id):
    if actor.get('role') not in ('staff','admin') or actor.get('workshop_id') != workshop_id or mechanic(actor):
        raise HTTPException(403, 'Solo el administrativo puede gestionar esta etapa.')

def catalog(db, workshop_id):
    rows = db.execute('SELECT * FROM service_catalog WHERE workshop_id=%s ORDER BY created_at,id', (workshop_id,)).fetchall()
    result = []
    for row in rows:
        if row['web_payload']:
            item = json.loads(row['web_payload'])
            if item.get('deleted'):
                continue
            item['disponible'] = bool(row['active'])
        else:
            variants = [{'id': f'variante-{n}', 'nombre': f'{n} cilindros', 'cilindros': n, 'precioCentavos': round(row[f'price_{n}_cyl'] * 100)} for n in (3,4,6,8)]
            item = {'id':row['id'], 'tallerId':workshop_id, 'nombre':row['name'], 'descripcion':row['description'] or '', 'disponible':bool(row['active']), 'moneda':'MXN', 'variantes':variants, 'precioCentavos':min(v['precioCentavos'] for v in variants), 'prioridad':{1:'Alta',2:'Media',3:'Baja'}.get(row['priority_rank'],'Media')}
        result.append(item)
    return result

def configuration(db, workshop_id):
    row = db.execute('SELECT payload FROM web_workshop_configuration WHERE workshop_id=%s', (workshop_id,)).fetchone()
    return json.loads(row['payload']) if row else None

def public_config(value):
    if not value or value.get('estado') != 'completa':
        return None
    data = value['datos']
    return {'estado':'completa', 'updatedAt':value['updatedAt'], 'datos':{**data, 'personal':[]}}

def sync_quote_tasks(db, order_id, services):
    # Canonical task and price records stay usable by the native SQL APIs.
    db.execute('DELETE FROM work_order_tasks WHERE work_order_id=%s AND id LIKE %s', (order_id, 'web-quote-%'))
    for index, service in enumerate(services):
        db.execute('INSERT INTO work_order_tasks (id,work_order_id,name,price,priority,status,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
            (f'web-quote-{order_id}-{index}',order_id,service['nombre'],service['precioCentavos']/100,{'Alta':'high','Media':'normal','Baja':'low'}.get(service.get('prioridad'),'normal'),'pending',utc_now_iso(),utc_now_iso()))

def create_router(db_path):
    router = APIRouter(prefix='/internal/web/sync', dependencies=[Depends(require_service_token)])

    @router.post('/snapshot')
    def snapshot(payload: InternalOperation):
        actor = payload.actor
        with connect(db_path()) as db:
            rows = db.execute('SELECT * FROM workshops WHERE active=1').fetchall()
            own = actor.get('workshop_id')
            configurations = {}
            for row in rows:
                config = configuration(db,row['id'])
                if config:
                    if own == row['id']:
                        configurations[row['id']] = config
                    elif public_config(config):
                        configurations[row['id']] = public_config(config)
            catalogs = {row['id']:catalog(db,row['id']) for row in rows}
            favorite_ids = [row['workshop_id'] for row in db.execute('SELECT workshop_id FROM web_favorites WHERE customer_id=%s', (actor.get('customer_id') or '',))]
            return {'configurations':configurations, 'catalogs':catalogs, 'favoriteIds':favorite_ids}

    @router.post('/configuration')
    def save_config(payload: InternalOperation):
        config = parse(Configuration,payload.data)
        actor = payload.actor
        with connect(db_path()) as db:
            write_lock(db)
            manager(db,actor,actor.get('workshop_id'))
            previous = configuration(db,actor['workshop_id'])
            if not config.complete and previous and previous['estado'] == 'completa':
                raise HTTPException(409,'El taller ya tiene un perfil completo. Guarda la edición completa.')
            value = {'estado':'completa' if config.complete else 'borrador','datos':config.datos.model_dump(),'updatedAt':utc_now_iso()}
            db.execute('INSERT INTO web_workshop_configuration VALUES (%s,%s) ON CONFLICT(workshop_id) DO UPDATE SET payload=excluded.payload', (actor['workshop_id'],json.dumps(value,ensure_ascii=False)))
            return value

    @router.post('/catalog/{action}')
    def save_catalog(action: str, payload: InternalOperation):
        actor,data=payload.actor,payload.data
        if action not in ('save','import','remove'):
            raise HTTPException(404,'Operación no disponible.')
        raw=data.get('services',[])
        if not isinstance(raw,list):
            raise HTTPException(422,'Selecciona una lista de servicios válida.')
        models = [parse(CatalogService,item) for item in raw] if action != 'remove' else []
        if action == 'save' and len(models) != 1 or action == 'import' and not 1 <= len(models) <= 500:
            raise HTTPException(422,'Selecciona servicios válidos.')
        with connect(db_path()) as db:
            write_lock(db)
            wid=actor.get('workshop_id')
            manager(db,actor,wid)
            current=catalog(db,wid)
            if action=='remove':
                # Keep canonical references intact; remove web visibility via a tombstone.
                row=db.execute('SELECT id FROM service_catalog WHERE workshop_id=%s AND (web_service_id=%s OR (web_service_id IS NULL AND id=%s))',(wid,data.get('id'),data.get('id'))).fetchone()
                if not row:
                    raise HTTPException(404,'Servicio no encontrado.')
                db.execute("UPDATE service_catalog SET active=0, web_payload=jsonb_set(COALESCE(web_payload,'{}')::jsonb, '{deleted}', 'true'::jsonb)::text WHERE id=%s",(row['id'],))
            else:
                for model in models:
                    item=model.model_dump(exclude_none=True)
                    if model.tallerId != wid:
                        raise HTTPException(403,'El servicio pertenece a otro taller.')
                    match=next((v for v in current if v['id']==model.id),None)
                    duplicate=next((v for v in current if v['id']!=model.id and v['nombre'].casefold()==model.nombre.casefold()),None)
                    if action=='import' and (match or duplicate):
                        continue
                    if duplicate:
                        raise HTTPException(409,'Ya existe un servicio con este nombre.')
                    row=db.execute('SELECT id FROM service_catalog WHERE workshop_id=%s AND (web_service_id=%s OR (web_service_id IS NULL AND id=%s))',(wid,model.id,model.id)).fetchone()
                    cid=row['id'] if row else 'catalog-web-'+str(uuid4())
                    prices={n:next((v.precioCentavos/100 for v in model.variantes if v.cilindros==n),model.precioCentavos/100) for n in (3,4,6,8)}
                    db.execute('INSERT INTO service_catalog (id,workshop_id,name,description,priority_rank,price_3_cyl,price_4_cyl,price_6_cyl,price_8_cyl,base_price,active,created_at,web_service_id,web_payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,priority_rank=excluded.priority_rank,price_3_cyl=excluded.price_3_cyl,price_4_cyl=excluded.price_4_cyl,price_6_cyl=excluded.price_6_cyl,price_8_cyl=excluded.price_8_cyl,base_price=excluded.base_price,active=excluded.active,web_service_id=excluded.web_service_id,web_payload=excluded.web_payload',
                        (cid,wid,model.nombre,model.descripcion,{'Alta':1,'Media':2,'Baja':3}.get(model.prioridad,2),prices[3],prices[4],prices[6],prices[8],model.precioCentavos/100,int(model.disponible),utc_now_iso(),model.id,json.dumps(item,ensure_ascii=False)))
                    current=[v for v in current if v['id']!=model.id]+[item]
            return [v for v in catalog(db,wid) if not v.get('deleted')]

    @router.post('/favorites')
    def favorite(payload: InternalOperation):
        actor,data=payload.actor,payload.data
        if actor.get('role')!='client':
            raise HTTPException(403,'Solo un conductor puede guardar talleres.')
        value=str(data.get('id','')).strip().removeprefix('taller-').lower()
        if not re.fullmatch(r'[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}',value):
            raise HTTPException(422,'Ingresa un UUID de taller válido.')
        with connect(db_path()) as db:
            rows=db.execute('SELECT id FROM workshops WHERE active=1').fetchall()
            wid=next((row['id'] for row in rows if row['id'].removeprefix('taller-').lower()==value),None)
            if not wid:
                raise HTTPException(404,'No encontramos ese taller.')
            if data.get('remove') is True:
                db.execute('DELETE FROM web_favorites WHERE customer_id=%s AND workshop_id=%s',(actor['customer_id'],wid))
            else:
                db.execute('INSERT INTO web_favorites VALUES (%s,%s) ON CONFLICT DO NOTHING',(actor['customer_id'],wid))
        return {'id':wid}

    @router.post('/orders')
    def create_order(payload: InternalOperation):
        actor,data=payload.actor,payload.data
        if actor.get('role')!='client':
            raise HTTPException(403,'Solo el conductor puede solicitar un servicio.')
        wid=data.get('tallerId')
        # The gateway supplies an owner-checked canonical vehicle, never frontend data.
        vehicle=data.get('vehicle',{})
        if vehicle.get('customer_id')!=actor.get('customer_id'):
            raise HTTPException(403,'Selecciona un vehículo propio.')
        try:
            datetime.fromisoformat(str(data['fechaInicio']).replace('Z','+00:00'))
        except (KeyError, ValueError):
            raise HTTPException(422,'Selecciona una fecha de ingreso válida.')
        with connect(db_path()) as db:
            write_lock(db)
            if not db.execute('SELECT id FROM workshops WHERE id=%s AND active=1',(wid,)).fetchone() or not db.execute('SELECT 1 FROM web_favorites WHERE customer_id=%s AND workshop_id=%s',(actor['customer_id'],wid)).fetchone():
                raise HTTPException(403,'Selecciona uno de tus talleres guardados.')
            if db.execute("SELECT id FROM work_orders WHERE vehicle_id=%s AND status NOT IN ('delivered','cancelled')",(vehicle['id'],)).fetchone():
                raise HTTPException(409,'Este auto ya tiene una solicitud activa.')
            choices=data.get('choices')
            if not isinstance(choices,dict) or not 1<=len(choices)<=30:
                raise HTTPException(422,'Selecciona entre 1 y 30 servicios.')
            services=[]
            for sid,vid in choices.items():
                service=next((v for v in catalog(db,wid) if v['id']==sid and v['disponible'] and not v.get('deleted')),None)
                variant=next((v for v in (service or {}).get('variantes',[]) if v['id']==vid),None)
                cylinders=json.loads(vehicle.get('web_details') or '{}').get('cilindros',4)
                if not service or not variant or variant.get('cilindros') not in (None,cylinders):
                    raise HTTPException(409,'Un servicio o su precio ya no está disponible para este auto.')
                services.append({'servicioId':sid,'nombre':service['nombre'],'descripcion':service['descripcion'],'varianteId':vid,'varianteNombre':variant['nombre'],'precioCentavos':variant['precioCentavos'],**({'prioridad':service['prioridad']} if service.get('prioridad') else {})})
            now=utc_now_iso(); oid='sol-'+str(uuid4())
            extra={'progreso':initial_progress(now),'servicios':services,'fechaInicio':data['fechaInicio'],'materiales':[]}
            db.execute("INSERT INTO work_orders (id,workshop_id,customer_id,vehicle_id,description,priority,status,estimated_total,created_at,updated_at,web_details) VALUES (%s,%s,%s,%s,%s,'normal','diagnosis',%s,%s,%s,%s)",(oid,wid,actor['customer_id'],vehicle['id'],' · '.join(v['nombre'] for v in services),sum(v['precioCentavos'] for v in services)/100,now,now,json.dumps(extra,ensure_ascii=False)))
            sync_quote_tasks(db,oid,services)
            return dict(db.execute('SELECT * FROM work_orders WHERE id=%s',(oid,)).fetchone())

    @router.post('/orders/{order_id}/{action}')
    def update_order(order_id: str, action: str, payload: InternalOperation):
        actor,data=payload.actor,payload.data
        with connect(db_path()) as db:
            write_lock(db)
            row=db.execute('SELECT * FROM work_orders WHERE id=%s',(order_id,)).fetchone()
            if not row:
                raise HTTPException(404,'Orden no encontrada.')
            row=dict(row)
            is_client=actor.get('role')=='client'
            if is_client:
                if row['customer_id']!=actor.get('customer_id') or action!='authorize':
                    raise HTTPException(403,'No tienes permiso para modificar esta orden.')
            elif actor.get('workshop_id')!=row['workshop_id']:
                raise HTTPException(403,'La orden pertenece a otro taller.')
            if row['status'] in ('delivered','cancelled'):
                raise HTTPException(409,'La orden ya está cerrada.')
            if data.get('expectedUpdatedAt') and data['expectedUpdatedAt']!=row['updated_at']:
                raise HTTPException(409,'La orden cambió. Actualiza y vuelve a intentarlo.')
            extra=json.loads(row['web_details'] or '{}')
            order=web_order(row,row['customer_id'],'')
            progress=order['progreso']; current=progress['etapa']; index=STAGES.index(current)
            if mechanic(actor) and (current not in ('Diagnóstico','Servicio') or progress.get('tecnicoId') not in (None,actor['id']) or action not in ('tasks','photos')):
                raise HTTPException(403,'Solo puedes actualizar las tareas y fotos de tus órdenes asignadas.')
            if current=='Autorización' and action not in ('authorize','transfer'):
                raise HTTPException(409,'En espera de autorización del conductor.')
            services=extra.get('servicios',[])
            if action=='quote':
                order_manager(actor,row['workshop_id'])
                if current!='Cotización':
                    raise HTTPException(409,'Solo puedes cotizar en Cotización.')
                raw=data.get('services',[])
                if not isinstance(raw,list) or not 1<=len(raw)<=30:
                    raise HTTPException(422,'Completa entre 1 y 30 servicios.')
                updated=[parse(QuoteService,v).model_dump(exclude_none=True) for v in raw]
                if len({v['servicioId'] for v in updated})!=len(updated):
                    raise HTTPException(422,'No repitas servicios.')
                if any(not any(v['servicioId']==s['servicioId'] and v['varianteId']==s['varianteId'] and v['nombre']==s['nombre'] for v in updated) for s in services):
                    raise HTTPException(422,'Conserva los servicios iniciales de la orden.')
                extra['servicios']=updated
                extra['numeroTransferencia']=transfer(data.get('numeroTransferencia',extra.get('numeroTransferencia','')))
                sync_quote_tasks(db,order_id,updated)
            elif action=='transfer':
                order_manager(actor,row['workshop_id'])
                if current not in ('Cotización','Autorización'):
                    raise HTTPException(409,'Actualiza el número en Cotización o Autorización.')
                extra['numeroTransferencia']=transfer(data.get('numeroTransferencia',''))
            elif action=='tasks':
                if data.get('expectedStage')!=current:
                    raise HTTPException(409,'La etapa cambió. Vuelve a abrir la orden.')
                completed=data.get('completed')
                tasks=progress['etapas'][index]['tareas']
                if not isinstance(completed,list) or len(completed)!=len(tasks) or any(type(v)!=bool for v in completed):
                    raise HTTPException(422,'Revisa las tareas de la etapa.')
                for task,done in zip(tasks,completed):
                    task['completada']=done
            elif action=='photos':
                if data.get('stage')!=current or current=='Cotización':
                    raise HTTPException(409,'Las fotos deben corresponder a la etapa actual.')
                photos=data.get('photos',[])
                target=extra.setdefault('fotos',{}).setdefault(current,[])
                if not photos or len(target)+len(photos)>12:
                    raise HTTPException(422,'Puedes adjuntar hasta 12 fotos por etapa.')
                for photo in photos:
                    if not isinstance(photo,dict) or not isinstance(photo.get('url'),str) or len(photo['url'])>600_000 or not re.fullmatch(r'data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/]+={0,2}',photo['url']) or not str(photo.get('titulo','')).strip():
                        raise HTTPException(422,'Selecciona fotos JPG, PNG o WebP válidas.')
                    target.append({'id':str(uuid4()),'url':photo['url'],'titulo':str(photo['titulo'])[:120],'autor':actor['name'],'fecha':utc_now_iso()})
            elif action=='advance':
                order_manager(actor,row['workshop_id'])
                if not all(v['completada'] for v in progress['etapas'][index]['tareas']):
                    raise HTTPException(409,'Completa las tareas antes de avanzar.')
                if current in ('Diagnóstico','Servicio') and not extra.get('fotos',{}).get(current):
                    raise HTTPException(409,'Adjunta fotos del proceso antes de avanzar.')
                if index==1 and not services:
                    raise HTTPException(409,'Guarda una cotización antes de enviarla al conductor.')
                if index==4:
                    extra['finalizadaEn']=utc_now_iso(); row['status']='delivered'
                else:
                    progress['etapa']=STAGES[index+1]
                    row['status']={1:'diagnosis',2:'awaiting_approval',3:'in_progress',4:'ready'}[index+1]
            elif action=='authorize':
                if not is_client or current!='Autorización':
                    raise HTTPException(403,'Solo el conductor puede autorizar en esta etapa.')
                selected=data.get('selectedIds'); method=data.get('metodoPago')
                if not isinstance(selected,list) or not selected or any(type(v)!=str for v in selected) or len(set(selected))!=len(selected) or any(v not in [s['servicioId'] for s in services] for v in selected) or method not in ('transferencia','efectivo'):
                    raise HTTPException(422,'Selecciona servicios válidos y transferencia o efectivo.')
                extra['autorizacion']={'serviciosIds':selected,'metodoPago':method,'fecha':utc_now_iso()}
                for task in progress['etapas'][2]['tareas']:
                    task['completada']=True
                progress['etapa']='Servicio'; row['status']='in_progress'
                sync_quote_tasks(db,order_id,[s for s in services if s['servicioId'] in selected])
            else:
                raise HTTPException(404,'Operación no disponible.')
            now=utc_now_iso(); progress['actualizado']=now; extra['progreso']=progress
            approved=extra.get('autorizacion',{}).get('serviciosIds')
            total=sum(v['precioCentavos'] for v in extra.get('servicios',[]) if approved is None or v['servicioId'] in approved)/100
            db.execute('UPDATE work_orders SET status=%s, estimated_total=%s, updated_at=%s, web_details=%s WHERE id=%s',(row['status'],total,now,json.dumps(extra,ensure_ascii=False),order_id))
            return dict(db.execute('SELECT * FROM work_orders WHERE id=%s',(order_id,)).fetchone())
    return router
