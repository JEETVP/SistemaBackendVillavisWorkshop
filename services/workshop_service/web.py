"""Workshop ownership and intake orders for the React compatibility contract."""
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response

from services.common.database import connect
from services.common.internal import require_service_token
from services.common.time import utc_now_iso
from services.common.web_schemas import OrderProvision, WorkshopProvision


def init_web_workshops(db):
    from services.workshop_service.web_sync import init_schema
    init_schema(db)
    for table, additions in {"workshops": {"owner_id": "TEXT", "location_json": "TEXT"},
                             "work_orders": {"web_details": "TEXT"}}.items():
        existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        for name, sql_type in additions.items():
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_workshops_owner ON workshops(owner_id) WHERE owner_id IS NOT NULL")


def create_router(db_path):
    router = APIRouter(prefix="/internal/web", dependencies=[Depends(require_service_token)])

    @router.post("/workshops", status_code=201)
    def provision_workshop(payload: WorkshopProvision):
        now = utc_now_iso()
        location = payload.ubicacion.model_dump()
        with connect(db_path()) as db:
            try:
                db.execute("""INSERT INTO workshops (id, name, address, active, created_at, owner_id, location_json)
                    VALUES (?, ?, ?, 1, ?, ?, ?)""", (payload.id, payload.nombre,
                    ", ".join([location["direccion"], location["ciudad"], location["estado"], location["codigoPostal"]]),
                    now, payload.owner_id, json.dumps(location, ensure_ascii=False)))
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, "El taller o encargado ya están registrados.") from error
            return dict(db.execute("SELECT * FROM workshops WHERE id = ?", (payload.id,)).fetchone())

    @router.delete("/workshops/{workshop_id}", status_code=204)
    def abort_workshop(workshop_id: str):
        with connect(db_path()) as db:
            db.execute("DELETE FROM workshops WHERE id = ? AND owner_id IS NOT NULL", (workshop_id,))
        return Response(status_code=204)

    @router.get("/workshops")
    def directory():
        with connect(db_path()) as db:
            rows = db.execute("""SELECT w.*, (SELECT count(*) FROM work_orders o WHERE o.workshop_id = w.id
                AND o.status NOT IN ('delivered', 'cancelled')) AS active_orders
                FROM workshops w WHERE w.active = 1 ORDER BY w.name""").fetchall()
        return [dict(row) for row in rows]

    @router.post("/orders", status_code=201)
    def provision_order(payload: OrderProvision):
        now = utc_now_iso()
        with connect(db_path()) as db:
            if not db.execute("SELECT id FROM workshops WHERE id = ? AND active = 1", (payload.workshop_id,)).fetchone():
                raise HTTPException(404, "No se encontró el taller.")
            try:
                db.execute("""INSERT INTO work_orders (id, workshop_id, customer_id, vehicle_id, description,
                    priority, status, estimated_total, created_at, updated_at, web_details)
                    VALUES (?, ?, ?, ?, ?, 'normal', 'diagnosis', 0, ?, ?, ?)""", (payload.id, payload.workshop_id,
                    payload.customer_id, payload.vehicle_id, payload.description, now, now, json.dumps({"web_intake": True})))
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, "La orden ya está registrada.") from error
            return dict(db.execute("SELECT * FROM work_orders WHERE id = ?", (payload.id,)).fetchone())

    @router.delete("/orders/{order_id}", status_code=204)
    def abort_order(order_id: str):
        with connect(db_path()) as db:
            db.execute("DELETE FROM work_orders WHERE id = ? AND json_extract(web_details, '$.web_intake') = 1", (order_id,))
        return Response(status_code=204)

    @router.get("/orders")
    def orders(workshop_id: str | None = None, customer_id: str | None = None):
        if bool(workshop_id) == bool(customer_id):
            raise HTTPException(422, "Specify exactly one order scope")
        field, value = ("workshop_id", workshop_id) if workshop_id else ("customer_id", customer_id)
        with connect(db_path()) as db:
            rows = db.execute(f"SELECT * FROM work_orders WHERE {field} = ? ORDER BY created_at", (value,)).fetchall()
        return [dict(row) for row in rows]

    return router
