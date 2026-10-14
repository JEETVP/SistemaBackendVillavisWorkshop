from __future__ import annotations

import os
import sqlite3
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status

from services.common.database import connect, db_path_from_env
from services.common.time import utc_now_iso
from services.identity_service.schemas import (
    StaffLogin,
    StaffUserRegister,
    TokenOut,
    TokenValidate,
    UserOut,
    VehicleSessionCreate,
)
from services.identity_service.security import create_token, hash_password, verify_password

DB_PATH = db_path_from_env("IDENTITY_DB_PATH", "data/identity.db")

app = FastAPI(
    title="Villavis Identity Service",
    description="Microservicio de usuarios, sesiones y roles.",
    version="1.0.0",
)


def public_user(data: sqlite3.Row | dict) -> dict:
    user = dict(data)
    user.pop("password_hash", None)
    return user


def create_session(db: sqlite3.Connection, user_id: str) -> str:
    token = create_token()
    db.execute(
        "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, user_id, utc_now_iso()),
    )
    return token


def init_db() -> None:
    with connect(DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT,
                role TEXT NOT NULL,
                customer_id TEXT,
                primary_vehicle_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
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

        bootstrap_admin_email = os.getenv("IDENTITY_BOOTSTRAP_ADMIN_EMAIL")
        bootstrap_admin_password = os.getenv("IDENTITY_BOOTSTRAP_ADMIN_PASSWORD")
        if bootstrap_admin_email and bootstrap_admin_password:
            existing = db.execute(
                "SELECT id FROM users WHERE email = ?",
                (bootstrap_admin_email.lower(),),
            ).fetchone()
            if not existing:
                db.execute(
                    """
                    INSERT INTO users (
                        id, name, email, password_hash, role,
                        customer_id, primary_vehicle_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        "Admin Villavis",
                        bootstrap_admin_email.lower(),
                        hash_password(bootstrap_admin_password),
                        "admin",
                        None,
                        None,
                        utc_now_iso(),
                    ),
                )


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"service": "identity_service", "status": "ok"}


@app.post("/auth/vehicle-session", response_model=TokenOut)
def create_vehicle_session(payload: VehicleSessionCreate) -> dict:
    with connect(DB_PATH) as db:
        row = db.execute(
            "SELECT * FROM users WHERE role = 'client' AND customer_id = ?",
            (payload.customer_id,),
        ).fetchone()

        if row:
            db.execute(
                "UPDATE users SET name = ?, primary_vehicle_id = ? WHERE id = ?",
                (payload.name.strip(), payload.primary_vehicle_id, row["id"]),
            )
            row = db.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
        else:
            user_id = str(uuid4())
            db.execute(
                """
                INSERT INTO users (
                    id, name, email, password_hash, role,
                    customer_id, primary_vehicle_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    payload.name.strip(),
                    None,
                    None,
                    "client",
                    payload.customer_id,
                    payload.primary_vehicle_id,
                    utc_now_iso(),
                ),
            )
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

        token = create_session(db, row["id"])
    return {"access_token": token, "user": public_user(row)}


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
        "email": payload.email.lower(),
        "password_hash": hash_password(payload.password),
        "role": payload.role.value,
        "customer_id": None,
        "primary_vehicle_id": None,
        "created_at": utc_now_iso(),
    }

    with connect(DB_PATH) as db:
        try:
            db.execute(
                """
                INSERT INTO users (
                    id, name, email, password_hash, role,
                    customer_id, primary_vehicle_id, created_at
                )
                VALUES (
                    :id, :name, :email, :password_hash, :role,
                    :customer_id, :primary_vehicle_id, :created_at
                )
                """,
                user,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            ) from exc

        token = create_session(db, user["id"])

    return {"access_token": token, "user": public_user(user)}


@app.post("/auth/staff/login", response_model=TokenOut)
def staff_login(payload: StaffLogin) -> dict:
    with connect(DB_PATH) as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (payload.email.lower(),)).fetchone()
        if (
            not row
            or row["role"] not in {"staff", "admin"}
            or not row["password_hash"]
            or not verify_password(payload.password, row["password_hash"])
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid staff credentials",
            )

        token = create_session(db, row["id"])

    return {"access_token": token, "user": public_user(row)}


@app.post("/sessions/validate", response_model=UserOut)
def validate_session(payload: TokenValidate) -> dict:
    with connect(DB_PATH) as db:
        row = db.execute(
            """
            SELECT users.*
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.revoked_at IS NULL
            """,
            (payload.access_token,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return public_user(row)


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: TokenValidate) -> None:
    with connect(DB_PATH) as db:
        db.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token = ? AND revoked_at IS NULL",
            (utc_now_iso(), payload.access_token),
        )
