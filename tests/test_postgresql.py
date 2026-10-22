from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from psycopg import IntegrityError
from test_integration import ServiceFixture
from services.common.database import connect, pool_for
from services.identity_service import app as identity
from services.api_gateway import app as gateway


class PostgreSQLPersistenceTests(ServiceFixture):
    def test_transactions_rollback_and_pool_recovers_after_unique_constraint_error(self):
        url = identity.DATABASE_URL
        pool = pool_for(url)
        with self.assertRaises(RuntimeError):
            with connect(url) as db:
                db.execute("INSERT INTO users (id,name,role,created_at) VALUES ('rollback-only','Test','client','2026-10-22')")
                raise RuntimeError('abort')
        with connect(url) as db:
            self.assertIsNone(db.execute("SELECT id FROM users WHERE id='rollback-only'").fetchone())
        with self.assertRaises(IntegrityError):
            with connect(url) as db:
                db.execute("INSERT INTO users (id,name,role,created_at) VALUES ('duplicate-only','Test','client','2026-10-22')")
                db.execute("INSERT INTO users (id,name,role,created_at) VALUES ('duplicate-only','Test','client','2026-10-22')")
        with connect(url) as db:
            self.assertIsNone(db.execute("SELECT id FROM users WHERE id='duplicate-only'").fetchone())
            self.assertIn('PostgreSQL', db.execute('SELECT version() AS version').fetchone()['version'])
        self.assertIs(pool_for(url), pool)

    def test_simultaneous_mileage_retry_is_applied_exactly_once(self):
        browser = self.stack.enter_context(TestClient(gateway.app))
        origin = {'Origin':'http://localhost:5173'}
        registration = browser.post('/api/auth/customers',headers=origin,json={
            'nombre':'Prueba concurrente','telefono':'2224321234','email':'pg-concurrency@example.test','password':'ClavePrueba123!'
        })
        self.assertEqual(registration.status_code,201,registration.text)
        vehicle = browser.post('/api/vehicles',headers=origin,json={
            'marca':'Mazda','modelo':'3','anio':2022,'placas':'PG-123','numeroSerie':'1HGCM82633A123456','cilindros':4,
            'combustible':'Gasolina','kilometraje':1000,'color':'Rojo'
        })
        self.assertEqual(vehicle.status_code,200,vehicle.text)
        vehicle_id=vehicle.json()['result']['id']
        def retry(_):
            return browser.post(f'/api/vehicles/{vehicle_id}/mileage',headers=origin,json={'kilometros':100,'operationId':'same-concurrent-operation'})
        with ThreadPoolExecutor(max_workers=2) as workers:
            responses=list(workers.map(retry,range(2)))
        self.assertEqual([response.status_code for response in responses],[200,200])
        result=browser.get('/api/auth/session').json()['vehicles'][0]
        self.assertEqual(result['kilometraje'],1100)
        self.assertEqual(len(result['cargas']),1)
