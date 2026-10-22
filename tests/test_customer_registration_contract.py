import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from services.api_gateway.web import create_router, BrowserRoute

class CustomerRegistrationContractTests(unittest.TestCase):
    def setUp(self):
        BrowserRoute.limits.clear()
        self.calls = []
        self.fail_profile = False
        self.payload = {'nombre': ' Ana ', 'telefono': '222 555 6677', 'email': 'ANA@example.test', 'password': 'MiClave123!'}
        self.env = patch.dict(os.environ, {'APP_ORIGIN': 'http://localhost:5173'})
        self.env.start()
        self.addCleanup(self.env.stop)
        async def current_user(token):
            raise HTTPException(401, 'Not used')
        async def request(method, service, path, json=None, params=None):
            self.calls.append((method, path, json))
            if self.fail_profile and path == '/internal/web/customers/self-register':
                return {'detail': 'Profile unavailable'}, 503
            if path.endswith('/commit'):
                return {'access_token': 'private-session', 'user': {'id': path.split('/')[-2], 'name': 'Ana', 'email': 'ana@example.test', 'phone': '2225556677', 'role': 'client', 'state': 'active', 'created_at': '2026-10-19T18:00:00Z'}}, 200
            return {}, 200
        app = FastAPI()
        app.include_router(create_router(request, current_user))
        self.client = TestClient(app)

    def test_registration_has_private_cookie_and_normalized_public_profile(self):
        response = self.client.post('/api/auth/customers', headers={'Origin': 'http://localhost:5173'}, json=self.payload)
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertEqual(data['user']['role'], 'user')
        self.assertEqual(data['user']['estado'], 'activo')
        self.assertEqual(data['vehicles'], [])
        self.assertNotIn('access_token', data)
        cookie = response.headers['set-cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('Path=/api', cookie)
        account = self.calls[0][2]
        self.assertEqual(account['telefono'], '2225556677')
        self.assertEqual(account['nombre'], 'Ana')
        self.assertEqual(account['email'], 'ana@example.test')
        self.assertNotIn('workshop_id', account)
        self.assertNotIn('vehicle_id', account)

    def test_invalid_data_and_cross_origin_do_not_provision(self):
        for fields in [{'telefono': '123'}, {'password': 'short'}, {'email': 'bad'}, {'nombre': ' '}, {'role': 'admin'}]:
            response = self.client.post('/api/auth/customers', headers={'Origin': 'http://localhost:5173'}, json={**self.payload, **fields})
            self.assertEqual(response.status_code, 422)
        response = self.client.post('/api/auth/customers', headers={'Origin': 'https://other.test'}, json=self.payload)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.calls, [])

    def test_downstream_failure_aborts_account_and_profile(self):
        self.fail_profile = True
        response = self.client.post('/api/auth/customers', headers={'Origin': 'http://localhost:5173'}, json=self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('set-cookie', response.headers)
        cleanup = [(method, path) for method, path, _ in self.calls if method == 'DELETE']
        self.assertEqual(len(cleanup), 2)
        self.assertTrue(cleanup[0][1].startswith('/internal/web/accounts/'))
        self.assertTrue(cleanup[1][1].startswith('/internal/web/customers/'))
