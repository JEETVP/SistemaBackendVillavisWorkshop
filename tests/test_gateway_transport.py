import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from services.api_gateway import app as gateway


class GatewayTransportTests(unittest.TestCase):
    def test_pool_is_reused_closed_and_recovers_after_connection_failure(self):
        original_client = httpx.AsyncClient
        created = []
        received = []
        unavailable = False

        def respond(request):
            received.append(request)
            if unavailable:
                raise httpx.ConnectError('Service unavailable', request=request)
            return httpx.Response(200, json={'status': 'ok'})

        def create(**kwargs):
            client = original_client(transport=httpx.MockTransport(respond), trust_env=False, **kwargs)
            created.append(client)
            return client

        with patch.object(gateway.httpx, 'AsyncClient', create):
            with TestClient(gateway.app) as browser:
                for _ in range(3):
                    self.assertEqual(browser.get('/health').status_code, 200)
                self.assertEqual(len(created), 1)
                self.assertFalse(created[0].is_closed)
                self.assertEqual(len(received), 9)
                unavailable = True
                self.assertEqual(browser.get('/health').status_code, 503)
                unavailable = False
                self.assertEqual(browser.get('/health').status_code, 200)
                self.assertEqual(len(created), 1)
                self.assertTrue(all('x-service-token' in request.headers for request in received))
            self.assertTrue(created[0].is_closed)

            with TestClient(gateway.app) as restarted:
                self.assertEqual(restarted.get('/health').status_code, 200)
                self.assertEqual(len(created), 2)
            self.assertTrue(created[1].is_closed)
