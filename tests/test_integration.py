"""HTTP integration tests using the three real services and isolated SQLite files."""
from contextlib import ExitStack
from pathlib import Path
from shutil import rmtree
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from services.api_gateway import app as gateway
from services.common import security
from services.customer_service import app as customers
from services.identity_service import app as identity
from services.workshop_service import app as workshop


class ServiceFixture(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        test_root = Path(__file__).resolve().parents[1] / "data" / "test-runs"
        test_root.mkdir(parents=True, exist_ok=True)
        directory = test_root / uuid4().hex
        directory.mkdir()
        self.directory = directory
        def cleanup_database_files():
            if directory.resolve().parent != test_root.resolve():
                raise RuntimeError("Test cleanup escaped its temporary directory")
            rmtree(directory)
        self.stack.callback(cleanup_database_files)
        for module, name in ((identity, "identity"), (customers, "customers"), (workshop, "workshop")):
            self.stack.enter_context(patch.object(module, "DB_PATH", str(directory / f"{name}.db")))
        original_key = security.ensure_private_key
        isolated_key = lambda: original_key(str(directory / "jwt.pem"))
        self.stack.enter_context(patch.object(security, "ensure_private_key", isolated_key))
        self.stack.enter_context(patch.object(identity, "ensure_private_key", isolated_key))
        self.stack.enter_context(patch.object(gateway, "PUBLIC_KEY_CACHE", None))
        self.stack.enter_context(patch.dict("os.environ", {
            "IDENTITY_BOOTSTRAP_ADMIN_PHONE": "5550000000",
            "IDENTITY_BOOTSTRAP_ADMIN_PASSWORD": "test-admin-password",
        }))
        for module in (identity, customers, workshop):
            self.stack.enter_context(TestClient(module.app))
        original_client = httpx.AsyncClient
        mounts = {
            gateway.IDENTITY_SERVICE_URL: httpx.ASGITransport(app=identity.app),
            gateway.CUSTOMERS_SERVICE_URL: httpx.ASGITransport(app=customers.app),
            gateway.WORKSHOP_SERVICE_URL: httpx.ASGITransport(app=workshop.app),
        }
        self.transports = mounts
        def unexpected_request(request):
            raise AssertionError(f"Unexpected downstream request: {request.method} {request.url}")
        async def dispatch(request):
            # Resolve at request time so failure-injection changes also exercise a pooled client.
            transport = mounts.get(str(request.url.copy_with(path="/", query=None)).rstrip("/"))
            if transport is None:
                return unexpected_request(request)
            return await transport.handle_async_request(request)
        self.stack.enter_context(patch.object(gateway.httpx, "AsyncClient",
            lambda **kwargs: original_client(trust_env=False,
                transport=httpx.MockTransport(dispatch), **kwargs)))
        self.client = self.stack.enter_context(TestClient(gateway.app))
        admin = self.request("POST", "/auth/staff/login", body={
            "phone": "5550000000", "password": "test-admin-password",
        })
        self.admin = {"Authorization": f"Bearer {admin['access_token']}"}
        self.workshop = self.request("POST", "/workshops", self.admin, {
            "name": "Taller de prueba", "address": "Avenida de prueba 123",
        }, 201)
        self.account = self.register()
        self.user = {"Authorization": f"Bearer {self.account['access_token']}"}

    def request(self, method, path, headers=None, body=None, expected=200):
        response = self.client.request(method, path, headers=headers, json=body)
        self.assertEqual(response.status_code, expected, f"{method} {path}: {response.text}")
        return response.json() if response.content else None

    def register(self, suffix="1"):
        return self.request("POST", "/auth/register", body={
            "name": "Conductor de prueba", "phone": f"555100000{suffix}",
            "password": "test-client-password", "plate": f"ABC-00{suffix}",
            "vin": f"3N1CN7AD0KL00000{suffix}", "brand": "Nissan", "model": "Versa", "year": 2020,
        }, expected=201)

    def create_order(self):
        return self.request("POST", "/work-orders", self.admin, {
            "workshop_id": self.workshop["id"], "customer_id": self.account["user"]["customer_id"],
            "vehicle_id": self.account["vehicle"]["id"], "description": "Revision completa del vehiculo",
        }, 201)


class GatewayIntegrationTests(ServiceFixture):
    def test_health_login_and_revocation(self):
        self.assertEqual(self.request("GET", "/health")["status"], "ok")
        self.assertEqual(self.request("GET", "/auth/me", self.user)["id"], self.account["user"]["id"])
        self.request("POST", "/auth/login", body={"phone": "5551000001", "password": "wrong-password"}, expected=401)
        self.request("POST", "/auth/logout", self.user, expected=204)
        self.request("GET", "/auth/me", self.user, expected=401)
        self.request("GET", "/me/vehicles", expected=401)
        self.request("GET", "/auth/me", {"Authorization": "Bearer forged-token"}, expected=401)

    def test_customer_isolation_and_staff_permissions(self):
        other = self.register("2")
        self.request("GET", f"/customers/{other['user']['customer_id']}", self.user, expected=403)
        self.request("GET", f"/vehicles/{other['vehicle']['id']}/history", self.user, expected=403)
        self.request("GET", "/customers", self.user, expected=403)
        self.request("POST", "/workshops", self.user, {"name": "Otro", "address": "Direccion 123"}, 403)
        self.request("GET", "/admin/dashboard", self.user, expected=403)

    def test_vehicle_queries_exposed_by_gateway(self):
        vehicle = self.account["vehicle"]
        customer_id = self.account["user"]["customer_id"]
        self.assertEqual(self.request("GET", f"/vehicles/{vehicle['id']}", self.user)["id"], vehicle["id"])
        self.assertEqual(self.request("GET", f"/vehicles/by-vin/{vehicle['vin']}", self.admin)["id"], vehicle["id"])
        self.assertEqual(len(self.request("GET", f"/customers/{customer_id}/vehicles", self.user)), 1)
        self.request("GET", f"/vehicles/by-vin/{vehicle['vin']}", self.user, expected=403)
        other = self.register("2")
        self.request("GET", f"/vehicles/{other['vehicle']['id']}", self.user, expected=403)

    def test_vehicle_patch_rejects_invalid_vin_without_mutating(self):
        vehicle = self.account["vehicle"]
        self.request("PATCH", f"/vehicles/{vehicle['id']}", self.admin, {"vin": "A" * 18}, 422)
        actual = self.request("GET", "/me/vehicles", self.user)
        self.assertEqual(actual[0]["vin"], vehicle["vin"])

    def test_vehicle_patch_rejects_required_null_without_mutating(self):
        vehicle = self.account["vehicle"]
        self.request("PATCH", f"/vehicles/{vehicle['id']}", self.admin, {"brand": None}, 422)
        self.assertEqual(self.request("GET", "/me/vehicles", self.user)[0]["brand"], vehicle["brand"])

    def test_appointment_requires_matching_customer_and_vehicle(self):
        other = self.register("2")
        self.request("POST", "/appointments", self.admin, {
            "workshop_id": self.workshop["id"], "customer_id": other["user"]["customer_id"],
            "vehicle_id": self.account["vehicle"]["id"], "requested_at": "2026-10-20T10:00:00-06:00",
        }, 422)
        self.assertEqual(self.request("GET", "/appointments", self.admin), [])

    def test_quote_item_edit_delete_and_authorization(self):
        order = self.create_order()
        quote = self.request("POST", "/quotes", self.admin, {
            "work_order_id": order["id"],
            "items": [{"description": "Aceite", "quantity": 2, "unit_price": 125.5}],
        }, 201)
        path = f"/quotes/{quote['id']}/items/{quote['items'][0]['id']}"
        self.request("PATCH", path, self.user, {"quantity": 3}, 403)
        edited = self.request("PATCH", path, self.admin, {"quantity": 3, "unit_price": 150})
        self.assertEqual(edited["subtotal"], 450)
        self.assertEqual(edited["items"][0]["total"], 450)
        self.request("PATCH", path, self.admin, {"quantity": None}, 422)
        self.request("PATCH", path, self.admin, {}, 400)
        self.request("PATCH", f"/quotes/{quote['id']}/items/missing", self.admin, {"quantity": 2}, 404)
        self.request("DELETE", path, self.user, expected=403)
        empty = self.request("DELETE", path, self.admin)
        self.assertEqual(empty["subtotal"], 0)
        self.assertEqual(empty["items"], [])

    def test_accepted_quote_cannot_be_edited(self):
        order = self.create_order()
        quote = self.request("POST", "/quotes", self.admin, {
            "work_order_id": order["id"], "items": [{"description": "Revision", "unit_price": 400}],
        }, 201)
        self.request("PATCH", f"/quotes/{quote['id']}/status", self.user, {"status": "accepted"})
        path = f"/quotes/{quote['id']}/items/{quote['items'][0]['id']}"
        self.request("PATCH", path, self.admin, {"unit_price": 900}, 409)
        self.request("DELETE", path, self.admin, expected=409)
        self.request("POST", f"/quotes/{quote['id']}/items", self.admin, {"description": "Extra", "unit_price": 200}, 409)
        self.request("PATCH", f"/quotes/{quote['id']}/status", self.admin, {"status": "draft"}, 409)
        self.assertEqual(self.request("GET", f"/work-orders/{order['id']}", self.user)["estimated_total"], 400)
        self.request("PATCH", f"/work-orders/{order['id']}/status", self.admin, {"status": "delivered"})
        self.request("PATCH", f"/quotes/{quote['id']}/status", self.user, {"status": "accepted"})
        self.assertEqual(self.request("GET", f"/work-orders/{order['id']}", self.user)["status"], "delivered")

    def test_cart_checkout_work_progress_notifications_and_reports(self):
        vehicle = self.account["vehicle"]
        workshop_id = self.workshop["id"]
        service = self.request("POST", "/services", self.admin, {
            "workshop_id": workshop_id, "name": "Cambio de aceite", "service_type": "Preventivo",
            "price_3_cyl": 100, "price_4_cyl": 200, "price_6_cyl": 300, "price_8_cyl": 400,
        }, 201)
        self.assertEqual(self.request("GET", f"/services/{service['id']}/price?cylinders=4")["unit_price"], 200)
        intake = self.request("POST", "/vehicle-intakes", self.user, {
            "workshop_id": workshop_id, "vehicle_id": vehicle["id"], "vin": vehicle["vin"],
            "photo_urls": ["https://example.test/intake.jpg"],
        }, 201)
        cart = self.request("POST", "/service-carts", self.user, {
            "workshop_id": workshop_id, "vehicle_id": vehicle["id"], "intake_id": intake["id"],
        }, 201)
        cart_path = f"/service-carts/{cart['id']}"
        cart = self.request("POST", cart_path + "/items", self.user, {
            "service_id": service["id"], "cylinder_count": 4, "quantity": 2,
        }, 201)
        self.assertEqual(cart["subtotal"], 400)
        self.request("PATCH", f"{cart_path}/items/{cart['items'][0]['id']}", self.user, {"quantity": 3})
        self.assertEqual(self.request("GET", cart_path + "/summary", self.user)["subtotal"], 600)
        checkout = self.request("POST", cart_path + "/checkout", self.user, {
            "requested_at": "2026-10-20T10:00:00-06:00", "deposit_percentage": 30,
        }, 201)
        self.assertEqual(checkout["payment_request"]["deposit_amount"], 180)
        self.request("POST", cart_path + "/checkout", self.user, {
            "requested_at": "2026-10-20T10:00:00-06:00", "deposit_percentage": 30,
        }, 422)
        order = checkout["work_order"]
        order_path = f"/work-orders/{order['id']}"
        self.request("POST", order_path + "/accept", self.admin)
        progress = self.request("PATCH", f"{order_path}/tasks/{order['tasks'][0]['id']}/status",
            self.admin, {"status": "done"})
        self.assertEqual(progress["progress_percent"], 100)
        self.assertEqual(progress["status"], "ready")
        self.request("POST", order_path + "/evidence", self.admin, {"file_url": "https://example.test/done.jpg"}, 201)
        self.assertEqual(len(self.request("GET", order_path + "/evidence", self.user)), 1)
        self.request("POST", "/payments", self.admin, {"work_order_id": order["id"], "amount": 180, "status": "paid"}, 201)
        self.assertEqual(len(self.request("GET", f"/vehicles/{vehicle['id']}/history", self.user)["work_orders"]), 1)
        self.assertGreater(self.request("GET", "/me/notifications/unread-count", self.user)["unread_count"], 0)
        self.request("PATCH", "/me/notifications/read-all", self.user)
        self.assertEqual(self.request("GET", "/me/notifications/unread-count", self.user)["unread_count"], 0)
        self.assertGreater(self.request("GET", f"/workshops/{workshop_id}/notifications/unread-count", self.admin)["unread_count"], 0)
        self.request("GET", f"/admin/dashboard?workshop_id={workshop_id}", self.admin)
        report = self.request("GET", f"/reports/workshops?workshop_id={workshop_id}", self.admin)
        self.assertEqual(report["paid_amount"], 180)


if __name__ == "__main__":
    unittest.main()
