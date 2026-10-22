from test_integration import ServiceFixture
import httpx
from services.api_gateway import app as gateway
from services.api_gateway.web import BrowserRoute
from services.common.database import connect
from services.customer_service import app as customers
from services.identity_service import app as identity

ORIGIN = {'Origin': 'http://localhost:5173'}

class CustomerSelfRegistrationTests(ServiceFixture):
    def setUp(self):
        super().setUp()
        BrowserRoute.limits.clear()
        self.payload = {'nombre': ' Ana Conductora ', 'telefono': '222 555 6677',
                        'email': ' ANA@EXAMPLE.TEST ', 'password': 'UnaClaveSegura123!'}

    def web(self, method, path, body=None, expected=200):
        return self.request(method, '/api' + path, ORIGIN, body, expected)

    def counts(self):
        with connect(identity.DB_PATH) as db:
            users = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        with connect(customers.DB_PATH) as db:
            return users, db.execute('SELECT COUNT(*) FROM customers').fetchone()[0], db.execute('SELECT COUNT(*) FROM vehicles').fetchone()[0]

    def test_register_without_workshop_vehicle_or_activation_and_login_after_logout(self):
        data = self.web('POST', '/auth/customers', self.payload, 201)
        user = data['user']
        self.assertEqual(user['role'], 'user')
        self.assertEqual(user['estado'], 'activo')
        self.assertEqual(user['email'], 'ana@example.test')
        self.assertEqual(user['nombre'], 'Ana Conductora')
        self.assertEqual(data['vehicles'], [])
        self.assertEqual(data['orders'], [])
        self.assertNotIn('access_token', data)
        token = self.client.cookies.get('tallerplus_session')
        self.assertTrue(token)
        with connect(identity.DB_PATH) as db:
            stored = db.execute('SELECT * FROM users WHERE id=?', (user['uid'],)).fetchone()
            self.assertNotEqual(stored['password_hash'], self.payload['password'])
            self.assertIsNone(stored['registration_workshop_id'])
            self.assertIsNone(stored['primary_vehicle_id'])
            self.assertEqual(db.execute('SELECT * FROM activations WHERE user_id=?', (user['uid'],)).fetchall(), [])
        self.assertEqual(self.web('GET', '/auth/session')['user']['uid'], user['uid'])
        self.web('POST', '/auth/logout', {})
        self.web('GET', '/auth/session', expected=401)
        logged = self.web('POST', '/auth/login', {'type': 'cliente', 'telefono': '2225556677', 'password': self.payload['password']})
        self.assertEqual(logged['user']['uid'], user['uid'])

    def test_reject_duplicates_invalid_data_and_privilege_fields_without_partial_records(self):
        self.web('POST', '/auth/customers', self.payload, 201)
        before = self.counts()
        self.web('POST', '/auth/customers', self.payload, 409)
        self.web('POST', '/auth/customers', {**self.payload, 'telefono': '2225556688'}, 409)
        for override in [{'nombre': ' '}, {'telefono': '123'}, {'email': 'invalid'}, {'password': 'short'}, {'role': 'admin'}]:
            self.web('POST', '/auth/customers', {**self.payload, **override}, 400)
        self.assertEqual(self.counts(), before)

    def test_customer_failure_removes_provisional_identity(self):
        before = self.counts()
        original = self.transports[gateway.CUSTOMERS_SERVICE_URL]
        async def fail_profile(request):
            if request.url.path == '/internal/web/customers/self-register':
                return httpx.Response(503, json={'detail': 'Injected failure'})
            return await original.handle_async_request(request)
        self.transports[gateway.CUSTOMERS_SERVICE_URL] = httpx.MockTransport(fail_profile)
        self.web('POST', '/auth/customers', self.payload, 503)
        self.assertEqual(self.counts(), before)
