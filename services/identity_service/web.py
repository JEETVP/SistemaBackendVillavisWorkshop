"""Identity operations used by the gateway's browser compatibility API."""
from datetime import datetime, timezone
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Response

from services.common.config import app_origin
from services.common.database import Connection, IntegrityError, table_columns, write_lock, connect
from services.common.internal import require_service_token
from services.common.time import utc_now_iso
from services.common.web_schemas import (
    AccountLookup, AccountProvision, ActivationComplete, ActivationToken, InternalCustomerRegistration, InternalRenew, WebLogin,
)
from services.identity_service.security import hash_password, verify_password


def init_web_identity(db):
    from services.identity_service.web_sync import init_schema
    init_schema(db)
    columns = table_columns(db, "users")
    for name, sql_type in {"state": "TEXT NOT NULL DEFAULT 'active'", "workshop_id": "TEXT",
                           "registration_workshop_id": "TEXT"}.items():
        if name not in columns:
            db.execute(f"ALTER TABLE users ADD COLUMN {name} {sql_type}")
    db.execute("""CREATE TABLE IF NOT EXISTS activations (
        token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        expires_at DOUBLE PRECISION NOT NULL)""")


def safe_user(row):
    return {key: value for key, value in dict(row).items() if key != "password_hash"}


def issue_activation(db, user_id):
    token = secrets.token_urlsafe(32)
    expires = time.time() + int(os.getenv("ACTIVATION_TTL_SECONDS", "86400"))
    db.execute("DELETE FROM activations WHERE user_id = %s", (user_id,))
    db.execute("INSERT INTO activations VALUES (%s, %s, %s)", (hashlib.sha256(token.encode()).hexdigest(), user_id, expires))
    return {"activationUrl": f"{app_origin()}/registro/activar?{urlencode({'token': token})}",
            "expiresAt": datetime.fromtimestamp(expires, timezone.utc).isoformat()}


def valid_activation(db, token):
    row = db.execute("""SELECT a.* FROM activations a JOIN users u ON u.id = a.user_id
        WHERE a.token_hash = %s AND a.expires_at > %s AND u.state = 'pending_activation'""",
        (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    if not row:
        raise HTTPException(400, "El enlace no es válido, venció o ya fue utilizado.")
    return row


def create_router(db_path, create_session):
    router = APIRouter(prefix="/internal/web", dependencies=[Depends(require_service_token)])

    @router.post("/accounts", status_code=201)
    def provision(payload: AccountProvision):
        if payload.role == "staff" and (not payload.email or not payload.password):
            raise HTTPException(422, "Workshop account requires email and password")
        if payload.role == "client" and (not payload.phone or not payload.vehicle_id):
            raise HTTPException(422, "Client account requires phone and vehicle")
        user = {"id": payload.id, "name": payload.name, "phone": payload.phone,
                "email": payload.email.lower() if payload.email else None,
                "password_hash": hash_password(payload.password) if payload.password else None,
                "role": payload.role, "customer_id": payload.id if payload.role == "client" else None,
                "primary_vehicle_id": payload.vehicle_id, "created_at": utc_now_iso(), "state": "provisioning",
                "workshop_id": payload.workshop_id if payload.role == "staff" else None,
                "registration_workshop_id": payload.workshop_id}
        with connect(db_path()) as db:
            try:
                db.execute("""INSERT INTO users (id, name, phone, email, password_hash, role, customer_id,
                    primary_vehicle_id, created_at, state, workshop_id, registration_workshop_id)
                    VALUES (%(id)s, %(name)s, %(phone)s, %(email)s, %(password_hash)s, %(role)s, %(customer_id)s,
                    %(primary_vehicle_id)s, %(created_at)s, %(state)s, %(workshop_id)s, %(registration_workshop_id)s)""", user)
            except IntegrityError as error:
                raise HTTPException(409, "Ya existe una cuenta con este correo o teléfono.") from error
        return safe_user(user)

    @router.post("/accounts/self-register", status_code=201)
    def self_register(payload: InternalCustomerRegistration):
        user = {"id": payload.id, "name": payload.nombre, "phone": payload.telefono,
            "email": payload.email, "password_hash": hash_password(payload.password), "role": "client",
            "customer_id": payload.id, "primary_vehicle_id": None, "created_at": utc_now_iso(),
            "state": "provisioning", "workshop_id": None, "registration_workshop_id": None}
        with connect(db_path()) as db:
            try:
                db.execute("""INSERT INTO users (id, name, phone, email, password_hash, role, customer_id,
                    primary_vehicle_id, created_at, state, workshop_id, registration_workshop_id)
                    VALUES (%(id)s, %(name)s, %(phone)s, %(email)s, %(password_hash)s, %(role)s, %(customer_id)s,
                    %(primary_vehicle_id)s, %(created_at)s, %(state)s, %(workshop_id)s, %(registration_workshop_id)s)""", user)
            except IntegrityError as error:
                raise HTTPException(409, "Ya existe una cuenta con este correo o teléfono.") from error
        return safe_user(user)

    @router.post("/accounts/{user_id}/commit")
    def commit(user_id: str):
        with connect(db_path()) as db:
            write_lock(db)
            row = db.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
            if not row or row["state"] != "provisioning":
                raise HTTPException(409, "Account is not being provisioned")
            next_state = "active" if row["role"] == "staff" or (row["password_hash"] and not row["registration_workshop_id"]) else "pending_activation"
            db.execute("UPDATE users SET state = %s WHERE id = %s", (next_state, user_id))
            user = safe_user(db.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone())
            if next_state == "active":
                return {"user": user, "access_token": create_session(db, user_id)}
            return {"user": user, **issue_activation(db, user_id)}

    @router.delete("/accounts/{user_id}", status_code=204)
    def abort(user_id: str):
        with connect(db_path()) as db:
            write_lock(db)
            row = db.execute("SELECT state FROM users WHERE id = %s", (user_id,)).fetchone()
            if row and row["state"] != "provisioning":
                raise HTTPException(409, "A committed account cannot be aborted")
            db.execute("DELETE FROM users WHERE id = %s AND state = 'provisioning'", (user_id,))
        return Response(status_code=204)

    @router.post("/accounts/lookup")
    def lookup(payload: AccountLookup):
        if not payload.customer_ids:
            return []
        placeholders = ",".join("%s" for _ in payload.customer_ids)
        with connect(db_path()) as db:
            rows = db.execute(f"SELECT * FROM users WHERE customer_id IN ({placeholders}) AND state != 'provisioning'",
                              payload.customer_ids).fetchall()
        return [safe_user(row) for row in rows]

    @router.post("/login")
    def login(payload: WebLogin):
        with connect(db_path()) as db:
            if payload.type == "cliente":
                row = db.execute("SELECT * FROM users WHERE phone = %s AND role = 'client'", (payload.telefono,)).fetchone()
            else:
                row = db.execute("SELECT * FROM users WHERE email = %s AND role IN ('staff', 'admin') AND workshop_id IS NOT NULL",
                                 (payload.email,)).fetchone()
            # Always derive a verifier, including missing or inactive accounts.
            candidate = row["password_hash"] if row and row["password_hash"] else hash_password("unregistered-account")
            valid = verify_password(payload.password, candidate)
            if not row or not valid or row["state"] != "active":
                raise HTTPException(401, "Teléfono o contraseña incorrectos. Si recibiste un enlace de activación, complétalo antes de entrar.")
            return {"user": safe_user(row), "access_token": create_session(db, row["id"])}

    @router.post("/activation/renew")
    def renew(payload: InternalRenew):
        with connect(db_path()) as db:
            write_lock(db)
            row = db.execute("SELECT * FROM users WHERE id = %s", (payload.user_id,)).fetchone()
            if not row or row["registration_workshop_id"] != payload.workshop_id:
                raise HTTPException(403, "No tienes acceso a este cliente.")
            if row["state"] != "pending_activation":
                raise HTTPException(409, "La cuenta ya está activada o no está disponible.")
            return issue_activation(db, payload.user_id)

    @router.post("/activation/validate")
    def validate(payload: ActivationToken):
        with connect(db_path()) as db:
            row = valid_activation(db, payload.token)
            return {"expiresAt": datetime.fromtimestamp(row["expires_at"], timezone.utc).isoformat()}

    @router.post("/activation/complete")
    def activate(payload: ActivationComplete):
        with connect(db_path()) as db:
            valid_activation(db, payload.token)
        password_hash = hash_password(payload.password)
        with connect(db_path()) as db:
            write_lock(db)
            row = valid_activation(db, payload.token)
            db.execute("UPDATE users SET state = 'active', password_hash = %s WHERE id = %s", (password_hash, row["user_id"]))
            db.execute("DELETE FROM activations WHERE user_id = %s", (row["user_id"],))
        return {"success": True}

    return router
