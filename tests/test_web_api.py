from concurrent.futures import ThreadPoolExecutor
import time
from urllib.parse import parse_qs, urlsplit

import httpx

from test_integration import ServiceFixture
from services.api_gateway import app as gateway
from services.api_gateway.web import BrowserRoute
from services.common.database import connect
from services.customer_service import app as customers
from services.identity_service import app as identity
from services.workshop_service import app as workshop


ORIGIN = {"Origin": "http://localhost:5173"}


class BrowserApiTests(ServiceFixture):
    def setUp(self):
        super().setUp()
        BrowserRoute.limits.clear()
        self.stack.callback(BrowserRoute.limits.clear)

    def web(self, method, path, body=None, expected=200):
        return self.request(method, "/api" + path, ORIGIN, body, expected)

    def workshop_input(self, email="recepcion@prueba.test"):
        return {"nombre": "Taller prueba", "encargadoNombre": "Ana", "email": email,
            "password": "ClaveTaller123!", "ubicacion": {"direccion": "Calle 10", "ciudad": "Puebla",
            "estado": "Puebla", "codigoPostal": "72000"}}

    def intake_input(self):
        return {"nombre": " Luis Pérez ", "telefono": "222 123 4567", "motivoServicio": "Revisar frenos",
            "vehiculo": {"marca": "Volkswagen", "modelo": "Jetta", "anio": 2020, "placas": "abc-123",
                "numeroSerie": "3VW2K7AJ5EM123456", "cilindros": 4, "combustible": "Gasolina",
                "kilometraje": 45000, "color": "Blanco"}}

    def register_workshop(self, email="recepcion@prueba.test"):
        return self.web("POST", "/auth/workshops", self.workshop_input(email), 201)

    def receive(self):
        self.register_workshop()
        intake = self.web("POST", "/workshop/intake", self.intake_input(), 201)
        token = parse_qs(urlsplit(intake["activationUrl"]).query)["token"][0]
        return intake, token

    def activate(self, token, expected=200):
        return self.web("POST", "/activation/complete", {"token": token, "password": "ClaveCliente123!",
            "passwordConfirm": "ClaveCliente123!"}, expected)

    def counts(self):
        result = []
        for path, table in [(identity.DB_PATH, "users"), (customers.DB_PATH, "customers"),
                            (customers.DB_PATH, "vehicles"), (workshop.DB_PATH, "work_orders")]:
            with connect(path) as db:
                result.append(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        return result

    def test_complete_flow_uses_canonical_data_and_cookie(self):
        intake, token = self.receive()
        self.assertEqual(intake["user"]["estado"], "pendiente_activacion")
        self.assertEqual(intake["vehiculo"]["placas"], "ABC123")
        self.assertEqual(intake["solicitud"]["progreso"]["etapa"], "Diagnóstico")
        self.web("POST", "/auth/login", {"type": "cliente", "telefono": "2221234567", "password": "ClaveCliente123!"}, 401)
        self.web("POST", "/activation/validate", {"token": token})
        self.activate(token)
        self.activate(token, 400)
        self.web("POST", "/auth/logout", {})
        self.web("GET", "/auth/session", expected=401)
        response = self.client.post("/api/auth/login", headers=ORIGIN,
            json={"type": "cliente", "telefono": "222-123-4567", "password": "ClaveCliente123!"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("Path=/api", response.headers["set-cookie"])
        self.assertNotIn("access_token", response.text)
        data = response.json()
        self.assertEqual(data["vehicles"][0]["id"], intake["vehiculo"]["id"])
        self.assertEqual(data["orders"][0]["id"], intake["solicitud"]["id"])
        self.assertEqual(self.web("GET", "/auth/session")["user"]["uid"], intake["user"]["uid"])
        # The same order exists in the original FastAPI resource, not a browser-only collection.
        order = self.request("GET", f"/work-orders/{intake['solicitud']['id']}", self.admin)
        self.assertEqual(order["vehicle_id"], intake["vehiculo"]["id"])
        self.request("PATCH", f"/work-orders/{order['id']}/status", self.admin, {"status": "delivered"})
        self.assertEqual(self.web("GET", "/auth/session")["orders"][0]["estado"], "Finalizada")

    def test_tenant_isolation_renewal_and_public_directory(self):
        intake, token = self.receive()
        first = self.web("GET", "/auth/session")["user"]
        # Even a user who extracts their own HttpOnly token cannot use the legacy global staff permissions.
        token_header = {"Authorization": f"Bearer {self.client.cookies.get('tallerplus_session')}"}
        self.request("GET", "/customers", token_header, expected=403)
        self.request("GET", "/work-orders", token_header, expected=403)
        self.request("GET", f"/customers/{self.account['user']['customer_id']}", token_header, expected=403)
        renewed = self.web("POST", "/workshop/activation", {"userId": intake["user"]["uid"]})
        self.web("POST", "/activation/validate", {"token": token}, 400)
        second = self.register_workshop("otro@prueba.test")
        self.assertNotEqual(first["tallerId"], second["user"]["tallerId"])
        snapshot = self.web("GET", "/auth/session")
        self.assertEqual(snapshot["orders"], [])
        self.assertEqual(snapshot["vehicles"], [])
        self.assertEqual(len(snapshot["users"]), 1)
        self.web("POST", "/workshop/activation", {"userId": intake["user"]["uid"]}, 403)
        directory = self.web("GET", "/workshops")
        self.assertTrue(all(set(item) == {"id", "nombre", "ubicacion", "serviciosEnProceso"} for item in directory["workshops"]))
        self.assertNotIn(intake["user"]["celular"], str(directory))
        current_token = parse_qs(urlsplit(renewed["activationUrl"]).query)["token"][0]
        self.web("POST", "/activation/validate", {"token": current_token})

    def test_duplicate_phone_or_vehicle_leaves_no_partial_records(self):
        self.receive()
        before = self.counts()
        self.web("POST", "/workshop/intake", self.intake_input(), 409)
        self.assertEqual(self.counts(), before)
        payload = self.intake_input()
        payload["telefono"] = "2229999999"
        self.web("POST", "/workshop/intake", payload, 409)
        self.assertEqual(self.counts(), before)

    def test_downstream_failure_compensates_provisional_resources(self):
        self.register_workshop()
        before = self.counts()
        original = self.transports[gateway.WORKSHOP_SERVICE_URL]
        async def fail_order(request):
            if request.method == "POST" and request.url.path == "/internal/web/orders":
                return httpx.Response(503, json={"detail": "Injected failure"})
            return await original.handle_async_request(request)
        self.transports[gateway.WORKSHOP_SERVICE_URL] = httpx.MockTransport(fail_order)
        self.web("POST", "/workshop/intake", self.intake_input(), 503)
        self.assertEqual(self.counts(), before)

    def test_invalid_vehicle_and_password_do_not_write(self):
        self.register_workshop()
        before = self.counts()
        payload = self.intake_input()
        payload["vehiculo"]["numeroSerie"] = "INVALID"
        self.web("POST", "/workshop/intake", payload, 400)
        self.assertEqual(self.counts(), before)
        intake = self.web("POST", "/workshop/intake", self.intake_input(), 201)
        token = parse_qs(urlsplit(intake["activationUrl"]).query)["token"][0]
        self.web("POST", "/activation/complete", {"token": token, "password": "ClaveCliente123!", "passwordConfirm": "Diferente123!"}, 400)
        self.web("POST", "/activation/validate", {"token": token})
        with connect(identity.DB_PATH) as db:
            db.execute("UPDATE activations SET expires_at = ?", (time.time() - 1,))
        self.activate(token, 400)

    def test_activation_is_single_use_under_concurrent_requests(self):
        _, token = self.receive()
        def activate_once(_):
            return self.client.post("/api/activation/complete", headers=ORIGIN,
                json={"token": token, "password": "ClaveCliente123!", "passwordConfirm": "ClaveCliente123!"}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(activate_once, range(2)))
        self.assertEqual(sorted(outcomes), [200, 400])

    def test_electric_vin_only_intake_and_native_vehicle_query(self):
        registration = self.workshop_input()
        registration["nombre"] = "A"
        owner = self.web("POST", "/auth/workshops", registration, 201)
        payload = self.intake_input()
        payload.update(nombre="B", motivoServicio="R" * 1000)
        payload["vehiculo"].update(placas="", combustible="Eléctrico", cilindros=0, marca="M" * 80)
        intake = self.web("POST", "/workshop/intake", payload, 201)
        self.assertEqual(intake["vehiculo"]["placas"], "")
        self.assertEqual(intake["vehiculo"]["cilindros"], 0)
        native = self.request("GET", f"/vehicles/{intake['vehiculo']['id']}", self.admin)
        self.assertIsNone(native["plate"])
        self.request("GET", f"/work-orders/{intake['solicitud']['id']}", self.admin)
        self.request("GET", f"/customers/{intake['user']['uid']}", self.admin)
        self.request("GET", f"/workshops/{owner['user']['tallerId']}", self.admin)

    def test_origin_body_size_rate_limit_and_internal_authentication(self):
        self.request("POST", "/api/auth/workshops", {"Origin": "https://untrusted.test"}, self.workshop_input(), 403)
        response = self.client.post("/api/auth/login", headers={**ORIGIN, "Content-Type": "application/json"}, content="x" * 1_500_001)
        self.assertEqual(response.status_code, 413)
        for _ in range(30):
            self.web("POST", "/activation/validate", {"token": "A" * 43}, 400)
        self.web("POST", "/activation/validate", {"token": "A" * 43}, 429)
        from fastapi.testclient import TestClient
        with TestClient(identity.app) as client:
            self.assertEqual(client.post("/internal/web/accounts/lookup", json={"customer_ids": []}).status_code, 403)
