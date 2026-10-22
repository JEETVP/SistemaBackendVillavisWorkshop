from test_integration import ServiceFixture
from fastapi.testclient import TestClient
from services.api_gateway import app as gateway
from services.common.database import connect
from services.workshop_service import app as workshop
import httpx

ORIGIN={'Origin':'http://localhost:5173'}

class BrowserSyncTests(ServiceFixture):
    def setUp(self):
        super().setUp()
        from services.api_gateway.web import BrowserRoute
        BrowserRoute.limits.clear()
        self.owner=self.stack.enter_context(TestClient(gateway.app))
        self.driver=self.stack.enter_context(TestClient(gateway.app))
        self.mechanic=self.stack.enter_context(TestClient(gateway.app))
        self.other=self.stack.enter_context(TestClient(gateway.app))
        self.registration={'nombre':'Taller sincronizado','encargadoNombre':'Ana Encargada','email':'sync-owner@example.test','password':'ClaveOwner123!', 'ubicacion':{'direccion':'Calle 20','ciudad':'Puebla','estado':'Puebla','codigoPostal':'72000'}}
        registered=self.web(self.owner,'/auth/workshops',self.registration,201)
        self.wid=registered['user']['tallerId']; self.uid=registered['user']['uid']
        self.config={'datos':{'descripcion':'Taller de pruebas','telefono':'2221234567','foto':'data:image/png;base64,YWJj',
            'personal':[{'id':self.uid,'nombre':'Ana Encargada','email':self.registration['email'],'puesto':'Personal administrativo','especialidad':''},
                {'id':'sync-mechanic','nombre':'Luis Mecánico','email':'sync-mechanic@example.test','puesto':'Mecánico','especialidad':'Motor'}],
            'servicios':[],'puestosTrabajo':3,'vehiculosPorDia':10,'equipamiento':'Herramientas','horario':{'dias':['Lunes'],'apertura':'09:00','cierre':'18:00'}},'complete':True,'passwords':{'sync-mechanic':'ClaveMecanico123!'}}
        self.web(self.owner,'/workshop/configuration',self.config)
        self.service={'id':'general','tallerId':self.wid,'nombre':'Servicio general','descripcion':'Aceite y filtro','disponible':True,'moneda':'MXN','prioridad':'Media',
            'variantes':[{'id':'4','nombre':'4 cilindros','cilindros':4,'precioCentavos':185000}]}
        self.web(self.owner,'/workshop/catalog/save',{'services':[self.service]})
        self.web(self.driver,'/auth/customers',{'nombre':'Miguel','telefono':'2229988776','email':'sync-driver@example.test','password':'ClaveDriver123!'},201)
        self.vehicle={'marca':'Mazda','modelo':'3','anio':2022,'placas':'SYN-123','numeroSerie':'1HGCM82633A123456','cilindros':4,'combustible':'Gasolina','kilometraje':1000,'color':'Rojo'}
        self.vid=self.web(self.driver,'/vehicles',self.vehicle)['result']['id']
        self.web(self.driver,'/favorites',{'id':self.wid})
        self.web(self.mechanic,'/auth/login',{'type':'taller','email':'sync-mechanic@example.test','password':'ClaveMecanico123!'})
        self.web(self.other,'/auth/workshops',{**self.registration,'email':'sync-other@example.test'},201)

    def web(self,client,path,data=None,status=200):
        response=client.request('GET' if data is None else 'POST','/api'+path,headers=ORIGIN,json=data)
        self.assertEqual(response.status_code,status,f'{path}: {response.text}')
        return response.json()

    def order(self):
        return self.web(self.driver,'/orders',{'tallerId':self.wid,'vehiculoId':self.vid,'fechaInicio':'2026-10-20T10:00:00-06:00','choices':{'general':'4'}})['result']

    def test_independent_sessions_share_profile_catalog_vehicle_histories_and_favorites(self):
        driver=self.web(self.driver,'/auth/session')
        self.assertEqual(driver['configurations'][self.wid]['datos']['personal'],[])
        self.assertNotIn('cuentas',driver['configurations'][self.wid])
        self.assertEqual(driver['catalogs'][self.wid][0]['variantes'][0]['precioCentavos'],185000)
        self.assertEqual(driver['favoriteIds'],[self.wid])
        self.assertEqual(len(driver['vehicles']),1)
        self.assertEqual(self.web(self.mechanic,'/auth/session')['user']['puesto'],'Mecánico')
        self.web(self.driver,f'/vehicles/{self.vid}/mileage',{'kilometros':150,'operationId':'mileage-once'})
        repeated=self.web(self.driver,f'/vehicles/{self.vid}/mileage',{'kilometros':150,'operationId':'mileage-once'})
        self.assertEqual(repeated['result']['kilometraje'],1150)
        self.assertEqual(len(repeated['result']['cargas']),1)
        self.web(self.driver,f'/vehicles/{self.vid}/fuel',{'kilometraje':1200,'litros':30,'tanqueLleno':True,'operationId':'fuel-1'})
        self.web(self.driver,f'/vehicles/{self.vid}/fuel',{'kilometraje':1250,'litros':10,'tanqueLleno':False,'operationId':'fuel-2'})
        self.web(self.driver,f'/vehicles/{self.vid}/fuel',{'kilometraje':1300,'litros':20,'tanqueLleno':True,'operationId':'fuel-3'})
        self.web(self.driver,f'/vehicles/{self.vid}/fuel',{'kilometraje':900,'litros':20,'tanqueLleno':True,'operationId':'backwards'},422)
        fresh=self.stack.enter_context(TestClient(gateway.app))
        data=self.web(fresh,'/auth/login',{'type':'cliente','telefono':'2229988776','password':'ClaveDriver123!'})
        self.assertEqual(data['vehicles'][0]['kilometraje'],1300)
        self.assertEqual(len(data['vehicles'][0]['combustibleRegistros']),3)
        self.assertEqual(data['favoriteIds'],[self.wid])
        self.web(self.other,f'/vehicles/{self.vid}/mileage',{'kilometros':100,'operationId':'forbidden'},403)
        self.web(self.mechanic,'/workshop/catalog/save',{'services':[self.service]},403)
        self.web(self.other,'/workshop/catalog/save',{'services':[self.service]},403)
        self.web(self.driver,'/favorites',{'id':self.wid,'remove':True})
        self.assertEqual(self.web(fresh,'/auth/session')['favoriteIds'],[])

    def test_full_workflow_quote_authorization_payment_and_completion_shared_between_roles(self):
        order=self.order(); oid=order['id']
        self.web(self.driver,'/orders',{'tallerId':self.wid,'vehiculoId':self.vid,'fechaInicio':'2026-10-20','choices':{'general':'4'}},409)
        self.web(self.other,f'/orders/{oid}/tasks',{'completed':[True],'expectedStage':'Diagnóstico'},403)
        self.web(self.driver,f'/orders/{oid}/tasks',{'completed':[True],'expectedStage':'Diagnóstico'},403)
        self.web(self.mechanic,f'/orders/{oid}/tasks',{'completed':[True],'expectedStage':'Diagnóstico'})
        self.web(self.owner,f'/orders/{oid}/advance',{},409)
        photo={'url':'data:image/jpeg;base64,YWJj','titulo':'Revisión'}
        self.web(self.mechanic,f'/orders/{oid}/photos',{'stage':'Diagnóstico','photos':[photo]})
        self.web(self.owner,f'/orders/{oid}/advance',{})
        quoted=[{'servicioId':'general','nombre':'Servicio general','descripcion':'Aceite y filtro','varianteId':'4','varianteNombre':'4 cilindros','precioCentavos':190000,'prioridad':'Media'},
            {'servicioId':'frenos','nombre':'Frenos','descripcion':'Revisión de frenos','varianteId':'custom','varianteNombre':'Para este auto','precioCentavos':90000,'prioridad':'Alta'}]
        self.web(self.owner,f'/orders/{oid}/quote',{'services':quoted,'numeroTransferencia':'012345678901234567'})
        self.web(self.mechanic,f'/orders/{oid}/quote',{'services':quoted},403)
        self.web(self.owner,f'/orders/{oid}/tasks',{'completed':[True],'expectedStage':'Cotización'})
        self.web(self.owner,f'/orders/{oid}/advance',{})
        waiting=self.web(self.driver,'/auth/session')['orders'][0]
        self.assertEqual(waiting['progreso']['etapa'],'Autorización')
        self.assertEqual(waiting['numeroTransferencia'],'012345678901234567')
        self.assertEqual(waiting['servicios'][1]['prioridad'],'Alta')
        self.web(self.owner,f'/orders/{oid}/authorize',{'selectedIds':['general'],'metodoPago':'efectivo'},403)
        self.web(self.driver,f'/orders/{oid}/authorize',{'selectedIds':['missing'],'metodoPago':'efectivo'},422)
        self.web(self.driver,f'/orders/{oid}/authorize',{'selectedIds':['general'],'metodoPago':'efectivo','expectedUpdatedAt':'old'},409)
        self.web(self.driver,f'/orders/{oid}/authorize',{'selectedIds':['general'],'metodoPago':'efectivo'})
        shared=self.web(self.owner,'/auth/session')['orders'][0]
        self.assertEqual(shared['autorizacion']['serviciosIds'],['general'])
        self.assertEqual(shared['autorizacion']['metodoPago'],'efectivo')
        self.assertEqual(shared['progreso']['etapa'],'Servicio')
        with connect(workshop.DATABASE_URL) as db:
            self.assertEqual(next(iter(db.execute('SELECT estimated_total FROM work_orders WHERE id=%s',(oid,)).fetchone().values())),1900)
            self.assertEqual(next(iter(db.execute('SELECT COUNT(*) FROM work_order_tasks WHERE work_order_id=%s',(oid,)).fetchone().values())),1)
        self.web(self.mechanic,f'/orders/{oid}/tasks',{'completed':[True],'expectedStage':'Servicio'})
        self.web(self.mechanic,f'/orders/{oid}/photos',{'stage':'Servicio','photos':[photo]})
        self.web(self.owner,f'/orders/{oid}/advance',{})
        self.web(self.owner,f'/orders/{oid}/tasks',{'completed':[True],'expectedStage':'Entrega'})
        self.web(self.owner,f'/orders/{oid}/advance',{})
        finished=self.web(self.driver,'/auth/session')['orders'][0]
        self.assertEqual(finished['estado'],'Finalizada')
        self.assertTrue(finished['finalizadaEn'])
        self.assertEqual(len(finished['fotos']['Servicio']),1)
        self.web(self.owner,f'/orders/{oid}/advance',{},409)

    def test_catalog_import_is_atomic_and_deletion_removes_public_visibility(self):
        second={**self.service,'id':'second','nombre':'Segundo servicio'}
        invalid={**self.service,'id':'bad','nombre':'Incorrecto','variantes':[]}
        self.web(self.owner,'/workshop/catalog/import',{'services':[second,invalid]},422)
        self.assertEqual(len(self.web(self.driver,'/auth/session')['catalogs'][self.wid]),1)
        self.web(self.owner,'/workshop/catalog/import',{'services':[self.service,second]})
        self.web(self.owner,'/workshop/catalog/import',{'services':[second]})
        self.assertEqual(len(self.web(self.driver,'/auth/session')['catalogs'][self.wid]),2)
        self.web(self.owner,'/workshop/catalog/save',{'services':{}},422)
        self.web(self.owner,'/workshop/catalog/remove',{'id':'second'})
        self.assertEqual([v['id'] for v in self.web(self.driver,'/auth/session')['catalogs'][self.wid]],['general'])
        with connect(workshop.DATABASE_URL) as db:
            self.assertEqual(next(iter(db.execute('SELECT active FROM service_catalog WHERE web_service_id=%s AND workshop_id=%s',('second',self.wid)).fetchone().values())),0)

    def test_staff_removal_blocks_existing_sessions_and_configuration_failure_rolls_back_profiles(self):
        self.assertEqual(self.web(self.mechanic,'/auth/session')['user']['estado'],'activo')
        self.config['datos']['personal']=self.config['datos']['personal'][:1]
        self.config['passwords']={}
        original=self.transports[gateway.WORKSHOP_SERVICE_URL]
        async def fail_config(request):
            if request.url.path=='/internal/web/sync/configuration':
                return httpx.Response(503,json={'detail':'Injected failure'})
            return await original.handle_async_request(request)
        self.transports[gateway.WORKSHOP_SERVICE_URL]=httpx.MockTransport(fail_config)
        self.web(self.owner,'/workshop/configuration',self.config,503)
        self.assertEqual(self.web(self.mechanic,'/auth/session')['user']['estado'],'activo')
        self.transports[gateway.WORKSHOP_SERVICE_URL]=original
        self.web(self.owner,'/workshop/configuration',self.config)
        self.web(self.mechanic,'/auth/session',status=401)
        self.web(self.mechanic,'/auth/login',{'type':'taller','email':'sync-mechanic@example.test','password':'ClaveMecanico123!'},401)
