"""Atomic customer/vehicle intake in the canonical customer database."""
import json

from fastapi import APIRouter, Depends, HTTPException, Response

from services.common.database import Connection, IntegrityError, table_columns, write_lock, connect
from services.common.internal import require_service_token
from services.common.time import utc_now_iso
from services.common.web_schemas import CustomerProvision, CustomerProfileProvision, VehicleLookup


def init_web_customers(db):
    columns = table_columns(db, "vehicles")
    db.execute("ALTER TABLE vehicles ALTER COLUMN plate DROP NOT NULL")
    if "web_details" not in columns:
        db.execute("ALTER TABLE vehicles ADD COLUMN web_details TEXT")
    customer_columns = table_columns(db, "customers")
    if "provisioned_via_web" not in customer_columns:
        db.execute("ALTER TABLE customers ADD COLUMN provisioned_via_web INTEGER NOT NULL DEFAULT 0")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicle_normalized_plate
        ON vehicles(UPPER(REPLACE(REPLACE(plate, '-', ''), ' ', ''))) WHERE plate IS NOT NULL AND plate != ''""")


def create_router(db_path):
    router = APIRouter(prefix="/internal/web", dependencies=[Depends(require_service_token)])

    @router.post("/customers/self-register", status_code=201)
    def self_register(payload: CustomerProfileProvision):
        with connect(db_path()) as db:
            db.execute("INSERT INTO customers (id, name, phone, email, created_at, provisioned_via_web) VALUES (%s, %s, %s, %s, %s, 1)",
                (payload.id, payload.nombre, payload.telefono, payload.email, utc_now_iso()))
        return {"id": payload.id}

    @router.post("/customers", status_code=201)
    def provision(payload: CustomerProvision):
        now = utc_now_iso()
        intake = payload.intake
        vehicle = intake.vehiculo
        details = {"cilindros": vehicle.cilindros, "combustible": vehicle.combustible,
                   "kilometraje": vehicle.kilometraje, "registradoPor": payload.actor_id,
                   "tallerRegistroId": payload.workshop_id, **({"foto": vehicle.foto} if vehicle.foto else {})}
        with connect(db_path()) as db:
            try:
                db.execute("""INSERT INTO customers (id, name, phone, email, created_at, provisioned_via_web)
                    VALUES (%s, %s, %s, NULL, %s, 1)""", (payload.id, intake.nombre, intake.telefono, now))
                db.execute("""INSERT INTO vehicles (id, customer_id, plate, vin, brand, model, year, color,
                    owner_name, created_at, web_details) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (payload.vehicle_id, payload.id, vehicle.placas or None, vehicle.numeroSerie, vehicle.marca,
                     vehicle.modelo, vehicle.anio, vehicle.color, intake.nombre, now, json.dumps(details, ensure_ascii=False)))
            except IntegrityError as error:
                raise HTTPException(409, "Ya existe un vehículo con estas placas o VIN.") from error
            return dict(db.execute("SELECT * FROM vehicles WHERE id = %s", (payload.vehicle_id,)).fetchone())

    @router.delete("/customers/{customer_id}", status_code=204)
    def abort(customer_id: str):
        with connect(db_path()) as db:
            db.execute("DELETE FROM customers WHERE id = %s AND provisioned_via_web = 1", (customer_id,))
        return Response(status_code=204)

    @router.post("/vehicles/lookup")
    def lookup(payload: VehicleLookup):
        with connect(db_path()) as db:
            if payload.customer_id:
                rows = db.execute("SELECT * FROM vehicles WHERE customer_id = %s ORDER BY created_at", (payload.customer_id,)).fetchall()
            elif payload.vehicle_ids:
                placeholders = ",".join("%s" for _ in payload.vehicle_ids)
                rows = db.execute(f"SELECT * FROM vehicles WHERE id IN ({placeholders})", payload.vehicle_ids).fetchall()
            else:
                rows = []
        return [dict(row) for row in rows]

    return router
