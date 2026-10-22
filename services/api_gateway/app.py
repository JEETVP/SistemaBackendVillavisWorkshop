from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from services.api_gateway.schemas import (
    AppointmentCreate,
    AppointmentStatusUpdate,
    CustomerCreate,
    EvidenceCreate,
    PaymentCreate,
    QuoteCreate,
    QuoteItemCreate,
    QuoteItemUpdate,
    QuoteStatusUpdate,
    RecommendationCreate,
    ServiceCartCheckoutCreate,
    ServiceCartCreate,
    ServiceCartItemCreate,
    ServiceCartItemUpdate,
    ServiceCreate,
    ServiceUpdate,
    StaffLogin,
    StaffUserRegister,
    TaskCreate,
    TaskStatusUpdate,
    VehicleAccountRegister,
    VehicleCreate,
    VehicleIntakeCreate,
    VehicleUpdate,
    WorkshopCreate,
    WorkshopUpdate,
    WorkOrderCreate,
    WorkOrderStatusUpdate,
)
from services.common.security import verify_token
from services.api_gateway.web import create_router

IDENTITY_SERVICE_URL = os.getenv("IDENTITY_SERVICE_URL", "http://127.0.0.1:8003")
CUSTOMERS_SERVICE_URL = os.getenv("CUSTOMERS_SERVICE_URL", "http://127.0.0.1:8001")
WORKSHOP_SERVICE_URL = os.getenv("WORKSHOP_SERVICE_URL", "http://127.0.0.1:8002")
REQUEST_TIMEOUT = 8.0
PUBLIC_KEY_CACHE: str | None = None

@asynccontextmanager
async def lifespan(application: FastAPI):
    # One pool per worker: do not rebuild SSL/proxy configuration for each hop.
    previous = getattr(application.state, "service_client", None)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        application.state.service_client = client
        try:
            yield
        finally:
            application.state.service_client = previous


app = FastAPI(
    lifespan=lifespan,
    title="Villavis Workshop API Gateway",
    description="Entrada principal del backend distribuido de Taller+ para Villavis Workshop.",
    version="1.0.0",
)


@app.exception_handler(StarletteHTTPException)
async def browser_http_error(request: Request, error: StarletteHTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": error.detail if isinstance(error.detail, str) else "Revisa los datos enviados."},
            status_code=error.status_code, headers={"Cache-Control": "no-store", **(error.headers or {})})
    return await http_exception_handler(request, error)


@app.exception_handler(RequestValidationError)
async def browser_validation_error(request: Request, error: RequestValidationError):
    if request.url.path.startswith("/api/"):
        message = error.errors()[0].get("msg", "Revisa los datos del formulario.")
        return JSONResponse({"error": message}, status_code=400, headers={"Cache-Control": "no-store"})
    return await request_validation_exception_handler(request, error)


async def request_json(
    method: str,
    base_url: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
) -> tuple[Any, int]:
    url = f"{base_url}{path}"
    try:
        client = getattr(app.state, "service_client", None)
        if client is None or client.is_closed:
            raise HTTPException(503, "El gateway todavía está iniciando sus conexiones internas.")
        response = await client.request(method, url, json=json, params=params,
            headers={"X-Service-Token": os.getenv("INTERNAL_SERVICE_TOKEN", "")})
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service unavailable: {base_url}",
        ) from exc

    if response.content:
        return response.json(), response.status_code
    return None, response.status_code


def raise_for_service_error(payload: Any, status_code: int) -> None:
    if status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        raise HTTPException(status_code=status_code, detail=detail)


def extract_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")
    return token


async def authenticate_user(authorization: str | None) -> dict:
    token = extract_token(authorization)
    global PUBLIC_KEY_CACHE
    if PUBLIC_KEY_CACHE is None:
        key_data, key_code = await request_json("GET", IDENTITY_SERVICE_URL, "/auth/public-key")
        raise_for_service_error(key_data, key_code)
        if key_data.get("algorithm") != "RS256" or not key_data.get("public_key"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Identity service returned an invalid signing key",
            )
        PUBLIC_KEY_CACHE = key_data["public_key"]
    try:
        claims = verify_token(token, PUBLIC_KEY_CACHE)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    data, code = await request_json(
        "POST",
        IDENTITY_SERVICE_URL,
        "/sessions/validate",
        json={"access_token": token},
    )
    raise_for_service_error(data, code)
    if data.get("id") != claims.get("sub") or data.get("role") != claims.get("role"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token claims do not match session")
    return data


async def current_user(authorization: str | None = Header(default=None)) -> dict:
    user = await authenticate_user(authorization)
    # Public workshop signup must not grant access to the older global-staff API.
    # Its native resource permissions will migrate to workshop memberships later.
    if user.get("workshop_id"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Workshop accounts must use the scoped /api browser endpoints")
    return user


async def optional_current_user(authorization: str | None = Header(default=None)) -> dict | None:
    if not authorization:
        return None
    return await current_user(authorization)


def require_roles(*roles: str) -> Callable:
    async def dependency(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency


def ensure_customer_access(user: dict, customer_id: str) -> None:
    if user["role"] in {"staff", "admin"}:
        return
    if user.get("customer_id") == customer_id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer access denied")


def require_linked_customer(user: dict) -> str:
    customer_id = user.get("customer_id")
    if not customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client user is not linked to a customer record",
        )
    return customer_id


async def fetch_vehicle(vehicle_id: str) -> dict:
    vehicle, code = await request_json("GET", CUSTOMERS_SERVICE_URL, f"/vehicles/{vehicle_id}")
    raise_for_service_error(vehicle, code)
    return vehicle


async def fetch_service_cart(cart_id: str) -> dict:
    cart, code = await request_json("GET", WORKSHOP_SERVICE_URL, f"/service-carts/{cart_id}")
    raise_for_service_error(cart, code)
    return cart


async def ensure_vehicle_access(user: dict, vehicle_id: str) -> dict:
    vehicle = await fetch_vehicle(vehicle_id)
    ensure_customer_access(user, vehicle["customer_id"])
    return vehicle


def ensure_vehicle_vin(vehicle: dict, vin: str) -> None:
    if (vehicle.get("vin") or "").upper() != vin.strip().upper():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid VIN for selected vehicle",
        )


@app.get("/health")
async def health() -> dict:
    identity, identity_status = await request_json("GET", IDENTITY_SERVICE_URL, "/health")
    customers, customers_status = await request_json("GET", CUSTOMERS_SERVICE_URL, "/health")
    workshop, workshop_status = await request_json("GET", WORKSHOP_SERVICE_URL, "/health")
    ok = identity_status < 400 and customers_status < 400 and workshop_status < 400

    return {
        "service": "api_gateway",
        "status": "ok" if ok else "degraded",
        "dependencies": {
            "identity": identity,
            "customers": customers,
            "workshop": workshop,
        },
    }


@app.get("/admin/dashboard")
async def admin_dashboard(
    workshop_id: str | None = None,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        "/admin/dashboard",
        params={"workshop_id": workshop_id} if workshop_id else {},
    )
    raise_for_service_error(data, code)
    return data


@app.get("/reports/workshops")
async def workshop_report(
    workshop_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    params = {
        key: value
        for key, value in {
            "workshop_id": workshop_id,
            "date_from": date_from,
            "date_to": date_to,
        }.items()
        if value is not None
    }
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        "/reports/workshops",
        params=params,
    )
    raise_for_service_error(data, code)
    return data


@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register_vehicle_account(payload: VehicleAccountRegister, response: Response) -> Any:
    existing_vehicle, existing_code = await request_json(
        "GET",
        CUSTOMERS_SERVICE_URL,
        f"/vehicles/by-plate/{payload.plate}",
    )
    if existing_code < 400:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vehicle plate already registered",
        )
    if existing_code != status.HTTP_404_NOT_FOUND:
        raise_for_service_error(existing_vehicle, existing_code)

    customer, customer_code = await request_json(
        "POST",
        CUSTOMERS_SERVICE_URL,
        "/customers",
        json={"name": payload.name, "phone": payload.phone, "email": None},
    )
    raise_for_service_error(customer, customer_code)

    vehicle_payload = payload.model_dump(
        exclude={"name", "phone", "password"},
    )
    if not vehicle_payload.get("owner_name"):
        vehicle_payload["owner_name"] = payload.name

    vehicle, vehicle_code = await request_json(
        "POST",
        CUSTOMERS_SERVICE_URL,
        f"/customers/{customer['id']}/vehicles",
        json=vehicle_payload,
    )
    raise_for_service_error(vehicle, vehicle_code)

    session, session_code = await request_json(
        "POST",
        IDENTITY_SERVICE_URL,
        "/auth/client/register",
        json={
            "name": payload.name,
            "phone": payload.phone,
            "password": payload.password,
            "customer_id": customer["id"],
            "primary_vehicle_id": vehicle["id"],
        },
    )
    raise_for_service_error(session, session_code)
    response.status_code = status.HTTP_201_CREATED
    return {"access_token": session["access_token"], "token_type": "bearer", "user": session["user"], "vehicle": vehicle}


@app.post("/auth/login")
async def login_with_phone(payload: StaffLogin) -> Any:
    data, code = await request_json(
        "POST",
        IDENTITY_SERVICE_URL,
        "/auth/login",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    vehicle = None
    primary_vehicle_id = data.get("user", {}).get("primary_vehicle_id")
    if primary_vehicle_id:
        vehicle, vehicle_code = await request_json(
            "GET",
            CUSTOMERS_SERVICE_URL,
            f"/vehicles/{primary_vehicle_id}",
        )
        if vehicle_code >= 400:
            vehicle = None
    return {**data, "vehicle": vehicle}


@app.post("/auth/staff/login")
async def staff_login(payload: StaffLogin) -> Any:
    data, code = await request_json(
        "POST",
        IDENTITY_SERVICE_URL,
        "/auth/staff/login",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    if data.get("user", {}).get("role") not in {"staff", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff account required")
    return data


@app.post("/auth/staff/register", status_code=status.HTTP_201_CREATED)
async def register_staff_user(
    payload: StaffUserRegister,
    response: Response,
    _: dict = Depends(require_roles("admin")),
) -> Any:
    data, code = await request_json(
        "POST",
        IDENTITY_SERVICE_URL,
        "/auth/staff/register",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(authorization: str | None = Header(default=None)) -> Response:
    token = extract_token(authorization)
    data, code = await request_json(
        "POST",
        IDENTITY_SERVICE_URL,
        "/auth/logout",
        json={"access_token": token},
    )
    raise_for_service_error(data, code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/auth/me")
async def me(user: dict = Depends(current_user)) -> dict:
    return user


@app.get("/me/vehicles")
async def list_my_vehicles(user: dict = Depends(current_user)) -> Any:
    customer_id = require_linked_customer(user)
    data, code = await request_json(
        "GET",
        CUSTOMERS_SERVICE_URL,
        f"/customers/{customer_id}/vehicles",
    )
    raise_for_service_error(data, code)
    return data


@app.post("/me/vehicles", status_code=status.HTTP_201_CREATED)
async def link_my_vehicle(
    payload: VehicleCreate,
    response: Response,
    user: dict = Depends(current_user),
) -> Any:
    customer_id = require_linked_customer(user)
    data, code = await request_json(
        "POST",
        CUSTOMERS_SERVICE_URL,
        f"/customers/{customer_id}/vehicles",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.post("/customers", status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    response: Response,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "POST",
        CUSTOMERS_SERVICE_URL,
        "/customers",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.get("/customers")
async def list_customers(_: dict = Depends(require_roles("staff", "admin"))) -> Any:
    data, code = await request_json("GET", CUSTOMERS_SERVICE_URL, "/customers")
    raise_for_service_error(data, code)
    return data


@app.get("/customers/{customer_id}")
async def get_customer(customer_id: str, user: dict = Depends(current_user)) -> Any:
    ensure_customer_access(user, customer_id)
    data, code = await request_json("GET", CUSTOMERS_SERVICE_URL, f"/customers/{customer_id}")
    raise_for_service_error(data, code)
    return data


@app.post("/customers/{customer_id}/vehicles", status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    customer_id: str,
    payload: VehicleCreate,
    response: Response,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "POST",
        CUSTOMERS_SERVICE_URL,
        f"/customers/{customer_id}/vehicles",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.get("/customers/{customer_id}/vehicles")
async def list_customer_vehicles(customer_id: str, user: dict = Depends(current_user)) -> Any:
    ensure_customer_access(user, customer_id)
    data, code = await request_json("GET", CUSTOMERS_SERVICE_URL, f"/customers/{customer_id}/vehicles")
    raise_for_service_error(data, code)
    return data


@app.get("/vehicles/{vehicle_id}")
async def get_vehicle(vehicle_id: str, user: dict = Depends(current_user)) -> Any:
    return await ensure_vehicle_access(user, vehicle_id)


@app.patch("/vehicles/{vehicle_id}")
async def update_vehicle(
    vehicle_id: str,
    payload: VehicleUpdate,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "PATCH",
        CUSTOMERS_SERVICE_URL,
        f"/vehicles/{vehicle_id}",
        json=payload.model_dump(exclude_unset=True),
    )
    raise_for_service_error(data, code)
    return data


@app.get("/vehicles/by-plate/{plate}")
async def get_vehicle_by_plate(plate: str, _: dict = Depends(require_roles("staff", "admin"))) -> Any:
    data, code = await request_json("GET", CUSTOMERS_SERVICE_URL, f"/vehicles/by-plate/{plate}")
    raise_for_service_error(data, code)
    return data


@app.get("/vehicles/by-vin/{vin}")
async def get_vehicle_by_vin(vin: str, _: dict = Depends(require_roles("staff", "admin"))) -> Any:
    data, code = await request_json("GET", CUSTOMERS_SERVICE_URL, f"/vehicles/by-vin/{vin}")
    raise_for_service_error(data, code)
    return data


@app.get("/vehicles/{vehicle_id}/recommendations")
async def list_vehicle_recommendations(vehicle_id: str, user: dict = Depends(current_user)) -> Any:
    await ensure_vehicle_access(user, vehicle_id)
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/vehicles/{vehicle_id}/recommendations",
    )
    raise_for_service_error(data, code)
    return data


@app.post("/workshops", status_code=status.HTTP_201_CREATED)
async def create_workshop(
    payload: WorkshopCreate,
    response: Response,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        "/workshops",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.get("/workshops")
async def list_workshops(active: bool | None = True) -> Any:
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        "/workshops",
        params={"active": active} if active is not None else {},
    )
    raise_for_service_error(data, code)
    return data


@app.get("/workshops/{workshop_id}")
async def get_workshop(workshop_id: str) -> Any:
    data, code = await request_json("GET", WORKSHOP_SERVICE_URL, f"/workshops/{workshop_id}")
    raise_for_service_error(data, code)
    return data


@app.patch("/workshops/{workshop_id}")
async def update_workshop(
    workshop_id: str,
    payload: WorkshopUpdate,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "PATCH",
        WORKSHOP_SERVICE_URL,
        f"/workshops/{workshop_id}",
        json=payload.model_dump(exclude_unset=True),
    )
    raise_for_service_error(data, code)
    return data


@app.get("/workshops/{workshop_id}/services")
async def list_workshop_services(workshop_id: str, active: bool | None = True) -> Any:
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/workshops/{workshop_id}/services",
        params={"active": active} if active is not None else {},
    )
    raise_for_service_error(data, code)
    return data


@app.post("/services", status_code=status.HTTP_201_CREATED)
async def create_service(
    payload: ServiceCreate,
    response: Response,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        "/services",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.get("/services")
async def list_services(active: bool | None = True, workshop_id: str | None = None) -> Any:
    params = {"active": active, "workshop_id": workshop_id}
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        "/services",
        params={key: value for key, value in params.items() if value is not None},
    )
    raise_for_service_error(data, code)
    return data


@app.get("/services/{service_id}")
async def get_service(service_id: str) -> Any:
    data, code = await request_json("GET", WORKSHOP_SERVICE_URL, f"/services/{service_id}")
    raise_for_service_error(data, code)
    return data


@app.patch("/services/{service_id}")
async def update_service(
    service_id: str,
    payload: ServiceUpdate,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "PATCH",
        WORKSHOP_SERVICE_URL,
        f"/services/{service_id}",
        json=payload.model_dump(exclude_unset=True),
    )
    raise_for_service_error(data, code)
    return data


@app.get("/services/{service_id}/price")
async def get_service_price(service_id: str, cylinders: int) -> Any:
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/services/{service_id}/price",
        params={"cylinders": cylinders},
    )
    raise_for_service_error(data, code)
    return data


@app.post("/service-carts", status_code=status.HTTP_201_CREATED)
async def create_service_cart(
    payload: ServiceCartCreate,
    response: Response,
    user: dict = Depends(current_user),
) -> Any:
    vehicle = await ensure_vehicle_access(user, payload.vehicle_id)
    if payload.intake_id:
        intake, intake_code = await request_json(
            "GET",
            WORKSHOP_SERVICE_URL,
            f"/vehicle-intakes/{payload.intake_id}",
        )
        raise_for_service_error(intake, intake_code)
        if (
            intake["workshop_id"] != payload.workshop_id
            or intake["customer_id"] != vehicle["customer_id"]
            or intake["vehicle_id"] != payload.vehicle_id
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Intake does not match selected cart workshop or vehicle",
            )

    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        "/service-carts",
        json={
            "workshop_id": payload.workshop_id,
            "customer_id": vehicle["customer_id"],
            "vehicle_id": payload.vehicle_id,
            "intake_id": payload.intake_id,
        },
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.get("/service-carts/{cart_id}")
async def get_service_cart(cart_id: str, user: dict = Depends(current_user)) -> Any:
    data = await fetch_service_cart(cart_id)
    ensure_customer_access(user, data["customer_id"])
    return data


@app.get("/service-carts/{cart_id}/summary")
async def get_service_cart_summary(cart_id: str, user: dict = Depends(current_user)) -> Any:
    data = await fetch_service_cart(cart_id)
    ensure_customer_access(user, data["customer_id"])
    return data


@app.post("/service-carts/{cart_id}/items", status_code=status.HTTP_201_CREATED)
async def add_service_cart_item(
    cart_id: str,
    payload: ServiceCartItemCreate,
    response: Response,
    user: dict = Depends(current_user),
) -> Any:
    cart = await fetch_service_cart(cart_id)
    ensure_customer_access(user, cart["customer_id"])
    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        f"/service-carts/{cart_id}/items",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.patch("/service-carts/{cart_id}/items/{item_id}")
async def update_service_cart_item(
    cart_id: str,
    item_id: str,
    payload: ServiceCartItemUpdate,
    user: dict = Depends(current_user),
) -> Any:
    cart = await fetch_service_cart(cart_id)
    ensure_customer_access(user, cart["customer_id"])
    data, code = await request_json(
        "PATCH",
        WORKSHOP_SERVICE_URL,
        f"/service-carts/{cart_id}/items/{item_id}",
        json=payload.model_dump(exclude_unset=True),
    )
    raise_for_service_error(data, code)
    return data


@app.delete("/service-carts/{cart_id}/items/{item_id}")
async def delete_service_cart_item(
    cart_id: str,
    item_id: str,
    user: dict = Depends(current_user),
) -> Any:
    cart = await fetch_service_cart(cart_id)
    ensure_customer_access(user, cart["customer_id"])
    data, code = await request_json(
        "DELETE",
        WORKSHOP_SERVICE_URL,
        f"/service-carts/{cart_id}/items/{item_id}",
    )
    raise_for_service_error(data, code)
    return data


@app.post("/service-carts/{cart_id}/checkout", status_code=status.HTTP_201_CREATED)
async def checkout_service_cart(
    cart_id: str,
    payload: ServiceCartCheckoutCreate,
    response: Response,
    user: dict = Depends(current_user),
) -> Any:
    cart = await fetch_service_cart(cart_id)
    ensure_customer_access(user, cart["customer_id"])
    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        f"/service-carts/{cart_id}/checkout",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.post("/vehicle-intakes", status_code=status.HTTP_201_CREATED)
async def create_vehicle_intake(
    payload: VehicleIntakeCreate,
    response: Response,
    user: dict = Depends(current_user),
) -> Any:
    vehicle = await ensure_vehicle_access(user, payload.vehicle_id)
    ensure_vehicle_vin(vehicle, payload.vin)

    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        "/vehicle-intakes",
        json={
            "workshop_id": payload.workshop_id,
            "customer_id": vehicle["customer_id"],
            "vehicle_id": payload.vehicle_id,
            "has_tapones": payload.has_tapones,
            "has_virlos": payload.has_virlos,
            "has_tapa_gasolina": payload.has_tapa_gasolina,
            "has_rines": payload.has_rines,
            "has_ceniceros": payload.has_ceniceros,
            "has_llanta_refaccion": payload.has_llanta_refaccion,
            "detail_notes": payload.detail_notes,
            "photo_urls": payload.photo_urls,
        },
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.get("/vehicle-intakes/{intake_id}")
async def get_vehicle_intake(intake_id: str, user: dict = Depends(current_user)) -> Any:
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/vehicle-intakes/{intake_id}",
    )
    raise_for_service_error(data, code)
    ensure_customer_access(user, data["customer_id"])
    return data


@app.get("/vehicles/{vehicle_id}/intakes")
async def list_vehicle_intakes(vehicle_id: str, user: dict = Depends(current_user)) -> Any:
    await ensure_vehicle_access(user, vehicle_id)
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/vehicles/{vehicle_id}/intakes",
    )
    raise_for_service_error(data, code)
    return data


@app.get("/vehicles/{vehicle_id}/history")
async def get_vehicle_history(vehicle_id: str, user: dict = Depends(current_user)) -> Any:
    await ensure_vehicle_access(user, vehicle_id)
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/vehicles/{vehicle_id}/history",
    )
    raise_for_service_error(data, code)
    return data


@app.post("/appointments", status_code=status.HTTP_201_CREATED)
async def create_appointment(
    payload: AppointmentCreate,
    response: Response,
    user: dict = Depends(current_user),
) -> Any:
    ensure_customer_access(user, payload.customer_id)
    vehicle = await ensure_vehicle_access(user, payload.vehicle_id)
    if vehicle["customer_id"] != payload.customer_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Vehicle does not belong to the customer",
        )
    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        "/appointments",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.get("/appointments")
async def list_appointments(
    workshop_id: str | None = None,
    customer_id: str | None = None,
    vehicle_id: str | None = None,
    user: dict = Depends(current_user),
) -> Any:
    if user["role"] == "client":
        customer_id = require_linked_customer(user)
    params = {
        k: v
        for k, v in {
            "workshop_id": workshop_id,
            "customer_id": customer_id,
            "vehicle_id": vehicle_id,
        }.items()
        if v
    }
    data, code = await request_json("GET", WORKSHOP_SERVICE_URL, "/appointments", params=params)
    raise_for_service_error(data, code)
    return data


@app.get("/appointments/{appointment_id}")
async def get_appointment(appointment_id: str, user: dict = Depends(current_user)) -> Any:
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/appointments/{appointment_id}",
    )
    raise_for_service_error(data, code)
    ensure_customer_access(user, data["customer_id"])
    return data


@app.patch("/appointments/{appointment_id}/status")
async def update_appointment_status(
    appointment_id: str,
    payload: AppointmentStatusUpdate,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "PATCH",
        WORKSHOP_SERVICE_URL,
        f"/appointments/{appointment_id}/status",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    return data


@app.post("/work-orders", status_code=status.HTTP_201_CREATED)
async def create_work_order(
    payload: WorkOrderCreate,
    response: Response,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    vehicle = await fetch_vehicle(payload.vehicle_id)
    if vehicle["customer_id"] != payload.customer_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Vehicle does not belong to the customer",
        )

    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        "/work-orders",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.get("/work-orders")
async def list_work_orders(
    status: str | None = None,
    workshop_id: str | None = None,
    customer_id: str | None = None,
    vehicle_id: str | None = None,
    user: dict = Depends(current_user),
) -> Any:
    if user["role"] == "client":
        customer_id = require_linked_customer(user)
    params = {
        "status": status,
        "workshop_id": workshop_id,
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
    }
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        "/work-orders",
        params={key: value for key, value in params.items() if value is not None},
    )
    raise_for_service_error(data, code)
    return data


@app.get("/work-orders/{order_id}")
async def get_work_order(order_id: str, user: dict = Depends(current_user)) -> Any:
    data, code = await request_json("GET", WORKSHOP_SERVICE_URL, f"/work-orders/{order_id}")
    raise_for_service_error(data, code)
    ensure_customer_access(user, data["customer_id"])
    return data


@app.patch("/work-orders/{order_id}/status")
async def update_work_order_status(
    order_id: str,
    payload: WorkOrderStatusUpdate,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "PATCH",
        WORKSHOP_SERVICE_URL,
        f"/work-orders/{order_id}/status",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    return data


@app.post("/work-orders/{order_id}/accept")
async def accept_work_order(
    order_id: str,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        f"/work-orders/{order_id}/accept",
    )
    raise_for_service_error(data, code)
    return data


@app.post("/work-orders/{order_id}/tasks", status_code=status.HTTP_201_CREATED)
async def add_work_order_task(
    order_id: str,
    payload: TaskCreate,
    response: Response,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        f"/work-orders/{order_id}/tasks",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.patch("/work-orders/{order_id}/tasks/{task_id}/status")
async def update_work_order_task_status(
    order_id: str,
    task_id: str,
    payload: TaskStatusUpdate,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "PATCH",
        WORKSHOP_SERVICE_URL,
        f"/work-orders/{order_id}/tasks/{task_id}/status",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    return data


@app.post("/quotes", status_code=status.HTTP_201_CREATED)
async def create_quote(
    payload: QuoteCreate,
    response: Response,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        "/quotes",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.post("/quotes/{quote_id}/items", status_code=status.HTTP_201_CREATED)
async def add_quote_item(
    quote_id: str,
    payload: QuoteItemCreate,
    response: Response,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        f"/quotes/{quote_id}/items",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.get("/quotes/{quote_id}")
async def get_quote(quote_id: str, user: dict = Depends(current_user)) -> Any:
    quote, code = await request_json("GET", WORKSHOP_SERVICE_URL, f"/quotes/{quote_id}")
    raise_for_service_error(quote, code)
    order, order_code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/work-orders/{quote['work_order_id']}",
    )
    raise_for_service_error(order, order_code)
    ensure_customer_access(user, order["customer_id"])
    return quote


@app.patch("/quotes/{quote_id}/items/{item_id}")
async def update_quote_item(
    quote_id: str,
    item_id: str,
    payload: QuoteItemUpdate,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "PATCH", WORKSHOP_SERVICE_URL, f"/quotes/{quote_id}/items/{item_id}",
        json=payload.model_dump(exclude_unset=True),
    )
    raise_for_service_error(data, code)
    return data


@app.delete("/quotes/{quote_id}/items/{item_id}")
async def delete_quote_item(
    quote_id: str,
    item_id: str,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json("DELETE", WORKSHOP_SERVICE_URL, f"/quotes/{quote_id}/items/{item_id}")
    raise_for_service_error(data, code)
    return data


@app.patch("/quotes/{quote_id}/status")
async def update_quote_status(
    quote_id: str,
    payload: QuoteStatusUpdate,
    user: dict = Depends(current_user),
) -> Any:
    quote, quote_code = await request_json("GET", WORKSHOP_SERVICE_URL, f"/quotes/{quote_id}")
    raise_for_service_error(quote, quote_code)
    order, order_code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/work-orders/{quote['work_order_id']}",
    )
    raise_for_service_error(order, order_code)
    ensure_customer_access(user, order["customer_id"])

    if payload.status in {"draft", "sent"} and user["role"] == "client":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client can only accept or reject")

    data, code = await request_json(
        "PATCH",
        WORKSHOP_SERVICE_URL,
        f"/quotes/{quote_id}/status",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    return data


@app.post("/work-orders/{order_id}/evidence", status_code=status.HTTP_201_CREATED)
async def add_evidence(
    order_id: str,
    payload: EvidenceCreate,
    response: Response,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        f"/work-orders/{order_id}/evidence",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.get("/work-orders/{order_id}/evidence")
async def list_evidence(order_id: str, user: dict = Depends(current_user)) -> Any:
    order, order_code = await request_json("GET", WORKSHOP_SERVICE_URL, f"/work-orders/{order_id}")
    raise_for_service_error(order, order_code)
    ensure_customer_access(user, order["customer_id"])
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/work-orders/{order_id}/evidence",
    )
    raise_for_service_error(data, code)
    return data


@app.post("/recommendations", status_code=status.HTTP_201_CREATED)
async def create_recommendation(
    payload: RecommendationCreate,
    response: Response,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        "/recommendations",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.get("/me/notifications")
async def list_my_notifications(
    unread_only: bool = False,
    user: dict = Depends(current_user),
) -> Any:
    customer_id = require_linked_customer(user)
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/customers/{customer_id}/notifications",
        params={"unread_only": unread_only},
    )
    raise_for_service_error(data, code)
    return data


@app.get("/me/notifications/unread-count")
async def my_notification_unread_count(user: dict = Depends(current_user)) -> Any:
    customer_id = require_linked_customer(user)
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/customers/{customer_id}/notifications/unread-count",
    )
    raise_for_service_error(data, code)
    return data


@app.patch("/me/notifications/read-all")
async def mark_my_notifications_read(user: dict = Depends(current_user)) -> Any:
    customer_id = require_linked_customer(user)
    data, code = await request_json(
        "PATCH",
        WORKSHOP_SERVICE_URL,
        f"/customers/{customer_id}/notifications/read-all",
    )
    raise_for_service_error(data, code)
    return data


@app.patch("/me/notifications/{notification_id}/read")
async def mark_my_notification_read(
    notification_id: str,
    user: dict = Depends(current_user),
) -> Any:
    current, current_code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/notifications/{notification_id}",
    )
    raise_for_service_error(current, current_code)
    ensure_customer_access(user, current["customer_id"])
    notification, notification_code = await request_json(
        "PATCH",
        WORKSHOP_SERVICE_URL,
        f"/notifications/{notification_id}/read",
    )
    raise_for_service_error(notification, notification_code)
    return notification


@app.get("/workshops/{workshop_id}/notifications")
async def list_workshop_notifications(
    workshop_id: str,
    unread_only: bool = False,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/workshops/{workshop_id}/notifications",
        params={"unread_only": unread_only},
    )
    raise_for_service_error(data, code)
    return data


@app.get("/workshops/{workshop_id}/notifications/unread-count")
async def workshop_notification_unread_count(
    workshop_id: str,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        f"/workshops/{workshop_id}/notifications/unread-count",
    )
    raise_for_service_error(data, code)
    return data


@app.patch("/workshops/{workshop_id}/notifications/read-all")
async def mark_workshop_notifications_read(
    workshop_id: str,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "PATCH",
        WORKSHOP_SERVICE_URL,
        f"/workshops/{workshop_id}/notifications/read-all",
    )
    raise_for_service_error(data, code)
    return data


@app.patch("/workshop-notifications/{notification_id}/read")
async def mark_workshop_notification_read(
    notification_id: str,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "PATCH",
        WORKSHOP_SERVICE_URL,
        f"/workshop-notifications/{notification_id}/read",
    )
    raise_for_service_error(data, code)
    return data


@app.post("/payments", status_code=status.HTTP_201_CREATED)
async def register_payment(
    payload: PaymentCreate,
    response: Response,
    _: dict = Depends(require_roles("staff", "admin")),
) -> Any:
    data, code = await request_json(
        "POST",
        WORKSHOP_SERVICE_URL,
        "/payments",
        json=payload.model_dump(),
    )
    raise_for_service_error(data, code)
    response.status_code = code
    return data


@app.get("/customers/{customer_id}/summary")
async def get_customer_summary(customer_id: str, user: dict = Depends(current_user)) -> dict:
    ensure_customer_access(user, customer_id)
    customer, customer_status = await request_json(
        "GET",
        CUSTOMERS_SERVICE_URL,
        f"/customers/{customer_id}",
    )
    raise_for_service_error(customer, customer_status)

    vehicles, vehicles_status = await request_json(
        "GET",
        CUSTOMERS_SERVICE_URL,
        f"/customers/{customer_id}/vehicles",
    )
    raise_for_service_error(vehicles, vehicles_status)

    orders, orders_status = await request_json(
        "GET",
        WORKSHOP_SERVICE_URL,
        "/work-orders",
        params={"customer_id": customer_id},
    )
    raise_for_service_error(orders, orders_status)

    return {
        "customer": customer,
        "vehicles": vehicles,
        "work_orders": orders,
    }


app.include_router(create_router(request_json, authenticate_user))
