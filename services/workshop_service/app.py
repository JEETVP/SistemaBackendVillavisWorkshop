from __future__ import annotations

import sqlite3
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, status

from services.common.database import connect, db_path_from_env
from services.common.time import utc_now_iso
from services.workshop_service.web import create_router, init_web_workshops
from services.workshop_service.schemas import (
    AppointmentCreate,
    AppointmentDetail,
    AppointmentOut,
    AppointmentStatus,
    AppointmentStatusUpdate,
    AppNotificationOut,
    CartCheckoutOut,
    CylinderCount,
    EvidenceCreate,
    EvidenceOut,
    PaymentCreate,
    PaymentOut,
    PaymentStatus,
    Priority,
    QuoteCreate,
    QuoteItemCreate,
    QuoteItemUpdate,
    QuoteOut,
    QuoteStatus,
    QuoteStatusUpdate,
    RecommendationCreate,
    RecommendationOut,
    AdminDashboardOut,
    ServiceCartCheckoutCreate,
    ServiceCartCreate,
    ServiceCartItemCreate,
    ServiceCartItemUpdate,
    ServiceCartOut,
    WorkshopReportOut,
    ServiceCreate,
    ServiceOut,
    ServicePriceOut,
    ServiceUpdate,
    TaskCreate,
    TaskOut,
    TaskStatus,
    TaskStatusUpdate,
    NotificationCountOut,
    NotificationBulkUpdateOut,
    VehicleIntakeCreate,
    VehicleIntakeOut,
    WorkshopNotificationOut,
    WorkshopCreate,
    WorkshopOut,
    WorkshopUpdate,
    WorkOrderCreate,
    WorkOrderDetail,
    WorkOrderOut,
    WorkOrderStatus,
    WorkOrderStatusUpdate,
)

DB_PATH = db_path_from_env("WORKSHOP_DB_PATH", "data/workshop.db")

app = FastAPI(
    title="Villavis Workshop Service",
    description="Microservicio de servicios, citas, cotizaciones y ordenes de trabajo.",
    version="1.0.0",
)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def ensure_columns(db: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    for column, column_type in columns.items():
        if column not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def init_db(db_path: str | None = None) -> None:
    with connect(db_path or DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS workshops (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                photo_url TEXT,
                phone TEXT,
                description TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS service_catalog (
                id TEXT PRIMARY KEY,
                workshop_id TEXT,
                name TEXT NOT NULL,
                service_type TEXT,
                description TEXT,
                priority_rank INTEGER NOT NULL DEFAULT 2,
                price_3_cyl REAL NOT NULL DEFAULT 0,
                price_4_cyl REAL NOT NULL DEFAULT 0,
                price_6_cyl REAL NOT NULL DEFAULT 0,
                price_8_cyl REAL NOT NULL DEFAULT 0,
                parts_brand TEXT,
                supplies_brand TEXT,
                base_price REAL NOT NULL DEFAULT 0,
                estimated_minutes INTEGER,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workshop_id) REFERENCES workshops(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS appointments (
                id TEXT PRIMARY KEY,
                workshop_id TEXT,
                customer_id TEXT NOT NULL,
                vehicle_id TEXT NOT NULL,
                intake_id TEXT,
                requested_at TEXT NOT NULL,
                notes TEXT,
                status TEXT NOT NULL,
                estimated_total REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS work_orders (
                id TEXT PRIMARY KEY,
                workshop_id TEXT,
                customer_id TEXT NOT NULL,
                vehicle_id TEXT NOT NULL,
                appointment_id TEXT,
                description TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                estimated_total REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        ensure_columns(
            db,
            "service_catalog",
            {
                "workshop_id": "TEXT",
                "service_type": "TEXT",
                "priority_rank": "INTEGER NOT NULL DEFAULT 2",
                "price_3_cyl": "REAL NOT NULL DEFAULT 0",
                "price_4_cyl": "REAL NOT NULL DEFAULT 0",
                "price_6_cyl": "REAL NOT NULL DEFAULT 0",
                "price_8_cyl": "REAL NOT NULL DEFAULT 0",
                "parts_brand": "TEXT",
                "supplies_brand": "TEXT",
            },
        )
        ensure_columns(
            db,
            "appointments",
            {
                "workshop_id": "TEXT",
                "intake_id": "TEXT",
                "estimated_total": "REAL NOT NULL DEFAULT 0",
            },
        )
        ensure_columns(db, "work_orders", {"workshop_id": "TEXT"})
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS vehicle_intakes (
                id TEXT PRIMARY KEY,
                workshop_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                vehicle_id TEXT NOT NULL,
                has_tapones INTEGER NOT NULL DEFAULT 0,
                has_virlos INTEGER NOT NULL DEFAULT 0,
                has_tapa_gasolina INTEGER NOT NULL DEFAULT 0,
                has_rines INTEGER NOT NULL DEFAULT 0,
                has_ceniceros INTEGER NOT NULL DEFAULT 0,
                has_llanta_refaccion INTEGER NOT NULL DEFAULT 0,
                detail_notes TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workshop_id) REFERENCES workshops(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS vehicle_intake_photos (
                id TEXT PRIMARY KEY,
                intake_id TEXT NOT NULL,
                photo_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (intake_id) REFERENCES vehicle_intakes(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS appointment_services (
                id TEXT PRIMARY KEY,
                appointment_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                service_name TEXT NOT NULL,
                cylinder_count INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL DEFAULT 0,
                estimated_total REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
                FOREIGN KEY (service_id) REFERENCES service_catalog(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS service_carts (
                id TEXT PRIMARY KEY,
                workshop_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                vehicle_id TEXT NOT NULL,
                intake_id TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                subtotal REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (workshop_id) REFERENCES workshops(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS service_cart_items (
                id TEXT PRIMARY KEY,
                cart_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                service_name TEXT NOT NULL,
                service_type TEXT NOT NULL,
                priority_rank INTEGER NOT NULL DEFAULT 2,
                cylinder_count INTEGER NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL DEFAULT 0,
                line_total REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (cart_id) REFERENCES service_carts(id) ON DELETE CASCADE,
                FOREIGN KEY (service_id) REFERENCES service_catalog(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS work_order_tasks (
                id TEXT PRIMARY KEY,
                work_order_id TEXT NOT NULL,
                service_id TEXT,
                name TEXT NOT NULL,
                price REAL NOT NULL DEFAULT 0,
                priority TEXT NOT NULL DEFAULT 'normal',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY (work_order_id) REFERENCES work_orders(id) ON DELETE CASCADE
            )
            """
        )
        ensure_columns(db, "work_order_tasks", {"updated_at": "TEXT"})
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS quotes (
                id TEXT PRIMARY KEY,
                work_order_id TEXT NOT NULL,
                status TEXT NOT NULL,
                subtotal REAL NOT NULL DEFAULT 0,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (work_order_id) REFERENCES work_orders(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS quote_items (
                id TEXT PRIMARY KEY,
                quote_id TEXT NOT NULL,
                service_id TEXT,
                cylinder_count INTEGER,
                description TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL DEFAULT 0,
                total REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (quote_id) REFERENCES quotes(id) ON DELETE CASCADE
            )
            """
        )
        ensure_columns(db, "quote_items", {"cylinder_count": "INTEGER"})
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                work_order_id TEXT NOT NULL,
                file_url TEXT NOT NULL,
                caption TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (work_order_id) REFERENCES work_orders(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendations (
                id TEXT PRIMARY KEY,
                vehicle_id TEXT NOT NULL,
                title TEXT NOT NULL,
                notes TEXT,
                priority TEXT NOT NULL,
                due_date TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                work_order_id TEXT NOT NULL,
                amount REAL NOT NULL,
                provider TEXT NOT NULL,
                reference TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (work_order_id) REFERENCES work_orders(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS appointment_payment_requests (
                id TEXT PRIMARY KEY,
                appointment_id TEXT NOT NULL,
                cart_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                vehicle_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                service_total REAL NOT NULL,
                deposit_percentage INTEGER NOT NULL,
                deposit_amount REAL NOT NULL,
                payment_link TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
                FOREIGN KEY (cart_id) REFERENCES service_carts(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS purchase_tickets (
                id TEXT PRIMARY KEY,
                ticket_number TEXT NOT NULL UNIQUE,
                appointment_id TEXT NOT NULL,
                payment_request_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                vehicle_id TEXT NOT NULL,
                service_total REAL NOT NULL,
                deposit_percentage INTEGER NOT NULL,
                deposit_amount REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
                FOREIGN KEY (payment_request_id) REFERENCES appointment_payment_requests(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS app_notifications (
                id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                related_entity_type TEXT,
                related_entity_id TEXT,
                read_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS workshop_notifications (
                id TEXT PRIMARY KEY,
                workshop_id TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                related_entity_type TEXT,
                related_entity_id TEXT,
                read_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workshop_id) REFERENCES workshops(id) ON DELETE CASCADE
            )
            """
        )


def fetch_work_order(db: sqlite3.Connection, order_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM work_orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    return row


def fetch_workshop(db: sqlite3.Connection, workshop_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM workshops WHERE id = ?", (workshop_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workshop not found")
    return row


def fetch_service(db: sqlite3.Connection, service_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM service_catalog WHERE id = ?", (service_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return row


def fetch_cart(db: sqlite3.Connection, cart_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM service_carts WHERE id = ?", (cart_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service cart not found")
    return row


def service_price_for_cylinders(service: sqlite3.Row | dict, cylinder_count: CylinderCount) -> float:
    key = f"price_{cylinder_count.value}_cyl"
    return float(service[key] or 0)


def priority_summary_for_cart(db: sqlite3.Connection, cart_id: str) -> list[dict]:
    rows = db.execute(
        """
        SELECT priority_rank, COUNT(*) AS item_count, COALESCE(SUM(line_total), 0) AS total
        FROM service_cart_items
        WHERE cart_id = ?
        GROUP BY priority_rank
        ORDER BY priority_rank ASC
        """,
        (cart_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def cart_with_items(db: sqlite3.Connection, cart_id: str) -> dict:
    cart = fetch_cart(db, cart_id)
    items = db.execute(
        """
        SELECT id, cart_id, service_id, service_name, service_type, priority_rank,
               cylinder_count, quantity, unit_price, line_total
        FROM service_cart_items
        WHERE cart_id = ?
        ORDER BY priority_rank ASC, created_at ASC
        """,
        (cart_id,),
    ).fetchall()
    data = dict(cart)
    data["items"] = [dict(row) for row in items]
    data["priority_summary"] = priority_summary_for_cart(db, cart_id)
    return data


def recalculate_cart(db: sqlite3.Connection, cart_id: str) -> None:
    subtotal = db.execute(
        "SELECT COALESCE(SUM(line_total), 0) AS subtotal FROM service_cart_items WHERE cart_id = ?",
        (cart_id,),
    ).fetchone()["subtotal"]
    db.execute(
        "UPDATE service_carts SET subtotal = ?, updated_at = ? WHERE id = ?",
        (subtotal, utc_now_iso(), cart_id),
    )


def notification_row(
    customer_id: str,
    title: str,
    message: str,
    notification_type: str,
    related_entity_type: str | None,
    related_entity_id: str | None,
) -> dict:
    return {
        "id": str(uuid4()),
        "customer_id": customer_id,
        "title": title,
        "message": message,
        "notification_type": notification_type,
        "related_entity_type": related_entity_type,
        "related_entity_id": related_entity_id,
        "read_at": None,
        "created_at": utc_now_iso(),
    }


def insert_notification(db: sqlite3.Connection, notification: dict) -> None:
    db.execute(
        """
        INSERT INTO app_notifications (
            id, customer_id, title, message, notification_type,
            related_entity_type, related_entity_id, read_at, created_at
        )
        VALUES (
            :id, :customer_id, :title, :message, :notification_type,
            :related_entity_type, :related_entity_id, :read_at, :created_at
        )
        """,
        notification,
    )


def workshop_notification_row(
    workshop_id: str,
    title: str,
    message: str,
    notification_type: str,
    related_entity_type: str | None,
    related_entity_id: str | None,
) -> dict:
    return {
        "id": str(uuid4()),
        "workshop_id": workshop_id,
        "title": title,
        "message": message,
        "notification_type": notification_type,
        "related_entity_type": related_entity_type,
        "related_entity_id": related_entity_id,
        "read_at": None,
        "created_at": utc_now_iso(),
    }


def insert_workshop_notification(db: sqlite3.Connection, notification: dict) -> None:
    db.execute(
        """
        INSERT INTO workshop_notifications (
            id, workshop_id, title, message, notification_type,
            related_entity_type, related_entity_id, read_at, created_at
        )
        VALUES (
            :id, :workshop_id, :title, :message, :notification_type,
            :related_entity_type, :related_entity_id, :read_at, :created_at
        )
        """,
        notification,
    )


def priority_from_rank(priority_rank: int) -> str:
    return {1: Priority.urgent.value, 2: Priority.normal.value, 3: Priority.low.value}.get(
        priority_rank,
        Priority.normal.value,
    )


def work_order_with_detail(db: sqlite3.Connection, order_id: str) -> dict:
    order = db.execute("SELECT * FROM work_orders WHERE id = ?", (order_id,)).fetchone()
    tasks = db.execute(
        "SELECT * FROM work_order_tasks WHERE work_order_id = ? ORDER BY created_at ASC",
        (order_id,),
    ).fetchall()
    quotes = db.execute(
        "SELECT id FROM quotes WHERE work_order_id = ? ORDER BY created_at DESC",
        (order_id,),
    ).fetchall()
    evidence = db.execute(
        "SELECT * FROM evidence WHERE work_order_id = ? ORDER BY created_at DESC",
        (order_id,),
    ).fetchall()
    payments = db.execute(
        "SELECT * FROM payments WHERE work_order_id = ? ORDER BY created_at DESC",
        (order_id,),
    ).fetchall()

    work_order = row_to_dict(order)
    if not work_order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")

    task_rows = [dict(row) for row in tasks]
    total_tasks = len(task_rows)
    completed_tasks = len([task for task in task_rows if task["status"] == TaskStatus.done.value])
    work_order["tasks"] = task_rows
    work_order["quotes"] = [quote_with_items(db, row["id"]) for row in quotes]
    work_order["evidence"] = [dict(row) for row in evidence]
    work_order["payments"] = [dict(row) for row in payments]
    work_order["total_tasks"] = total_tasks
    work_order["completed_tasks"] = completed_tasks
    work_order["progress_percent"] = round((completed_tasks / total_tasks) * 100, 2) if total_tasks else 0
    return work_order


def scoped_count(
    db: sqlite3.Connection,
    table: str,
    filters: list[str],
    params: list[str | int | float],
) -> int:
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    return int(db.execute(f"SELECT COUNT(*) AS total FROM {table} {where}", params).fetchone()["total"])


def scoped_sum(
    db: sqlite3.Connection,
    table: str,
    column: str,
    filters: list[str],
    params: list[str | int | float],
) -> float:
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    row = db.execute(
        f"SELECT COALESCE(SUM({column}), 0) AS total FROM {table} {where}",
        params,
    ).fetchone()
    return float(row["total"] or 0)


def date_scoped_filters(
    table_alias: str,
    date_from: str | None,
    date_to: str | None,
) -> tuple[list[str], list[str]]:
    filters: list[str] = []
    params: list[str] = []
    if date_from:
        filters.append(f"{table_alias}.created_at >= ?")
        params.append(date_from)
    if date_to:
        filters.append(f"{table_alias}.created_at <= ?")
        params.append(date_to)
    return filters, params


def add_cart_item_row(db: sqlite3.Connection, cart: sqlite3.Row, payload: ServiceCartItemCreate) -> dict:
    service = fetch_service(db, payload.service_id)
    if service["workshop_id"] != cart["workshop_id"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Service does not belong to selected workshop",
        )
    if not service["active"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Service is not active",
        )

    unit_price = service_price_for_cylinders(service, payload.cylinder_count)
    item = {
        "id": str(uuid4()),
        "cart_id": cart["id"],
        "service_id": service["id"],
        "service_name": service["name"],
        "service_type": service["service_type"],
        "priority_rank": service["priority_rank"],
        "cylinder_count": payload.cylinder_count.value,
        "quantity": payload.quantity,
        "unit_price": unit_price,
        "line_total": unit_price * payload.quantity,
        "created_at": utc_now_iso(),
    }
    db.execute(
        """
        INSERT INTO service_cart_items (
            id, cart_id, service_id, service_name, service_type, priority_rank,
            cylinder_count, quantity, unit_price, line_total, created_at
        )
        VALUES (
            :id, :cart_id, :service_id, :service_name, :service_type, :priority_rank,
            :cylinder_count, :quantity, :unit_price, :line_total, :created_at
        )
        """,
        item,
    )
    return item


def update_cart_item_row(
    db: sqlite3.Connection,
    cart: sqlite3.Row,
    item_id: str,
    payload: ServiceCartItemUpdate,
) -> dict:
    item = db.execute(
        "SELECT * FROM service_cart_items WHERE id = ? AND cart_id = ?",
        (item_id, cart["id"]),
    ).fetchone()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found")

    service = fetch_service(db, item["service_id"])
    cylinder_count = payload.cylinder_count or CylinderCount(item["cylinder_count"])
    quantity = payload.quantity if payload.quantity is not None else item["quantity"]
    unit_price = service_price_for_cylinders(service, cylinder_count)
    line_total = unit_price * quantity
    db.execute(
        """
        UPDATE service_cart_items
        SET cylinder_count = ?, quantity = ?, unit_price = ?, line_total = ?
        WHERE id = ? AND cart_id = ?
        """,
        (cylinder_count.value, quantity, unit_price, line_total, item_id, cart["id"]),
    )
    updated = db.execute(
        "SELECT * FROM service_cart_items WHERE id = ? AND cart_id = ?",
        (item_id, cart["id"]),
    ).fetchone()
    return dict(updated)


def add_quote_item_row(db: sqlite3.Connection, quote_id: str, payload: QuoteItemCreate) -> dict:
    unit_price = payload.unit_price
    if payload.service_id and payload.cylinder_count and unit_price == 0:
        service = fetch_service(db, payload.service_id)
        unit_price = service_price_for_cylinders(service, payload.cylinder_count)

    item = {
        "id": str(uuid4()),
        "quote_id": quote_id,
        "service_id": payload.service_id,
        "cylinder_count": payload.cylinder_count.value if payload.cylinder_count else None,
        "description": payload.description.strip(),
        "quantity": payload.quantity,
        "unit_price": unit_price,
        "total": payload.quantity * unit_price,
    }
    db.execute(
        """
        INSERT INTO quote_items (
            id, quote_id, service_id, cylinder_count, description, quantity, unit_price, total
        )
        VALUES (
            :id, :quote_id, :service_id, :cylinder_count,
            :description, :quantity, :unit_price, :total
        )
        """,
        item,
    )
    return item


def recalculate_quote(db: sqlite3.Connection, quote_id: str) -> None:
    subtotal = db.execute(
        "SELECT COALESCE(SUM(total), 0) AS subtotal FROM quote_items WHERE quote_id = ?",
        (quote_id,),
    ).fetchone()["subtotal"]
    db.execute(
        "UPDATE quotes SET subtotal = ?, updated_at = ? WHERE id = ?",
        (subtotal, utc_now_iso(), quote_id),
    )


def quote_with_items(db: sqlite3.Connection, quote_id: str) -> dict:
    quote = db.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
    if not quote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")

    items = db.execute(
        "SELECT * FROM quote_items WHERE quote_id = ? ORDER BY rowid ASC",
        (quote_id,),
    ).fetchall()
    data = dict(quote)
    data["items"] = [dict(item) for item in items]
    return data


def ensure_quote_editable(quote: dict) -> None:
    if quote["status"] in {QuoteStatus.accepted.value, QuoteStatus.rejected.value}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Resolved quotes cannot be edited")


def appointment_with_services(db: sqlite3.Connection, appointment_id: str) -> dict:
    appointment = db.execute(
        "SELECT * FROM appointments WHERE id = ?",
        (appointment_id,),
    ).fetchone()
    if not appointment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    services = db.execute(
        """
        SELECT *
        FROM appointment_services
        WHERE appointment_id = ?
        ORDER BY rowid ASC
        """,
        (appointment_id,),
    ).fetchall()
    data = dict(appointment)
    data["services"] = [dict(row) for row in services]
    return data


def intake_with_photos(db: sqlite3.Connection, intake_id: str) -> dict:
    intake = db.execute("SELECT * FROM vehicle_intakes WHERE id = ?", (intake_id,)).fetchone()
    if not intake:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle intake not found")

    photos = db.execute(
        "SELECT * FROM vehicle_intake_photos WHERE intake_id = ? ORDER BY created_at ASC",
        (intake_id,),
    ).fetchall()
    data = dict(intake)
    data["photos"] = [dict(row) for row in photos]
    data["photo_urls"] = [row["photo_url"] for row in photos]
    return data


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    with connect(DB_PATH) as db:
        init_web_workshops(db)


@app.get("/health")
def health() -> dict:
    return {"service": "workshop_service", "status": "ok"}


@app.get("/admin/dashboard", response_model=AdminDashboardOut)
def admin_dashboard(workshop_id: str | None = None) -> dict:
    active_statuses = [
        WorkOrderStatus.received.value,
        WorkOrderStatus.diagnosis.value,
        WorkOrderStatus.awaiting_approval.value,
        WorkOrderStatus.approved.value,
        WorkOrderStatus.in_progress.value,
    ]
    with connect(DB_PATH) as db:
        if workshop_id:
            fetch_workshop(db, workshop_id)

        appointment_filters = ["status = ?"]
        appointment_params: list[str | int | float] = [AppointmentStatus.requested.value]
        order_filters: list[str] = []
        order_params: list[str | int | float] = []
        notification_filters = ["read_at IS NULL"]
        notification_params: list[str | int | float] = []
        payment_filters = ["status = ?"]
        payment_params: list[str | int | float] = [PaymentStatus.pending.value]

        if workshop_id:
            appointment_filters.append("workshop_id = ?")
            appointment_params.append(workshop_id)
            order_filters.append("workshop_id = ?")
            order_params.append(workshop_id)
            notification_filters.append("workshop_id = ?")
            notification_params.append(workshop_id)
            payment_filters.append(
                "appointment_id IN (SELECT id FROM appointments WHERE workshop_id = ?)"
            )
            payment_params.append(workshop_id)

        received_order_filters = order_filters + ["status = ?"]
        received_order_params = order_params + [WorkOrderStatus.received.value]
        active_order_filters = order_filters + [
            f"status IN ({','.join('?' for _ in active_statuses)})"
        ]
        active_order_params = order_params + active_statuses
        ready_order_filters = order_filters + ["status = ?"]
        ready_order_params = order_params + [WorkOrderStatus.ready.value]
        open_revenue_filters = order_filters + ["status != ?", "status != ?"]
        open_revenue_params = order_params + [
            WorkOrderStatus.cancelled.value,
            WorkOrderStatus.delivered.value,
        ]

        return {
            "workshop_id": workshop_id,
            "pending_appointments": scoped_count(
                db,
                "appointments",
                appointment_filters,
                appointment_params,
            ),
            "received_orders": scoped_count(
                db,
                "work_orders",
                received_order_filters,
                received_order_params,
            ),
            "active_orders": scoped_count(db, "work_orders", active_order_filters, active_order_params),
            "ready_orders": scoped_count(db, "work_orders", ready_order_filters, ready_order_params),
            "unread_workshop_notifications": scoped_count(
                db,
                "workshop_notifications",
                notification_filters,
                notification_params,
            ),
            "pending_payment_requests": scoped_count(
                db,
                "appointment_payment_requests",
                payment_filters,
                payment_params,
            ),
            "estimated_open_revenue": scoped_sum(
                db,
                "work_orders",
                "estimated_total",
                open_revenue_filters,
                open_revenue_params,
            ),
        }


@app.get("/reports/workshops", response_model=WorkshopReportOut)
def workshop_report(
    workshop_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    with connect(DB_PATH) as db:
        if workshop_id:
            fetch_workshop(db, workshop_id)

        appointment_filters, appointment_params = date_scoped_filters("appointments", date_from, date_to)
        order_filters, order_params = date_scoped_filters("work_orders", date_from, date_to)
        payment_filters, payment_params = date_scoped_filters(
            "appointment_payment_requests",
            date_from,
            date_to,
        )
        paid_filters, paid_params = date_scoped_filters("payments", date_from, date_to)

        if workshop_id:
            appointment_filters.append("workshop_id = ?")
            appointment_params.append(workshop_id)
            order_filters.append("workshop_id = ?")
            order_params.append(workshop_id)
            payment_filters.append(
                "appointment_id IN (SELECT id FROM appointments WHERE workshop_id = ?)"
            )
            payment_params.append(workshop_id)
            paid_filters.append(
                "work_order_id IN (SELECT id FROM work_orders WHERE workshop_id = ?)"
            )
            paid_params.append(workshop_id)

        completed_filters = order_filters + ["status = ?"]
        completed_params = order_params + [WorkOrderStatus.delivered.value]
        cancelled_filters = order_filters + ["status = ?"]
        cancelled_params = order_params + [WorkOrderStatus.cancelled.value]
        active_filters = order_filters + ["status NOT IN (?, ?)"]
        active_params = order_params + [WorkOrderStatus.cancelled.value, WorkOrderStatus.delivered.value]
        pending_deposit_filters = payment_filters + ["status = ?"]
        pending_deposit_params = payment_params + [PaymentStatus.pending.value]
        paid_amount_filters = paid_filters + ["status = ?"]
        paid_amount_params = paid_params + [PaymentStatus.paid.value]

        service_filters: list[str] = []
        service_params: list[str | int | float] = []
        if workshop_id:
            service_filters.append("wo.workshop_id = ?")
            service_params.append(workshop_id)
        if date_from:
            service_filters.append("wo.created_at >= ?")
            service_params.append(date_from)
        if date_to:
            service_filters.append("wo.created_at <= ?")
            service_params.append(date_to)
        service_where = f"WHERE {' AND '.join(service_filters)}" if service_filters else ""
        top_services = db.execute(
            f"""
            SELECT
                wot.service_id,
                wot.name AS service_name,
                sc.service_type,
                COUNT(*) AS times_requested,
                COALESCE(SUM(wot.price), 0) AS revenue
            FROM work_order_tasks wot
            JOIN work_orders wo ON wo.id = wot.work_order_id
            LEFT JOIN service_catalog sc ON sc.id = wot.service_id
            {service_where}
            GROUP BY wot.service_id, wot.name, sc.service_type
            ORDER BY times_requested DESC, revenue DESC
            LIMIT 10
            """,
            service_params,
        ).fetchall()

        return {
            "workshop_id": workshop_id,
            "date_from": date_from,
            "date_to": date_to,
            "total_appointments": scoped_count(
                db,
                "appointments",
                appointment_filters,
                appointment_params,
            ),
            "total_orders": scoped_count(db, "work_orders", order_filters, order_params),
            "completed_orders": scoped_count(
                db,
                "work_orders",
                completed_filters,
                completed_params,
            ),
            "cancelled_orders": scoped_count(
                db,
                "work_orders",
                cancelled_filters,
                cancelled_params,
            ),
            "active_orders": scoped_count(db, "work_orders", active_filters, active_params),
            "estimated_revenue": scoped_sum(
                db,
                "work_orders",
                "estimated_total",
                order_filters,
                order_params,
            ),
            "paid_amount": scoped_sum(db, "payments", "amount", paid_amount_filters, paid_amount_params),
            "pending_deposit_amount": scoped_sum(
                db,
                "appointment_payment_requests",
                "deposit_amount",
                pending_deposit_filters,
                pending_deposit_params,
            ),
            "top_services": [dict(row) for row in top_services],
        }


@app.post("/workshops", response_model=WorkshopOut, status_code=status.HTTP_201_CREATED)
def create_workshop(payload: WorkshopCreate) -> dict:
    workshop = {
        "id": str(uuid4()),
        "name": payload.name.strip(),
        "address": payload.address.strip(),
        "photo_url": payload.photo_url.strip() if payload.photo_url else None,
        "phone": payload.phone.strip() if payload.phone else None,
        "description": payload.description.strip() if payload.description else None,
        "active": payload.active,
        "created_at": utc_now_iso(),
    }
    with connect(DB_PATH) as db:
        db.execute(
            """
            INSERT INTO workshops (
                id, name, address, photo_url, phone, description, active, created_at
            )
            VALUES (
                :id, :name, :address, :photo_url, :phone, :description, :active, :created_at
            )
            """,
            workshop,
        )
    return workshop


@app.get("/workshops", response_model=list[WorkshopOut])
def list_workshops(active: bool | None = True) -> list[dict]:
    with connect(DB_PATH) as db:
        if active is None:
            rows = db.execute("SELECT * FROM workshops ORDER BY name ASC").fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM workshops WHERE active = ? ORDER BY name ASC",
                (1 if active else 0,),
            ).fetchall()
    return [dict(row) for row in rows]


@app.get("/workshops/{workshop_id}", response_model=WorkshopOut)
def get_workshop(workshop_id: str) -> dict:
    with connect(DB_PATH) as db:
        return dict(fetch_workshop(db, workshop_id))


@app.patch("/workshops/{workshop_id}", response_model=WorkshopOut)
def update_workshop(workshop_id: str, payload: WorkshopUpdate) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    normalized = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in changes.items()
    }
    assignments = ", ".join(f"{key} = ?" for key in normalized)
    params = list(normalized.values()) + [workshop_id]

    with connect(DB_PATH) as db:
        fetch_workshop(db, workshop_id)
        db.execute(f"UPDATE workshops SET {assignments} WHERE id = ?", params)
        updated = db.execute("SELECT * FROM workshops WHERE id = ?", (workshop_id,)).fetchone()
    return dict(updated)


@app.post("/services", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
def create_service(payload: ServiceCreate) -> dict:
    service = {
        "id": str(uuid4()),
        "workshop_id": payload.workshop_id,
        "name": payload.name.strip(),
        "service_type": payload.service_type.strip(),
        "description": payload.description.strip() if payload.description else None,
        "priority_rank": payload.priority_rank,
        "price_3_cyl": payload.price_3_cyl,
        "price_4_cyl": payload.price_4_cyl,
        "price_6_cyl": payload.price_6_cyl,
        "price_8_cyl": payload.price_8_cyl,
        "parts_brand": payload.parts_brand.strip() if payload.parts_brand else None,
        "supplies_brand": payload.supplies_brand.strip() if payload.supplies_brand else None,
        "base_price": payload.base_price if payload.base_price is not None else payload.price_4_cyl,
        "estimated_minutes": payload.estimated_minutes,
        "active": payload.active,
        "created_at": utc_now_iso(),
    }
    with connect(DB_PATH) as db:
        fetch_workshop(db, payload.workshop_id)
        db.execute(
            """
            INSERT INTO service_catalog (
                id, workshop_id, name, service_type, description,
                priority_rank, price_3_cyl, price_4_cyl, price_6_cyl, price_8_cyl,
                parts_brand, supplies_brand, base_price, estimated_minutes, active, created_at
            )
            VALUES (
                :id, :workshop_id, :name, :service_type, :description,
                :priority_rank, :price_3_cyl, :price_4_cyl, :price_6_cyl, :price_8_cyl,
                :parts_brand, :supplies_brand, :base_price, :estimated_minutes, :active, :created_at
            )
            """,
            service,
        )
    return service


@app.get("/services", response_model=list[ServiceOut])
def list_services(active: bool | None = True, workshop_id: str | None = None) -> list[dict]:
    filters: list[str] = []
    params: list[str | int] = []
    if active is not None:
        filters.append("active = ?")
        params.append(1 if active else 0)
    if workshop_id:
        filters.append("workshop_id = ?")
        params.append(workshop_id)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    with connect(DB_PATH) as db:
        rows = db.execute(
            f"SELECT * FROM service_catalog {where} ORDER BY priority_rank ASC, name ASC",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/services/{service_id}", response_model=ServiceOut)
def get_service(service_id: str) -> dict:
    with connect(DB_PATH) as db:
        return dict(fetch_service(db, service_id))


@app.patch("/services/{service_id}", response_model=ServiceOut)
def update_service(service_id: str, payload: ServiceUpdate) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    normalized = {}
    for key, value in changes.items():
        if isinstance(value, str):
            value = value.strip()
        normalized[key] = value

    if "workshop_id" in normalized:
        with connect(DB_PATH) as db:
            fetch_workshop(db, normalized["workshop_id"])

    if "base_price" not in normalized:
        if "price_4_cyl" in normalized:
            normalized["base_price"] = normalized["price_4_cyl"]

    assignments = ", ".join(f"{key} = ?" for key in normalized)
    params = list(normalized.values()) + [service_id]

    with connect(DB_PATH) as db:
        fetch_service(db, service_id)
        db.execute(f"UPDATE service_catalog SET {assignments} WHERE id = ?", params)
        updated = db.execute("SELECT * FROM service_catalog WHERE id = ?", (service_id,)).fetchone()
    return dict(updated)


@app.get("/services/{service_id}/price", response_model=ServicePriceOut)
def get_service_price(service_id: str, cylinders: CylinderCount) -> dict:
    with connect(DB_PATH) as db:
        service = fetch_service(db, service_id)
    return {
        "service_id": service["id"],
        "workshop_id": service["workshop_id"],
        "name": service["name"],
        "service_type": service["service_type"],
        "priority_rank": service["priority_rank"],
        "cylinder_count": cylinders.value,
        "unit_price": service_price_for_cylinders(service, cylinders),
        "parts_brand": service["parts_brand"],
        "supplies_brand": service["supplies_brand"],
    }


@app.get("/workshops/{workshop_id}/services", response_model=list[ServiceOut])
def list_workshop_services(workshop_id: str, active: bool | None = True) -> list[dict]:
    with connect(DB_PATH) as db:
        fetch_workshop(db, workshop_id)
    return list_services(active=active, workshop_id=workshop_id)


@app.post("/service-carts", response_model=ServiceCartOut, status_code=status.HTTP_201_CREATED)
def create_service_cart(payload: ServiceCartCreate) -> dict:
    now = utc_now_iso()
    cart_id = str(uuid4())
    cart = {
        "id": cart_id,
        "workshop_id": payload.workshop_id,
        "customer_id": payload.customer_id,
        "vehicle_id": payload.vehicle_id,
        "intake_id": payload.intake_id,
        "status": "open",
        "subtotal": 0.0,
        "created_at": now,
        "updated_at": now,
    }
    with connect(DB_PATH) as db:
        fetch_workshop(db, payload.workshop_id)
        if payload.intake_id:
            intake = intake_with_photos(db, payload.intake_id)
            if (
                intake["workshop_id"] != payload.workshop_id
                or intake["customer_id"] != payload.customer_id
                or intake["vehicle_id"] != payload.vehicle_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Intake does not match cart workshop, customer or vehicle",
                )
        db.execute(
            """
            INSERT INTO service_carts (
                id, workshop_id, customer_id, vehicle_id, intake_id,
                status, subtotal, created_at, updated_at
            )
            VALUES (
                :id, :workshop_id, :customer_id, :vehicle_id, :intake_id,
                :status, :subtotal, :created_at, :updated_at
            )
            """,
            cart,
        )
        return cart_with_items(db, cart_id)


@app.get("/service-carts/{cart_id}", response_model=ServiceCartOut)
def get_service_cart(cart_id: str) -> dict:
    with connect(DB_PATH) as db:
        return cart_with_items(db, cart_id)


@app.get("/service-carts/{cart_id}/summary", response_model=ServiceCartOut)
def get_service_cart_summary(cart_id: str) -> dict:
    with connect(DB_PATH) as db:
        return cart_with_items(db, cart_id)


@app.post("/service-carts/{cart_id}/items", response_model=ServiceCartOut, status_code=status.HTTP_201_CREATED)
def add_service_cart_item(cart_id: str, payload: ServiceCartItemCreate) -> dict:
    with connect(DB_PATH) as db:
        cart = fetch_cart(db, cart_id)
        if cart["status"] != "open":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only open carts can be modified",
            )
        add_cart_item_row(db, cart, payload)
        recalculate_cart(db, cart_id)
        return cart_with_items(db, cart_id)


@app.patch("/service-carts/{cart_id}/items/{item_id}", response_model=ServiceCartOut)
def update_service_cart_item(cart_id: str, item_id: str, payload: ServiceCartItemUpdate) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    with connect(DB_PATH) as db:
        cart = fetch_cart(db, cart_id)
        if cart["status"] != "open":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only open carts can be modified",
            )
        update_cart_item_row(db, cart, item_id, payload)
        recalculate_cart(db, cart_id)
        return cart_with_items(db, cart_id)


@app.delete("/service-carts/{cart_id}/items/{item_id}", response_model=ServiceCartOut)
def delete_service_cart_item(cart_id: str, item_id: str) -> dict:
    with connect(DB_PATH) as db:
        cart = fetch_cart(db, cart_id)
        if cart["status"] != "open":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only open carts can be modified",
            )
        result = db.execute(
            "DELETE FROM service_cart_items WHERE cart_id = ? AND id = ?",
            (cart_id, item_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found")
        recalculate_cart(db, cart_id)
        return cart_with_items(db, cart_id)


@app.post("/service-carts/{cart_id}/checkout", response_model=CartCheckoutOut, status_code=status.HTTP_201_CREATED)
def checkout_service_cart(cart_id: str, payload: ServiceCartCheckoutCreate) -> dict:
    now = utc_now_iso()
    appointment_id = str(uuid4())
    work_order_id = str(uuid4())
    payment_request_id = str(uuid4())
    ticket_id = str(uuid4())
    ticket_number = f"VW-{now[:10].replace('-', '')}-{ticket_id[:8].upper()}"

    with connect(DB_PATH) as db:
        cart = fetch_cart(db, cart_id)
        if cart["status"] != "open":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only open carts can be checked out",
            )
        items = db.execute(
            "SELECT * FROM service_cart_items WHERE cart_id = ? ORDER BY priority_rank ASC, created_at ASC",
            (cart_id,),
        ).fetchall()
        if not items:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cart must include at least one service",
            )

        service_total = float(cart["subtotal"] or 0)
        deposit_percentage = payload.deposit_percentage.value
        deposit_amount = round(service_total * (deposit_percentage / 100), 2)

        appointment = {
            "id": appointment_id,
            "workshop_id": cart["workshop_id"],
            "customer_id": cart["customer_id"],
            "vehicle_id": cart["vehicle_id"],
            "intake_id": cart["intake_id"],
            "requested_at": payload.requested_at,
            "notes": payload.notes.strip() if payload.notes else None,
            "status": AppointmentStatus.requested.value,
            "estimated_total": service_total,
            "created_at": now,
            "updated_at": now,
        }
        db.execute(
            """
            INSERT INTO appointments (
                id, workshop_id, customer_id, vehicle_id, intake_id, requested_at,
                notes, status, estimated_total, created_at, updated_at
            )
            VALUES (
                :id, :workshop_id, :customer_id, :vehicle_id, :intake_id, :requested_at,
                :notes, :status, :estimated_total, :created_at, :updated_at
            )
            """,
            appointment,
        )
        for item in items:
            db.execute(
                """
                INSERT INTO appointment_services (
                    id, appointment_id, service_id, service_name, cylinder_count,
                    quantity, unit_price, estimated_total
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    appointment_id,
                    item["service_id"],
                    item["service_name"],
                    item["cylinder_count"],
                    item["quantity"],
                    item["unit_price"],
                    item["line_total"],
                ),
            )

        highest_priority_rank = min(int(item["priority_rank"] or 2) for item in items)
        work_order = {
            "id": work_order_id,
            "workshop_id": cart["workshop_id"],
            "customer_id": cart["customer_id"],
            "vehicle_id": cart["vehicle_id"],
            "appointment_id": appointment_id,
            "description": f"Servicios solicitados desde carrito {cart_id}",
            "priority": priority_from_rank(highest_priority_rank),
            "status": WorkOrderStatus.received.value,
            "estimated_total": service_total,
            "created_at": now,
            "updated_at": now,
        }
        db.execute(
            """
            INSERT INTO work_orders (
                id, workshop_id, customer_id, vehicle_id, appointment_id,
                description, priority, status, estimated_total, created_at, updated_at
            )
            VALUES (
                :id, :workshop_id, :customer_id, :vehicle_id, :appointment_id,
                :description, :priority, :status, :estimated_total, :created_at, :updated_at
            )
            """,
            work_order,
        )
        for item in items:
            task = {
                "id": str(uuid4()),
                "work_order_id": work_order_id,
                "service_id": item["service_id"],
                "name": item["service_name"],
                "price": item["line_total"],
                "priority": priority_from_rank(int(item["priority_rank"] or 2)),
                "status": TaskStatus.pending.value,
                "created_at": now,
                "updated_at": now,
            }
            db.execute(
                """
                INSERT INTO work_order_tasks (
                    id, work_order_id, service_id, name, price, priority,
                    status, created_at, updated_at
                )
                VALUES (
                    :id, :work_order_id, :service_id, :name, :price, :priority,
                    :status, :created_at, :updated_at
                )
                """,
                task,
            )

        payment_request = {
            "id": payment_request_id,
            "appointment_id": appointment_id,
            "cart_id": cart_id,
            "customer_id": cart["customer_id"],
            "vehicle_id": cart["vehicle_id"],
            "provider": "stripe",
            "service_total": service_total,
            "deposit_percentage": deposit_percentage,
            "deposit_amount": deposit_amount,
            "payment_link": f"https://payments.villavis.local/stripe/checkout/{payment_request_id}",
            "status": PaymentStatus.pending.value,
            "created_at": now,
            "updated_at": now,
        }
        db.execute(
            """
            INSERT INTO appointment_payment_requests (
                id, appointment_id, cart_id, customer_id, vehicle_id, provider,
                service_total, deposit_percentage, deposit_amount, payment_link,
                status, created_at, updated_at
            )
            VALUES (
                :id, :appointment_id, :cart_id, :customer_id, :vehicle_id, :provider,
                :service_total, :deposit_percentage, :deposit_amount, :payment_link,
                :status, :created_at, :updated_at
            )
            """,
            payment_request,
        )

        ticket = {
            "id": ticket_id,
            "ticket_number": ticket_number,
            "appointment_id": appointment_id,
            "payment_request_id": payment_request_id,
            "customer_id": cart["customer_id"],
            "vehicle_id": cart["vehicle_id"],
            "service_total": service_total,
            "deposit_percentage": deposit_percentage,
            "deposit_amount": deposit_amount,
            "status": "issued",
            "created_at": now,
        }
        db.execute(
            """
            INSERT INTO purchase_tickets (
                id, ticket_number, appointment_id, payment_request_id, customer_id,
                vehicle_id, service_total, deposit_percentage, deposit_amount, status, created_at
            )
            VALUES (
                :id, :ticket_number, :appointment_id, :payment_request_id, :customer_id,
                :vehicle_id, :service_total, :deposit_percentage, :deposit_amount, :status, :created_at
            )
            """,
            ticket,
        )

        notification = notification_row(
            cart["customer_id"],
            "Ticket de anticipo generado",
            (
                f"Se genero el ticket {ticket_number} por ${deposit_amount:.2f} "
                f"correspondiente al {deposit_percentage}% de tu servicio."
            ),
            "purchase_ticket",
            "purchase_ticket",
            ticket_id,
        )
        insert_notification(db, notification)
        insert_workshop_notification(
            db,
            workshop_notification_row(
                cart["workshop_id"],
                "Nueva orden de trabajo",
                f"Se creo una nueva orden de trabajo por ${service_total:.2f}.",
                "work_order_created",
                "work_order",
                work_order_id,
            ),
        )
        db.execute(
            "UPDATE service_carts SET status = ?, updated_at = ? WHERE id = ?",
            ("checked_out", now, cart_id),
        )

        return {
            "cart": cart_with_items(db, cart_id),
            "appointment": appointment_with_services(db, appointment_id),
            "work_order": work_order_with_detail(db, work_order_id),
            "payment_request": payment_request,
            "ticket": ticket,
            "notification": notification,
        }


@app.post("/vehicle-intakes", response_model=VehicleIntakeOut, status_code=status.HTTP_201_CREATED)
def create_vehicle_intake(payload: VehicleIntakeCreate) -> dict:
    intake_id = str(uuid4())
    intake = {
        "id": intake_id,
        "workshop_id": payload.workshop_id,
        "customer_id": payload.customer_id,
        "vehicle_id": payload.vehicle_id,
        "has_tapones": payload.has_tapones,
        "has_virlos": payload.has_virlos,
        "has_tapa_gasolina": payload.has_tapa_gasolina,
        "has_rines": payload.has_rines,
        "has_ceniceros": payload.has_ceniceros,
        "has_llanta_refaccion": payload.has_llanta_refaccion,
        "detail_notes": payload.detail_notes.strip() if payload.detail_notes else None,
        "created_at": utc_now_iso(),
    }
    with connect(DB_PATH) as db:
        fetch_workshop(db, payload.workshop_id)
        db.execute(
            """
            INSERT INTO vehicle_intakes (
                id, workshop_id, customer_id, vehicle_id,
                has_tapones, has_virlos, has_tapa_gasolina,
                has_rines, has_ceniceros, has_llanta_refaccion,
                detail_notes, created_at
            )
            VALUES (
                :id, :workshop_id, :customer_id, :vehicle_id,
                :has_tapones, :has_virlos, :has_tapa_gasolina,
                :has_rines, :has_ceniceros, :has_llanta_refaccion,
                :detail_notes, :created_at
            )
            """,
            intake,
        )
        for photo_url in payload.photo_urls:
            db.execute(
                """
                INSERT INTO vehicle_intake_photos (id, intake_id, photo_url, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(uuid4()), intake_id, photo_url.strip(), utc_now_iso()),
            )
        return intake_with_photos(db, intake_id)


@app.get("/vehicle-intakes/{intake_id}", response_model=VehicleIntakeOut)
def get_vehicle_intake(intake_id: str) -> dict:
    with connect(DB_PATH) as db:
        return intake_with_photos(db, intake_id)


@app.get("/vehicles/{vehicle_id}/intakes", response_model=list[VehicleIntakeOut])
def list_vehicle_intakes(vehicle_id: str) -> list[dict]:
    with connect(DB_PATH) as db:
        rows = db.execute(
            "SELECT id FROM vehicle_intakes WHERE vehicle_id = ? ORDER BY created_at DESC",
            (vehicle_id,),
        ).fetchall()
        return [intake_with_photos(db, row["id"]) for row in rows]


@app.get("/vehicles/{vehicle_id}/history")
def get_vehicle_history(vehicle_id: str) -> dict:
    with connect(DB_PATH) as db:
        intakes = db.execute(
            "SELECT id FROM vehicle_intakes WHERE vehicle_id = ? ORDER BY created_at DESC",
            (vehicle_id,),
        ).fetchall()
        appointments = db.execute(
            "SELECT id FROM appointments WHERE vehicle_id = ? ORDER BY requested_at DESC",
            (vehicle_id,),
        ).fetchall()
        orders = db.execute(
            "SELECT id FROM work_orders WHERE vehicle_id = ? ORDER BY created_at DESC",
            (vehicle_id,),
        ).fetchall()
        recommendations = db.execute(
            "SELECT * FROM recommendations WHERE vehicle_id = ? ORDER BY created_at DESC",
            (vehicle_id,),
        ).fetchall()
        payment_requests = db.execute(
            """
            SELECT *
            FROM appointment_payment_requests
            WHERE vehicle_id = ?
            ORDER BY created_at DESC
            """,
            (vehicle_id,),
        ).fetchall()
        tickets = db.execute(
            "SELECT * FROM purchase_tickets WHERE vehicle_id = ? ORDER BY created_at DESC",
            (vehicle_id,),
        ).fetchall()

        return {
            "vehicle_id": vehicle_id,
            "intakes": [intake_with_photos(db, row["id"]) for row in intakes],
            "appointments": [appointment_with_services(db, row["id"]) for row in appointments],
            "work_orders": [work_order_with_detail(db, row["id"]) for row in orders],
            "recommendations": [dict(row) for row in recommendations],
            "payment_requests": [dict(row) for row in payment_requests],
            "tickets": [dict(row) for row in tickets],
        }


@app.post("/appointments", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def create_appointment(payload: AppointmentCreate) -> dict:
    now = utc_now_iso()
    appointment_id = str(uuid4())
    appointment = {
        "id": appointment_id,
        "workshop_id": payload.workshop_id,
        "customer_id": payload.customer_id,
        "vehicle_id": payload.vehicle_id,
        "intake_id": payload.intake_id,
        "requested_at": payload.requested_at,
        "notes": payload.notes.strip() if payload.notes else None,
        "status": AppointmentStatus.requested.value,
        "estimated_total": 0.0,
        "created_at": now,
        "updated_at": now,
    }
    with connect(DB_PATH) as db:
        fetch_workshop(db, payload.workshop_id)
        if payload.intake_id:
            intake = intake_with_photos(db, payload.intake_id)
            if (
                intake["workshop_id"] != payload.workshop_id
                or intake["customer_id"] != payload.customer_id
                or intake["vehicle_id"] != payload.vehicle_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Intake does not match appointment workshop, customer or vehicle",
                )
        requested_services = []
        estimated_total = 0.0
        for requested in payload.services:
            service = fetch_service(db, requested.service_id)
            if service["workshop_id"] != payload.workshop_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Service does not belong to selected workshop",
                )
            unit_price = service_price_for_cylinders(service, requested.cylinder_count)
            line_total = unit_price * requested.quantity
            estimated_total += line_total
            requested_services.append(
                {
                    "id": str(uuid4()),
                    "appointment_id": appointment_id,
                    "service_id": requested.service_id,
                    "service_name": service["name"],
                    "cylinder_count": requested.cylinder_count.value,
                    "quantity": requested.quantity,
                    "unit_price": unit_price,
                    "estimated_total": line_total,
                }
            )

        appointment["estimated_total"] = estimated_total
        db.execute(
            """
            INSERT INTO appointments (
                id, workshop_id, customer_id, vehicle_id, intake_id, requested_at,
                notes, status, estimated_total, created_at, updated_at
            )
            VALUES (
                :id, :workshop_id, :customer_id, :vehicle_id, :intake_id, :requested_at,
                :notes, :status, :estimated_total, :created_at, :updated_at
            )
            """,
            appointment,
        )
        for requested in requested_services:
            db.execute(
                """
                INSERT INTO appointment_services (
                    id, appointment_id, service_id, service_name, cylinder_count,
                    quantity, unit_price, estimated_total
                )
                VALUES (
                    :id, :appointment_id, :service_id, :service_name, :cylinder_count,
                    :quantity, :unit_price, :estimated_total
                )
                """,
                requested,
            )
        return appointment_with_services(db, appointment_id)


@app.get("/appointments", response_model=list[AppointmentOut])
def list_appointments(
    customer_id: str | None = None,
    vehicle_id: str | None = None,
    workshop_id: str | None = None,
) -> list[dict]:
    filters: list[str] = []
    params: list[str] = []
    if workshop_id:
        filters.append("workshop_id = ?")
        params.append(workshop_id)
    if customer_id:
        filters.append("customer_id = ?")
        params.append(customer_id)
    if vehicle_id:
        filters.append("vehicle_id = ?")
        params.append(vehicle_id)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    with connect(DB_PATH) as db:
        rows = db.execute(
            f"SELECT * FROM appointments {where} ORDER BY requested_at ASC",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/appointments/{appointment_id}", response_model=AppointmentDetail)
def get_appointment(appointment_id: str) -> dict:
    with connect(DB_PATH) as db:
        return appointment_with_services(db, appointment_id)


@app.patch("/appointments/{appointment_id}/status", response_model=AppointmentOut)
def update_appointment_status(appointment_id: str, payload: AppointmentStatusUpdate) -> dict:
    with connect(DB_PATH) as db:
        current = db.execute("SELECT id FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        if not current:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
        db.execute(
            "UPDATE appointments SET status = ?, updated_at = ? WHERE id = ?",
            (payload.status.value, utc_now_iso(), appointment_id),
        )
        updated = db.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    return dict(updated)


@app.post("/work-orders", response_model=WorkOrderOut, status_code=status.HTTP_201_CREATED)
def create_work_order(payload: WorkOrderCreate) -> dict:
    now = utc_now_iso()
    work_order = {
        "id": str(uuid4()),
        "workshop_id": payload.workshop_id,
        "customer_id": payload.customer_id,
        "vehicle_id": payload.vehicle_id,
        "appointment_id": payload.appointment_id,
        "description": payload.description.strip(),
        "priority": payload.priority.value,
        "status": WorkOrderStatus.received.value,
        "estimated_total": 0.0,
        "created_at": now,
        "updated_at": now,
    }

    with connect(DB_PATH) as db:
        fetch_workshop(db, payload.workshop_id)
        db.execute(
            """
            INSERT INTO work_orders (
                id, workshop_id, customer_id, vehicle_id, appointment_id,
                description, priority, status, estimated_total, created_at, updated_at
            )
            VALUES (
                :id, :workshop_id, :customer_id, :vehicle_id, :appointment_id,
                :description, :priority, :status, :estimated_total, :created_at, :updated_at
            )
            """,
            work_order,
        )
        insert_workshop_notification(
            db,
            workshop_notification_row(
                payload.workshop_id,
                "Nueva orden de trabajo",
                f"Se creo una nueva orden de trabajo para el vehiculo {payload.vehicle_id}.",
                "work_order_created",
                "work_order",
                work_order["id"],
            ),
        )

    return work_order


@app.get("/work-orders", response_model=list[WorkOrderOut])
def list_work_orders(
    status_filter: WorkOrderStatus | None = Query(default=None, alias="status"),
    customer_id: str | None = None,
    vehicle_id: str | None = None,
    workshop_id: str | None = None,
) -> list[dict]:
    filters: list[str] = []
    params: list[str] = []

    if status_filter:
        filters.append("status = ?")
        params.append(status_filter.value)
    if workshop_id:
        filters.append("workshop_id = ?")
        params.append(workshop_id)
    if customer_id:
        filters.append("customer_id = ?")
        params.append(customer_id)
    if vehicle_id:
        filters.append("vehicle_id = ?")
        params.append(vehicle_id)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    with connect(DB_PATH) as db:
        rows = db.execute(
            f"SELECT * FROM work_orders {where} ORDER BY created_at DESC",
            params,
        ).fetchall()

    return [dict(row) for row in rows]


@app.get("/work-orders/{order_id}", response_model=WorkOrderDetail)
def get_work_order(order_id: str) -> dict:
    with connect(DB_PATH) as db:
        return work_order_with_detail(db, order_id)


@app.patch("/work-orders/{order_id}/status", response_model=WorkOrderOut)
def update_work_order_status(order_id: str, payload: WorkOrderStatusUpdate) -> dict:
    now = utc_now_iso()
    with connect(DB_PATH) as db:
        current = fetch_work_order(db, order_id)
        db.execute(
            "UPDATE work_orders SET status = ?, updated_at = ? WHERE id = ?",
            (payload.status.value, now, order_id),
        )
        insert_notification(
            db,
            notification_row(
                current["customer_id"],
                "Estado de orden actualizado",
                f"Tu orden de trabajo cambio a estado {payload.status.value}.",
                "work_order_status",
                "work_order",
                order_id,
            ),
        )
        updated = db.execute("SELECT * FROM work_orders WHERE id = ?", (order_id,)).fetchone()

    return dict(updated)


@app.post("/work-orders/{order_id}/accept", response_model=WorkOrderDetail)
def accept_work_order(order_id: str) -> dict:
    now = utc_now_iso()
    with connect(DB_PATH) as db:
        current = fetch_work_order(db, order_id)
        if current["status"] == WorkOrderStatus.cancelled.value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cancelled work orders cannot be accepted",
            )
        db.execute(
            "UPDATE work_orders SET status = ?, updated_at = ? WHERE id = ?",
            (WorkOrderStatus.approved.value, now, order_id),
        )
        if current["appointment_id"]:
            db.execute(
                "UPDATE appointments SET status = ?, updated_at = ? WHERE id = ?",
                (AppointmentStatus.confirmed.value, now, current["appointment_id"]),
            )
        insert_notification(
            db,
            notification_row(
                current["customer_id"],
                "Orden de trabajo aceptada",
                "El taller acepto tu orden de trabajo y comenzara el proceso de servicio.",
                "work_order_accepted",
                "work_order",
                order_id,
            ),
        )
        return work_order_with_detail(db, order_id)


@app.post("/work-orders/{order_id}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def add_task(order_id: str, payload: TaskCreate) -> dict:
    now = utc_now_iso()
    task = {
        "id": str(uuid4()),
        "work_order_id": order_id,
        "service_id": payload.service_id,
        "name": payload.name.strip(),
        "price": payload.price,
        "priority": payload.priority.value,
        "status": TaskStatus.pending.value,
        "created_at": now,
        "updated_at": now,
    }

    with connect(DB_PATH) as db:
        fetch_work_order(db, order_id)
        db.execute(
            """
            INSERT INTO work_order_tasks (
                id, work_order_id, service_id, name, price, priority, status, created_at, updated_at
            )
            VALUES (
                :id, :work_order_id, :service_id, :name, :price, :priority, :status, :created_at, :updated_at
            )
            """,
            task,
        )
        total = db.execute(
            "SELECT COALESCE(SUM(price), 0) AS total FROM work_order_tasks WHERE work_order_id = ?",
            (order_id,),
        ).fetchone()["total"]
        db.execute(
            "UPDATE work_orders SET estimated_total = ?, updated_at = ? WHERE id = ?",
            (total, now, order_id),
        )

    return task


@app.patch("/work-orders/{order_id}/tasks/{task_id}/status", response_model=WorkOrderDetail)
def update_task_status(order_id: str, task_id: str, payload: TaskStatusUpdate) -> dict:
    now = utc_now_iso()
    with connect(DB_PATH) as db:
        work_order = fetch_work_order(db, order_id)
        task = db.execute(
            "SELECT * FROM work_order_tasks WHERE id = ? AND work_order_id = ?",
            (task_id, order_id),
        ).fetchone()
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

        db.execute(
            "UPDATE work_order_tasks SET status = ?, updated_at = ? WHERE id = ?",
            (payload.status.value, now, task_id),
        )

        statuses = db.execute(
            "SELECT status FROM work_order_tasks WHERE work_order_id = ?",
            (order_id,),
        ).fetchall()
        next_order_status = work_order["status"]
        if statuses and all(row["status"] == TaskStatus.done.value for row in statuses):
            next_order_status = WorkOrderStatus.ready.value
        elif any(row["status"] in {TaskStatus.in_progress.value, TaskStatus.done.value} for row in statuses):
            next_order_status = WorkOrderStatus.in_progress.value

        if next_order_status != work_order["status"]:
            db.execute(
                "UPDATE work_orders SET status = ?, updated_at = ? WHERE id = ?",
                (next_order_status, now, order_id),
            )
        else:
            db.execute("UPDATE work_orders SET updated_at = ? WHERE id = ?", (now, order_id))

        insert_notification(
            db,
            notification_row(
                work_order["customer_id"],
                "Avance de servicio",
                f"El servicio '{task['name']}' cambio a estado {payload.status.value}.",
                "service_progress",
                "work_order",
                order_id,
            ),
        )
        return work_order_with_detail(db, order_id)


@app.post("/quotes", response_model=QuoteOut, status_code=status.HTTP_201_CREATED)
def create_quote(payload: QuoteCreate) -> dict:
    now = utc_now_iso()
    quote_id = str(uuid4())
    quote = {
        "id": quote_id,
        "work_order_id": payload.work_order_id,
        "status": QuoteStatus.draft.value,
        "subtotal": 0.0,
        "notes": payload.notes.strip() if payload.notes else None,
        "created_at": now,
        "updated_at": now,
    }

    with connect(DB_PATH) as db:
        fetch_work_order(db, payload.work_order_id)
        db.execute(
            """
            INSERT INTO quotes (id, work_order_id, status, subtotal, notes, created_at, updated_at)
            VALUES (:id, :work_order_id, :status, :subtotal, :notes, :created_at, :updated_at)
            """,
            quote,
        )
        for item in payload.items:
            add_quote_item_row(db, quote_id, item)
        recalculate_quote(db, quote_id)
        return quote_with_items(db, quote_id)


@app.get("/quotes/{quote_id}", response_model=QuoteOut)
def get_quote(quote_id: str) -> dict:
    with connect(DB_PATH) as db:
        return quote_with_items(db, quote_id)


@app.post("/quotes/{quote_id}/items", response_model=QuoteOut, status_code=status.HTTP_201_CREATED)
def add_quote_item(quote_id: str, payload: QuoteItemCreate) -> dict:
    with connect(DB_PATH) as db:
        ensure_quote_editable(quote_with_items(db, quote_id))
        add_quote_item_row(db, quote_id, payload)
        recalculate_quote(db, quote_id)
        return quote_with_items(db, quote_id)


@app.patch("/quotes/{quote_id}/items/{item_id}", response_model=QuoteOut)
def update_quote_item(quote_id: str, item_id: str, payload: QuoteItemUpdate) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    with connect(DB_PATH) as db:
        ensure_quote_editable(quote_with_items(db, quote_id))
        item = db.execute("SELECT * FROM quote_items WHERE id = ? AND quote_id = ?", (item_id, quote_id)).fetchone()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote item not found")
        updated = {**dict(item), **changes}
        updated["total"] = updated["quantity"] * updated["unit_price"]
        db.execute(
            """UPDATE quote_items SET description = :description, quantity = :quantity,
               unit_price = :unit_price, total = :total WHERE id = :id AND quote_id = :quote_id""",
            updated,
        )
        recalculate_quote(db, quote_id)
        return quote_with_items(db, quote_id)


@app.delete("/quotes/{quote_id}/items/{item_id}", response_model=QuoteOut)
def delete_quote_item(quote_id: str, item_id: str) -> dict:
    with connect(DB_PATH) as db:
        ensure_quote_editable(quote_with_items(db, quote_id))
        deleted = db.execute("DELETE FROM quote_items WHERE id = ? AND quote_id = ?", (item_id, quote_id))
        if deleted.rowcount == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote item not found")
        recalculate_quote(db, quote_id)
        return quote_with_items(db, quote_id)


@app.patch("/quotes/{quote_id}/status", response_model=QuoteOut)
def update_quote_status(quote_id: str, payload: QuoteStatusUpdate) -> dict:
    now = utc_now_iso()
    with connect(DB_PATH) as db:
        quote = quote_with_items(db, quote_id)
        if quote["status"] == payload.status.value:
            return quote
        ensure_quote_editable(quote)
        db.execute(
            "UPDATE quotes SET status = ?, updated_at = ? WHERE id = ?",
            (payload.status.value, now, quote_id),
        )
        if payload.status == QuoteStatus.accepted:
            db.execute(
                "UPDATE work_orders SET status = ?, estimated_total = ?, updated_at = ? WHERE id = ?",
                (WorkOrderStatus.approved.value, quote["subtotal"], now, quote["work_order_id"]),
            )
        return quote_with_items(db, quote_id)


@app.post("/work-orders/{order_id}/evidence", response_model=EvidenceOut, status_code=status.HTTP_201_CREATED)
def add_evidence(order_id: str, payload: EvidenceCreate) -> dict:
    evidence = {
        "id": str(uuid4()),
        "work_order_id": order_id,
        "file_url": payload.file_url,
        "caption": payload.caption.strip() if payload.caption else None,
        "created_at": utc_now_iso(),
    }
    with connect(DB_PATH) as db:
        fetch_work_order(db, order_id)
        db.execute(
            """
            INSERT INTO evidence (id, work_order_id, file_url, caption, created_at)
            VALUES (:id, :work_order_id, :file_url, :caption, :created_at)
            """,
            evidence,
        )
    return evidence


@app.get("/work-orders/{order_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(order_id: str) -> list[dict]:
    with connect(DB_PATH) as db:
        fetch_work_order(db, order_id)
        rows = db.execute(
            "SELECT * FROM evidence WHERE work_order_id = ? ORDER BY created_at DESC",
            (order_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/recommendations", response_model=RecommendationOut, status_code=status.HTTP_201_CREATED)
def create_recommendation(payload: RecommendationCreate) -> dict:
    recommendation = {
        "id": str(uuid4()),
        "vehicle_id": payload.vehicle_id,
        "title": payload.title.strip(),
        "notes": payload.notes.strip() if payload.notes else None,
        "priority": payload.priority.value,
        "due_date": payload.due_date,
        "status": "open",
        "created_at": utc_now_iso(),
    }
    with connect(DB_PATH) as db:
        db.execute(
            """
            INSERT INTO recommendations (
                id, vehicle_id, title, notes, priority, due_date, status, created_at
            )
            VALUES (
                :id, :vehicle_id, :title, :notes, :priority, :due_date, :status, :created_at
            )
            """,
            recommendation,
        )
    return recommendation


@app.get("/vehicles/{vehicle_id}/recommendations", response_model=list[RecommendationOut])
def list_vehicle_recommendations(vehicle_id: str) -> list[dict]:
    with connect(DB_PATH) as db:
        rows = db.execute(
            "SELECT * FROM recommendations WHERE vehicle_id = ? ORDER BY created_at DESC",
            (vehicle_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/customers/{customer_id}/notifications", response_model=list[AppNotificationOut])
def list_customer_notifications(customer_id: str, unread_only: bool = False) -> list[dict]:
    filters = ["customer_id = ?"]
    params: list[str] = [customer_id]
    if unread_only:
        filters.append("read_at IS NULL")
    where = " AND ".join(filters)
    with connect(DB_PATH) as db:
        rows = db.execute(
            f"SELECT * FROM app_notifications WHERE {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/customers/{customer_id}/notifications/unread-count", response_model=NotificationCountOut)
def customer_notification_unread_count(customer_id: str) -> dict:
    with connect(DB_PATH) as db:
        unread_count = db.execute(
            """
            SELECT COUNT(*) AS unread_count
            FROM app_notifications
            WHERE customer_id = ? AND read_at IS NULL
            """,
            (customer_id,),
        ).fetchone()["unread_count"]
    return {"unread_count": unread_count}


@app.patch("/customers/{customer_id}/notifications/read-all", response_model=NotificationBulkUpdateOut)
def mark_customer_notifications_read(customer_id: str) -> dict:
    now = utc_now_iso()
    with connect(DB_PATH) as db:
        result = db.execute(
            "UPDATE app_notifications SET read_at = ? WHERE customer_id = ? AND read_at IS NULL",
            (now, customer_id),
        )
        unread_count = db.execute(
            """
            SELECT COUNT(*) AS unread_count
            FROM app_notifications
            WHERE customer_id = ? AND read_at IS NULL
            """,
            (customer_id,),
        ).fetchone()["unread_count"]
    return {"updated_count": result.rowcount, "unread_count": unread_count}


@app.get("/notifications/{notification_id}", response_model=AppNotificationOut)
def get_notification(notification_id: str) -> dict:
    with connect(DB_PATH) as db:
        notification = db.execute(
            "SELECT * FROM app_notifications WHERE id = ?",
            (notification_id,),
        ).fetchone()
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return dict(notification)


@app.get("/workshops/{workshop_id}/notifications", response_model=list[WorkshopNotificationOut])
def list_workshop_notifications(workshop_id: str, unread_only: bool = False) -> list[dict]:
    filters = ["workshop_id = ?"]
    params: list[str] = [workshop_id]
    if unread_only:
        filters.append("read_at IS NULL")
    where = " AND ".join(filters)
    with connect(DB_PATH) as db:
        fetch_workshop(db, workshop_id)
        rows = db.execute(
            f"SELECT * FROM workshop_notifications WHERE {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/workshops/{workshop_id}/notifications/unread-count", response_model=NotificationCountOut)
def workshop_notification_unread_count(workshop_id: str) -> dict:
    with connect(DB_PATH) as db:
        fetch_workshop(db, workshop_id)
        unread_count = db.execute(
            """
            SELECT COUNT(*) AS unread_count
            FROM workshop_notifications
            WHERE workshop_id = ? AND read_at IS NULL
            """,
            (workshop_id,),
        ).fetchone()["unread_count"]
    return {"unread_count": unread_count}


@app.patch("/workshops/{workshop_id}/notifications/read-all", response_model=NotificationBulkUpdateOut)
def mark_workshop_notifications_read(workshop_id: str) -> dict:
    now = utc_now_iso()
    with connect(DB_PATH) as db:
        fetch_workshop(db, workshop_id)
        result = db.execute(
            "UPDATE workshop_notifications SET read_at = ? WHERE workshop_id = ? AND read_at IS NULL",
            (now, workshop_id),
        )
        unread_count = db.execute(
            """
            SELECT COUNT(*) AS unread_count
            FROM workshop_notifications
            WHERE workshop_id = ? AND read_at IS NULL
            """,
            (workshop_id,),
        ).fetchone()["unread_count"]
    return {"updated_count": result.rowcount, "unread_count": unread_count}


@app.get("/workshop-notifications/{notification_id}", response_model=WorkshopNotificationOut)
def get_workshop_notification(notification_id: str) -> dict:
    with connect(DB_PATH) as db:
        notification = db.execute(
            "SELECT * FROM workshop_notifications WHERE id = ?",
            (notification_id,),
        ).fetchone()
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workshop notification not found")
    return dict(notification)


@app.patch("/workshop-notifications/{notification_id}/read", response_model=WorkshopNotificationOut)
def mark_workshop_notification_read(notification_id: str) -> dict:
    with connect(DB_PATH) as db:
        notification = db.execute(
            "SELECT * FROM workshop_notifications WHERE id = ?",
            (notification_id,),
        ).fetchone()
        if not notification:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workshop notification not found")
        db.execute(
            "UPDATE workshop_notifications SET read_at = COALESCE(read_at, ?) WHERE id = ?",
            (utc_now_iso(), notification_id),
        )
        updated = db.execute(
            "SELECT * FROM workshop_notifications WHERE id = ?",
            (notification_id,),
        ).fetchone()
    return dict(updated)


@app.patch("/notifications/{notification_id}/read", response_model=AppNotificationOut)
def mark_notification_read(notification_id: str) -> dict:
    with connect(DB_PATH) as db:
        notification = db.execute(
            "SELECT * FROM app_notifications WHERE id = ?",
            (notification_id,),
        ).fetchone()
        if not notification:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
        db.execute(
            "UPDATE app_notifications SET read_at = COALESCE(read_at, ?) WHERE id = ?",
            (utc_now_iso(), notification_id),
        )
        updated = db.execute(
            "SELECT * FROM app_notifications WHERE id = ?",
            (notification_id,),
        ).fetchone()
    return dict(updated)


@app.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def register_payment(payload: PaymentCreate) -> dict:
    payment = {
        "id": str(uuid4()),
        "work_order_id": payload.work_order_id,
        "amount": payload.amount,
        "provider": payload.provider.strip(),
        "reference": payload.reference.strip() if payload.reference else None,
        "status": payload.status.value,
        "created_at": utc_now_iso(),
    }
    with connect(DB_PATH) as db:
        fetch_work_order(db, payload.work_order_id)
        db.execute(
            """
            INSERT INTO payments (id, work_order_id, amount, provider, reference, status, created_at)
            VALUES (:id, :work_order_id, :amount, :provider, :reference, :status, :created_at)
            """,
            payment,
        )
    return payment


app.include_router(create_router(lambda: DB_PATH))

from services.workshop_service.web_sync import create_router as create_sync_router
app.include_router(create_sync_router(lambda: DB_PATH))
