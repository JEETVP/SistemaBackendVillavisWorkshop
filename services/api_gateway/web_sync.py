"""Browser mutations: identity comes from the HttpOnly session, never request fields."""
import json
from fastapi import APIRouter, Depends, HTTPException
from services.common.sync_contracts import Configuration, parse
from services.api_gateway.web_mapping import web_order, web_vehicle, web_workshop, web_user

def create_router(call, actor, snapshot, workshop, customers, identity):
    router=APIRouter()

    async def wrapped(service,path,user,data):
        return await call('POST',service,'/internal/web/sync'+path,{'actor':user,'data':data})

    async def reply(user,result):
        return {'result':result,'snapshot':await snapshot(user)}

    @router.post('/workshop/configuration')
    async def configure(data: dict, user=Depends(actor)):
        config=parse(Configuration,data)
        rows=await call('GET',workshop,'/internal/web/workshops')
        if not any(row['id']==user.get('workshop_id') and row.get('owner_id')==user['id'] for row in rows):
            raise HTTPException(403,'Solo el encargado puede configurar su taller.')
        token=None
        if config.complete:
            token=(await wrapped(identity,'/staff',user,data))['rollbackToken']
        try:
            result=await wrapped(workshop,'/configuration',user,data)
        except HTTPException:
            if token:
                await call('POST',identity,f'/internal/web/sync/staff/{token}/rollback',{})
            raise
        if token:
            await call('POST',identity,f'/internal/web/sync/staff/{token}/commit',{})
        return await reply(user,result)

    @router.post('/workshop/catalog/{action}')
    async def catalog(action: str,data: dict,user=Depends(actor)):
        return await reply(user,await wrapped(workshop,f'/catalog/{action}',user,data))

    @router.post('/favorites')
    async def favorite(data: dict,user=Depends(actor)):
        result=await wrapped(workshop,'/favorites',user,data)
        rows=await call('GET',workshop,'/internal/web/workshops')
        result=web_workshop(next(row for row in rows if row['id']==result['id']))
        return await reply(user,result)

    @router.post('/vehicles')
    async def register_vehicle(data: dict,user=Depends(actor)):
        result=await wrapped(customers,'/vehicles',user,data)
        return await reply(user,web_vehicle(result,user['id']))

    @router.post('/vehicles/{vehicle_id}/{action}')
    async def update_vehicle(vehicle_id: str,action: str,data: dict,user=Depends(actor)):
        if action not in ('mileage','fuel'):
            raise HTTPException(404,'Operación no disponible.')
        result=await wrapped(customers,f'/vehicles/{vehicle_id}/{action}',user,data)
        return await reply(user,web_vehicle(result,user['id']))

    @router.post('/orders')
    async def create_order(data: dict,user=Depends(actor)):
        if user.get('role')!='client':
            raise HTTPException(403,'Solo el conductor puede solicitar un servicio.')
        vehicles=await call('POST',customers,'/internal/web/vehicles/lookup',{'customer_id':user['customer_id']})
        vehicle=next((v for v in vehicles if v['id']==data.get('vehiculoId')),None)
        if not vehicle:
            raise HTTPException(403,'Selecciona un vehículo propio.')
        result=await wrapped(workshop,'/orders',user,{**data,'vehicle':vehicle})
        return await reply(user,web_order(result,user['id'],''))

    @router.post('/orders/{order_id}/{action}')
    async def update_order(order_id: str,action: str,data: dict,user=Depends(actor)):
        result=await wrapped(workshop,f'/orders/{order_id}/{action}',user,data)
        # The canonical customer identity is resolved in the full snapshot.
        data_snapshot=await snapshot(user)
        mapped=next((v for v in data_snapshot['orders'] if v['id']==order_id),None)
        if not mapped:
            raise HTTPException(403,'La orden ya no está disponible para esta sesión.')
        return {'result':mapped,'snapshot':data_snapshot}
    return router
