from __future__ import annotations

import os
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response, status

from services.common.database import Connection, IntegrityError, table_columns, write_lock, connect, database_url_from_env
from services.common.time import utc_now_iso
from services.identity_service.web import create_router, init_web_identity
from services.identity_service.schemas import (
    ClientUserRegister,
    StaffLogin,
    StaffUserRegister,
    TokenOut,
    TokenValidate,
    UserOut,
)
from services.identity_service.security import (
    create_token,
    ensure_private_key,
    get_public_key_pem,
    hash_password,
    normalize_phone,
    verify_password,
    verify_token,
)

DATABASE_URL = database_url_from_env("IDENTITY_DATABASE_URL")

app = FastAPI(
    title="Villavis Identity Service",
    description="Microservicio de usuarios, sesiones y roles.",
    version="1.0.0",
)


def public_user(data: dict | dict) -> dict:
    user = dict(data)
    user.pop("password_hash", None)
    return user


def create_session(db: Connection, user_id: str) -> str:
    user = db.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    token = create_token(dict(user))
    db.execute(
        "INSERT INTO sessions (token, user_id, created_at) VALUES (%s, %s, %s)",
        (token, user_id, utc_now_iso()),
    )
    return token


def init_db(db_path: str | None = None) -> None:
    with connect(db_path or DATABASE_URL) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT UNIQUE,
                password_hash TEXT,
                role TEXT NOT NULL,
                customer_id TEXT,
                primary_vehicle_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        existing_columns = table_columns(db, "users")
        if "phone" not in existing_columns:
            db.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone) WHERE phone IS NOT NULL")
        init_web_identity(db)
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

        bootstrap_admin_phone = os.getenv("IDENTITY_BOOTSTRAP_ADMIN_PHONE", "").strip()
        bootstrap_admin_phone = normalize_phone(bootstrap_admin_phone) if bootstrap_admin_phone else ""
        bootstrap_admin_password = os.getenv("IDENTITY_BOOTSTRAP_ADMIN_PASSWORD")
        if bootstrap_admin_phone and bootstrap_admin_password:
            existing = db.execute("SELECT id FROM users WHERE phone = %s", (bootstrap_admin_phone,)).fetchone()
            if not existing:
                legacy_email = os.getenv("IDENTITY_BOOTSTRAP_ADMIN_EMAIL", "").lower()
                if legacy_email:
                    existing = db.execute("SELECT id FROM users WHERE email = %s", (legacy_email,)).fetchone()
                    if existing:
                        db.execute(
                            "UPDATE users SET phone = %s, password_hash = %s WHERE id = %s",
                            (bootstrap_admin_phone, hash_password(bootstrap_admin_password), existing["id"]),
                        )
            if not existing:
                db.execute(
                    """
                    INSERT INTO users (
                        id, name, phone, email, password_hash, role,
                        customer_id, primary_vehicle_id, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid4()),
                        "Admin Villavis",
                        bootstrap_admin_phone,
                        None,
                        hash_password(bootstrap_admin_password),
                        "admin",
                        None,
                        None,
                        utc_now_iso(),
                    ),
                )


@app.on_event("startup")
def on_startup() -> None:
    ensure_private_key()
    init_db()


@app.get("/health")
def health() -> dict:
    try:
        with connect(DATABASE_URL) as db:
            db.execute("SELECT 1")
    except Exception:
        raise HTTPException(503, "PostgreSQL is unavailable")
    return {"service": "identity_service", "status": "ok"}


@app.get("/auth/public-key")
def public_key() -> dict:
    return {"algorithm": "RS256", "public_key": get_public_key_pem().decode("ascii")}


@app.post("/auth/client/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register_client(payload: ClientUserRegister) -> dict:
    phone = normalize_phone(payload.phone)
    user = {
        "id": str(uuid4()),
        "name": payload.name.strip(),
        "phone": phone,
        "email": None,
        "password_hash": hash_password(payload.password),
        "role": "client",
        "customer_id": payload.customer_id,
        "primary_vehicle_id": payload.primary_vehicle_id,
        "created_at": utc_now_iso(),
    }
    with connect(DATABASE_URL) as db:
        try:
            db.execute(
                """
                INSERT INTO users (
                    id, name, phone, email, password_hash, role,
                    customer_id, primary_vehicle_id, created_at
                )
                VALUES (
                    %(id)s, %(name)s, %(phone)s, %(email)s, %(password_hash)s, %(role)s,
                    %(customer_id)s, %(primary_vehicle_id)s, %(created_at)s
                )
                """,
                user,
            )
        except IntegrityError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone already registered") from exc
        token = create_session(db, user["id"])
    return {"access_token": token, "user": public_user(user)}


@app.post("/auth/staff/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register_staff_user(payload: StaffUserRegister) -> dict:
    if payload.role.value == "client":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Use vehicle registration for client users",
        )

    user = {
        "id": str(uuid4()),
        "name": payload.name.strip(),
        "phone": normalize_phone(payload.phone),
        "email": None,
        "password_hash": hash_password(payload.password),
        "role": payload.role.value,
        "customer_id": None,
        "primary_vehicle_id": None,
        "created_at": utc_now_iso(),
    }

    with connect(DATABASE_URL) as db:
        try:
            db.execute(
                """
                INSERT INTO users (
                    id, name, phone, email, password_hash, role,
                    customer_id, primary_vehicle_id, created_at
                )
                VALUES (
                    %(id)s, %(name)s, %(phone)s, %(email)s, %(password_hash)s, %(role)s,
                    %(customer_id)s, %(primary_vehicle_id)s, %(created_at)s
                )
                """,
                user,
            )
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Phone already registered",
            ) from exc

        token = create_session(db, user["id"])

    return {"access_token": token, "user": public_user(user)}


@app.post("/auth/login", response_model=TokenOut)
@app.post("/auth/staff/login", response_model=TokenOut)
def login(payload: StaffLogin) -> dict:
    phone = normalize_phone(payload.phone)
    with connect(DATABASE_URL) as db:
        row = db.execute("SELECT * FROM users WHERE phone = %s", (phone,)).fetchone()
        if (
            not row
            or row["state"] != "active"
            or not row["password_hash"]
            or not verify_password(payload.password, row["password_hash"])
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid phone or password",
            )

        token = create_session(db, row["id"])

    return {"access_token": token, "user": public_user(row)}


@app.post("/sessions/validate", response_model=UserOut)
def validate_session(payload: TokenValidate) -> dict:
    try:
        claims = verify_token(payload.access_token, get_public_key_pem())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    with connect(DATABASE_URL) as db:
        row = db.execute(
            """
            SELECT users.*
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = %s AND sessions.revoked_at IS NULL
            """,
            (payload.access_token,),
        ).fetchone()

    if not row or row["id"] != claims["sub"] or row["state"] != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return public_user(row)


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: TokenValidate) -> Response:
    with connect(DATABASE_URL) as db:
        db.execute(
            "UPDATE sessions SET revoked_at = %s WHERE token = %s AND revoked_at IS NULL",
            (utc_now_iso(), payload.access_token),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


app.include_router(create_router(lambda: DATABASE_URL, create_session))

from services.identity_service.web_sync import create_router as create_sync_router
app.include_router(create_sync_router(lambda: DATABASE_URL))
