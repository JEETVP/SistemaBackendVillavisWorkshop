"""Browser API compatibility layer, backed by the canonical microservices."""
from collections import OrderedDict
import logging
import ipaddress
import os
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.routing import APIRoute

from services.api_gateway.web_mapping import web_order, web_user, web_vehicle, web_workshop
from services.common.config import app_origin
from services.common.security import TOKEN_TTL_SECONDS
from services.common.web_schemas import (
    ActivationComplete, ActivationRenew, ActivationToken, CustomerIntake, CustomerRegistration, WebLogin, WorkshopRegistration,
)

COOKIE = "tallerplus_session"
PUBLIC_PATHS = {"/api/auth/login", "/api/auth/workshops", "/api/auth/customers", "/api/activation/validate", "/api/activation/complete"}
logger = logging.getLogger(__name__)


class BrowserRoute(APIRoute):
    limits = OrderedDict()

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                if request.headers.get("origin") != app_origin():
                    raise HTTPException(403, "Origen de solicitud no permitido.")
                if not request.headers.get("content-type", "").lower().startswith("application/json"):
                    raise HTTPException(415, "Envía datos JSON.")
                chunks, size = [], 0
                body_limit = 8_000_000 if request.url.path.startswith("/api/orders/") and request.url.path.endswith("/photos") else 1_500_000
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > body_limit:
                        raise HTTPException(413, "El formulario supera el tamaño permitido.")
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            if request.url.path in PUBLIC_PATHS:
                now = time.monotonic()
                # Bounded memory, fixed 15-minute windows, based on the direct client address.
                while self.limits and next(iter(self.limits.values()))[1] <= now:
                    self.limits.popitem(last=False)
                client_address = request.client.host if request.client else "unknown"
                if os.getenv("RENDER_DEPLOYMENT") == "true":
                    try:
                        client_address = str(ipaddress.ip_address(request.headers.get("X-Frontend-Client-IP", "")))
                    except ValueError:
                        pass
                key = (client_address, request.url.path)
                count, until = self.limits.get(key, (0, now + 900))
                self.limits[key] = (count + 1, until)
                if len(self.limits) > 10_000:
                    self.limits.popitem(last=False)
                if count >= 30:
                    raise HTTPException(429, "Demasiados intentos. Inténtalo de nuevo en unos minutos.",
                                        headers={"Retry-After": str(max(1, int(until - now)))})
            response = await original(request)
            response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                     "Referrer-Policy": "no-referrer"})
            return response

        return handler


def create_router(request_json, current_user):
    router = APIRouter(prefix="/api", route_class=BrowserRoute)
    identity = os.getenv("IDENTITY_SERVICE_URL", "http://127.0.0.1:8003")
    customers = os.getenv("CUSTOMERS_SERVICE_URL", "http://127.0.0.1:8001")
    workshop = os.getenv("WORKSHOP_SERVICE_URL", "http://127.0.0.1:8002")

    async def call(method, service, path, body=None, params=None):
        data, code = await request_json(method, service, path, json=body, params=params)
        if code >= 400:
            raise HTTPException(code, data.get("detail", "No se pudo completar la operación.") if isinstance(data, dict) else "Servicio no disponible.")
        return data

    async def actor(request: Request):
        token = request.cookies.get(COOKIE)
        if not token:
            raise HTTPException(401, "Inicia sesión de nuevo para continuar.")
        return await current_user(f"Bearer {token}")

    def workshop_for(user):
        if user["role"] not in {"staff", "admin"} or not user.get("workshop_id"):
            raise HTTPException(403, "Solo el administrativo del taller puede realizar esta operación.")
        return user["workshop_id"]

    def cookie(response, token):
        response.set_cookie(COOKIE, token, httponly=True, samesite="lax", path="/api",
                            secure=app_origin().startswith("https://"), max_age=TOKEN_TTL_SECONDS)

    async def revoke_previous(request):
        old = request.cookies.get(COOKIE)
        if old:
            await call("POST", identity, "/auth/logout", {"access_token": old})

    async def compensate(user_id, resources):
        # Abort identity first. If commit already won, never remove a live account's resources.
        try:
            await call("DELETE", identity, f"/internal/web/accounts/{user_id}")
        except HTTPException:
            logger.error("Provisioning requires reconciliation for user %s; committed or unreachable identity", user_id)
            return
        for service, path in reversed(resources):
            try:
                await call("DELETE", service, path)
            except HTTPException:
                logger.error("Provisioning cleanup requires reconciliation: %s", path)

    async def snapshot(user):
        if user["role"] == "client":
            if not user.get("customer_id"):
                raise HTTPException(403, "La cuenta no está vinculada a un cliente.")
            orders = await call("GET", workshop, "/internal/web/orders", params={"customer_id": user["customer_id"]})
            vehicles = await call("POST", customers, "/internal/web/vehicles/lookup", {"customer_id": user["customer_id"]})
            accounts = [user]
            workshop_ids = {order["workshop_id"] for order in orders}
        else:
            workshop_id = workshop_for(user)
            orders = await call("GET", workshop, "/internal/web/orders", params={"workshop_id": workshop_id})
            if user.get("web_cargo") == "personal_taller" and user.get("web_position") != "Personal administrativo":
                orders = [row for row in orders if web_order(row,row["customer_id"],"")["progreso"]["etapa"] in ("Diagnóstico","Servicio")
                    and web_order(row,row["customer_id"],"")["progreso"].get("tecnicoId") in (None,user["id"])
                    and row["status"] not in ("delivered","cancelled")]
            vehicles = await call("POST", customers, "/internal/web/vehicles/lookup", {"vehicle_ids": list({order["vehicle_id"] for order in orders})})
            accounts = [user, *await call("POST", identity, "/internal/web/accounts/lookup", {"customer_ids": list({order["customer_id"] for order in orders})})]
            workshop_ids = {workshop_id}
        directory = await call("GET", workshop, "/internal/web/workshops")
        owned_workshops = [item for item in directory if item["id"] in workshop_ids]
        names = {item["id"]: item["name"] for item in owned_workshops}
        owners = {account["customer_id"]: account["id"] for account in accounts if account.get("customer_id")}
        sync = await call("POST", workshop, "/internal/web/sync/snapshot", {"actor": user, "data": {}})
        if user.get("workshop_id"):
            staff = await call("GET", identity, f"/internal/web/sync/staff/{user['workshop_id']}")
            accounts = list({account["id"]: account for account in [*accounts, *staff]}.values())
            own = sync["configurations"].get(user["workshop_id"])
            if own:
                own["cuentas"] = [{"user": web_user(account)} for account in staff if account["id"] != user["id"]]
        return {"configurations":sync["configurations"], "catalogs":sync["catalogs"], "favoriteIds":sync["favoriteIds"], "user": web_user(user), "users": [web_user(account) for account in accounts],
            "vehicles": [web_vehicle(vehicle, owners.get(vehicle["customer_id"], vehicle["customer_id"])) for vehicle in vehicles],
            "orders": [web_order(order, owners.get(order["customer_id"], order["customer_id"]), names.get(order["workshop_id"], "")) for order in orders],
            "workshops": [web_workshop(item) for item in directory]}

    @router.get("/health")
    async def health():
        return {"service": "fastapi-browser-api", "status": "ok"}

    @router.post("/auth/workshops", status_code=201)
    async def register(payload: WorkshopRegistration, request: Request, response: Response):
        user_id, workshop_id = str(uuid4()), f"taller-{uuid4()}"
        resources = []
        try:
            await call("POST", identity, "/internal/web/accounts", {"id": user_id, "role": "staff",
                "name": payload.encargadoNombre, "email": payload.email, "password": payload.password, "workshop_id": workshop_id})
            resources.append((workshop, f"/internal/web/workshops/{workshop_id}"))
            item = await call("POST", workshop, "/internal/web/workshops", {"id": workshop_id, "owner_id": user_id,
                "nombre": payload.nombre, "ubicacion": payload.ubicacion.model_dump()})
            await revoke_previous(request)
            result = await call("POST", identity, f"/internal/web/accounts/{user_id}/commit")
        except HTTPException:
            await compensate(user_id, resources)
            raise
        public = web_user(result["user"])
        cookie(response, result["access_token"])
        return {"user": public, "users": [public], "vehicles": [], "orders": [], "workshops": [web_workshop(item)]}

    @router.post("/auth/customers", status_code=201)
    async def register_customer(payload: CustomerRegistration, request: Request, response: Response):
        user_id = str(uuid4())
        resources = []
        data = {**payload.model_dump(), "id": user_id}
        try:
            await call("POST", identity, "/internal/web/accounts/self-register", data)
            resources.append((customers, f"/internal/web/customers/{user_id}"))
            await call("POST", customers, "/internal/web/customers/self-register", {key: value for key, value in data.items() if key != "password"})
            await revoke_previous(request)
            result = await call("POST", identity, f"/internal/web/accounts/{user_id}/commit")
        except HTTPException:
            await compensate(user_id, resources)
            raise
        public = web_user(result["user"])
        cookie(response, result["access_token"])
        return {"user": public, "users": [public], "vehicles": [], "orders": [], "workshops": []}

    @router.post("/auth/login")
    async def login(payload: WebLogin, request: Request, response: Response):
        result = await call("POST", identity, "/internal/web/login", payload.model_dump())
        try:
            data = await snapshot(result["user"])
            await revoke_previous(request)
        except HTTPException:
            await call("POST", identity, "/auth/logout", {"access_token": result["access_token"]})
            raise
        cookie(response, result["access_token"])
        return data

    @router.get("/auth/session")
    async def session(user=Depends(actor)):
        return await snapshot(user)

    @router.post("/auth/logout")
    async def logout(request: Request, response: Response):
        await revoke_previous(request)
        response.delete_cookie(COOKIE, path="/api", httponly=True, samesite="lax", secure=app_origin().startswith("https://"))
        return {"success": True}

    @router.get("/workshops")
    async def directory(user=Depends(actor)):
        items = await call("GET", workshop, "/internal/web/workshops")
        return {"workshops": [{"id": item["id"], "nombre": item["name"],
            "ubicacion": web_workshop(item)["ubicacion"], "serviciosEnProceso": item["active_orders"]} for item in items]}

    @router.post("/workshop/intake", status_code=201)
    async def intake(payload: CustomerIntake, user=Depends(actor)):
        workshop_id = workshop_for(user)
        if user.get("web_cargo") == "personal_taller" and user.get("web_position") != "Personal administrativo":
            raise HTTPException(403, "Solo el administrativo puede registrar clientes.")
        user_id, vehicle_id, order_id = str(uuid4()), f"vehiculo-{uuid4()}", f"sol-{uuid4()}"
        resources = []
        try:
            await call("POST", identity, "/internal/web/accounts", {"id": user_id, "role": "client",
                "name": payload.nombre, "phone": payload.telefono, "vehicle_id": vehicle_id, "workshop_id": workshop_id})
            resources.append((customers, f"/internal/web/customers/{user_id}"))
            vehicle = await call("POST", customers, "/internal/web/customers", {"id": user_id, "vehicle_id": vehicle_id,
                "actor_id": user["id"], "workshop_id": workshop_id, "intake": payload.model_dump()})
            resources.append((workshop, f"/internal/web/orders/{order_id}"))
            order = await call("POST", workshop, "/internal/web/orders", {"id": order_id, "customer_id": user_id,
                "vehicle_id": vehicle_id, "workshop_id": workshop_id, "description": payload.motivoServicio})
            items = await call("GET", workshop, "/internal/web/workshops")
            name = next((item["name"] for item in items if item["id"] == workshop_id), "")
            result = await call("POST", identity, f"/internal/web/accounts/{user_id}/commit")
        except HTTPException:
            await compensate(user_id, resources)
            raise
        return {"user": web_user(result["user"]), "vehiculo": web_vehicle(vehicle, user_id),
            "solicitud": web_order(order, user_id, name), "activationUrl": result["activationUrl"], "expiresAt": result["expiresAt"]}

    @router.post("/workshop/activation")
    async def renew(payload: ActivationRenew, user=Depends(actor)):
        if user.get("web_cargo") == "personal_taller" and user.get("web_position") != "Personal administrativo":
            raise HTTPException(403, "Solo el administrativo puede renovar accesos.")
        return await call("POST", identity, "/internal/web/activation/renew", {"user_id": payload.userId, "workshop_id": workshop_for(user)})

    @router.post("/activation/validate")
    async def validate(payload: ActivationToken):
        return await call("POST", identity, "/internal/web/activation/validate", payload.model_dump())

    @router.post("/activation/complete")
    async def activate(payload: ActivationComplete):
        return await call("POST", identity, "/internal/web/activation/complete", payload.model_dump())

    from services.api_gateway.web_sync import create_router as create_sync_router
    router.include_router(create_sync_router(call, actor, snapshot, workshop, customers, identity))
    return router
