from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, HTTPException, status

from services.common.database import Connection, IntegrityError, table_columns, write_lock, connect, database_url_from_env
from services.common.time import utc_now_iso
from services.customer_service.web import create_router, init_web_customers
from services.customer_service.schemas import (
    CustomerCreate,
    CustomerOut,
    VehicleCreate,
    VehicleOut,
    VehicleUpdate,
)

DATABASE_URL = database_url_from_env("CUSTOMERS_DATABASE_URL")

app = FastAPI(
    title="Villavis Customer Service",
    description="Microservicio de clientes y vehiculos del taller.",
    version="1.0.0",
)


def row_to_dict(row: dict | None) -> dict | None:
    return dict(row) if row else None


def ensure_vehicle_columns(db: Connection) -> None:
    existing = table_columns(db, "vehicles")
    columns = {
        "vehicle_type": "TEXT",
        "engine_number": "TEXT",
        "service_type": "TEXT",
        "owner_name": "TEXT",
    }
    for column, column_type in columns.items():
        if column not in existing:
            db.execute(f"ALTER TABLE vehicles ADD COLUMN {column} {column_type}")


def init_db(db_path: str | None = None) -> None:
    with connect(db_path or DATABASE_URL) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS vehicles (
                id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                plate TEXT UNIQUE,
                vin TEXT UNIQUE,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                year INTEGER,
                vehicle_type TEXT,
                color TEXT,
                engine_number TEXT,
                service_type TEXT,
                owner_name TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
            )
            """
        )
        ensure_vehicle_columns(db)
        init_web_customers(db)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    try:
        with connect(DATABASE_URL) as db:
            db.execute("SELECT 1")
    except Exception:
        raise HTTPException(503, "PostgreSQL is unavailable")
    return {"service": "customer_service", "status": "ok"}


@app.post("/customers", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate) -> dict:
    customer = {
        "id": str(uuid4()),
        "name": payload.name.strip(),
        "phone": payload.phone.strip(),
        "email": payload.email.strip() if payload.email else None,
        "created_at": utc_now_iso(),
    }

    with connect(DATABASE_URL) as db:
        db.execute(
            """
            INSERT INTO customers (id, name, phone, email, created_at)
            VALUES (%(id)s, %(name)s, %(phone)s, %(email)s, %(created_at)s)
            """,
            customer,
        )

    return customer


@app.get("/customers", response_model=list[CustomerOut])
def list_customers() -> list[dict]:
    with connect(DATABASE_URL) as db:
        rows = db.execute("SELECT * FROM customers ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


@app.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: str) -> dict:
    with connect(DATABASE_URL) as db:
        row = db.execute("SELECT * FROM customers WHERE id = %s", (customer_id,)).fetchone()

    customer = row_to_dict(row)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@app.post("/customers/{customer_id}/vehicles", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
def create_vehicle(customer_id: str, payload: VehicleCreate) -> dict:
    with connect(DATABASE_URL) as db:
        customer = db.execute("SELECT id FROM customers WHERE id = %s", (customer_id,)).fetchone()
        if not customer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

        vehicle = {
            "id": str(uuid4()),
            "customer_id": customer_id,
            "plate": payload.plate.strip().upper(),
            "vin": payload.vin.strip().upper(),
            "brand": payload.brand.strip(),
            "model": payload.model.strip(),
            "year": payload.year,
            "vehicle_type": payload.vehicle_type.strip() if payload.vehicle_type else None,
            "color": payload.color.strip() if payload.color else None,
            "engine_number": payload.engine_number.strip().upper() if payload.engine_number else None,
            "service_type": payload.service_type.strip() if payload.service_type else None,
            "owner_name": payload.owner_name.strip() if payload.owner_name else None,
            "created_at": utc_now_iso(),
        }

        try:
            db.execute(
                """
                INSERT INTO vehicles (
                    id, customer_id, plate, vin, brand, model, year, vehicle_type,
                    color, engine_number, service_type, owner_name, created_at
                )
                VALUES (
                    %(id)s, %(customer_id)s, %(plate)s, %(vin)s, %(brand)s, %(model)s, %(year)s, %(vehicle_type)s,
                    %(color)s, %(engine_number)s, %(service_type)s, %(owner_name)s, %(created_at)s
                )
                """,
                vehicle,
            )
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Vehicle plate or VIN already exists",
            ) from exc

    return vehicle


@app.get("/customers/{customer_id}/vehicles", response_model=list[VehicleOut])
def list_customer_vehicles(customer_id: str) -> list[dict]:
    with connect(DATABASE_URL) as db:
        customer = db.execute("SELECT id FROM customers WHERE id = %s", (customer_id,)).fetchone()
        if not customer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

        rows = db.execute(
            "SELECT * FROM vehicles WHERE customer_id = %s ORDER BY created_at DESC",
            (customer_id,),
        ).fetchall()

    return [dict(row) for row in rows]


@app.get("/vehicles/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(vehicle_id: str) -> dict:
    with connect(DATABASE_URL) as db:
        row = db.execute("SELECT * FROM vehicles WHERE id = %s", (vehicle_id,)).fetchone()

    vehicle = row_to_dict(row)
    if not vehicle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle


@app.patch("/vehicles/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(vehicle_id: str, payload: VehicleUpdate) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    normalized = {}
    for key, value in changes.items():
        if isinstance(value, str):
            value = value.strip()
        if key in {"plate", "vin", "engine_number"} and value:
            value = value.upper()
        normalized[key] = value

    assignments = ", ".join(f"{key} = %s" for key in normalized)
    params = list(normalized.values()) + [vehicle_id]

    with connect(DATABASE_URL) as db:
        current = db.execute("SELECT id FROM vehicles WHERE id = %s", (vehicle_id,)).fetchone()
        if not current:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

        try:
            db.execute(f"UPDATE vehicles SET {assignments} WHERE id = %s", params)
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Vehicle plate or VIN already exists",
            ) from exc

        updated = db.execute("SELECT * FROM vehicles WHERE id = %s", (vehicle_id,)).fetchone()

    return dict(updated)


@app.get("/vehicles/by-plate/{plate}", response_model=VehicleOut)
def get_vehicle_by_plate(plate: str) -> dict:
    with connect(DATABASE_URL) as db:
        row = db.execute("SELECT * FROM vehicles WHERE plate = %s", (plate.strip().upper(),)).fetchone()

    vehicle = row_to_dict(row)
    if not vehicle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle


@app.get("/vehicles/by-vin/{vin}", response_model=VehicleOut)
def get_vehicle_by_vin(vin: str) -> dict:
    with connect(DATABASE_URL) as db:
        row = db.execute("SELECT * FROM vehicles WHERE vin = %s", (vin.strip().upper(),)).fetchone()

    vehicle = row_to_dict(row)
    if not vehicle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle


app.include_router(create_router(lambda: DATABASE_URL))

from services.customer_service.web_sync import create_router as create_sync_router
app.include_router(create_sync_router(lambda: DATABASE_URL))
