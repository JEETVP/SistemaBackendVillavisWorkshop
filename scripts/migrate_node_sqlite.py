"""Import Node's SQLite records into the canonical FastAPI databases, offline.

The default is a read-only preview. --apply backs up existing targets before any
schema changes and imports in one transaction across three attached databases.
Existing IDs are never overwritten. Session cookies must be renewed by login.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def source_snapshot(source):
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        return {table: [dict(row) for row in db.execute(f"SELECT * FROM {table}")]
                for table in ("accounts", "workshops", "vehicles", "orders", "activations")}


def insert_without_overwrite(db, schema, table, values, identity_fields):
    existing = db.execute(f"SELECT * FROM {schema}.{table} WHERE id = ?", (values["id"],)).fetchone()
    if existing:
        if any(existing[key] != values[key] for key in identity_fields):
            raise ValueError(f"Conflicting identity in {table}; no records imported")
        return False
    names = list(values)
    db.execute(f"INSERT INTO {schema}.{table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})", list(values.values()))
    return True


def migrate(source, target_directory, apply=False):
    source, target_directory = Path(source).resolve(), Path(target_directory).resolve()
    snapshot = source_snapshot(source)
    counts = {table: len(rows) for table, rows in snapshot.items()}
    result = {"mode": "apply" if apply else "preview", "source_counts": counts,
              "sessions": "Not imported; sign in again with the same credentials"}
    # Parse and validate relationships before touching destination files.
    accounts = {row["id"]: (row, json.loads(row["payload"])) for row in snapshot["accounts"]}
    workshops = {row["id"]: (row, json.loads(row["payload"])) for row in snapshot["workshops"]}
    vehicles = {row["id"]: (row, json.loads(row["payload"])) for row in snapshot["vehicles"]}
    orders = [(row, json.loads(row["payload"])) for row in snapshot["orders"]]
    for row, _ in workshops.values():
        if row["owner_id"] not in accounts or accounts[row["owner_id"]][0]["role"] != "taller":
            raise ValueError("Workshop has no valid owner")
    for row, _ in vehicles.values():
        if row["owner_id"] not in accounts or accounts[row["owner_id"]][0]["role"] != "user":
            raise ValueError("Vehicle has no valid customer")
    for row, payload in orders:
        if row["workshop_id"] not in workshops or row["customer_id"] not in accounts or payload.get("vehiculoId") not in vehicles:
            raise ValueError("Order has a missing workshop, customer or vehicle")
        if vehicles[payload["vehiculoId"]][0]["owner_id"] != row["customer_id"]:
            raise ValueError("Order vehicle belongs to a different customer")
    for row, _ in accounts.values():
        if row["role"] not in {"user", "taller"} or row["state"] not in {"activo", "inactivo", "pendiente_activacion", "deudor"}:
            raise ValueError("Unsupported legacy account role or state")
        if bool(row["salt"]) != bool(row["verifier"]):
            raise ValueError("Incomplete legacy credentials")
        if row["verifier"]:
            if len(bytes.fromhex(row["salt"])) != 16 or len(bytes.fromhex(row["verifier"])) != 64:
                raise ValueError("Invalid legacy scrypt credentials")
    if not apply:
        return result

    from services.identity_service.app import init_db as init_identity
    from services.customer_service.app import init_db as init_customers
    from services.workshop_service.app import init_db as init_workshops
    from services.workshop_service.web import init_web_workshops
    from services.common.database import connect
    from services.common.time import utc_now_iso

    target_directory.mkdir(parents=True, exist_ok=True)
    paths = {name: target_directory / f"{name}.db" for name in ("identity", "customers", "workshop")}
    if source in paths.values():
        raise ValueError("The source must be different from all destination databases")
    backup_dir = target_directory / "migration-backups" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    backup_dir.mkdir(parents=True)
    for name, path in paths.items():
        if path.exists():
            with closing(sqlite3.connect(path)) as original, closing(sqlite3.connect(backup_dir / f"{name}.db")) as backup:
                original.backup(backup)
    init_identity(str(paths["identity"]))
    init_customers(str(paths["customers"]))
    init_workshops(str(paths["workshop"]))
    with connect(str(paths["workshop"])) as db:
        init_web_workshops(db)

    imported = {name: 0 for name in ("users", "customers", "vehicles", "workshops", "work_orders", "activations")}
    with connect(str(paths["identity"])) as db:
        db.execute("ATTACH DATABASE ? AS customer_data", (str(paths["customers"]),))
        db.execute("ATTACH DATABASE ? AS workshop_data", (str(paths["workshop"]),))
        # DELETE journals support SQLite's super-journal for cross-file commits.
        for schema in ("main", "customer_data", "workshop_data"):
            db.execute(f"PRAGMA {schema}.journal_mode = DELETE")
        db.execute("BEGIN IMMEDIATE")
        for uid, (row, payload) in accounts.items():
            client = row["role"] == "user"
            workshop_id = next((wid for wid, (wrow, _) in workshops.items() if wrow["owner_id"] == uid), None)
            registration_id = next((orow["workshop_id"] for orow, _ in orders if orow["customer_id"] == uid), None)
            first_vehicle = next((vid for vid, (vrow, _) in vehicles.items() if vrow["owner_id"] == uid), None)
            created = payload.get("createdAt") or utc_now_iso()
            values = {"id": uid, "name": payload.get("nombre") or payload.get("email") or "Usuario migrado",
                "phone": row["phone"], "email": row["email"], "password_hash": f"node_scrypt${row['salt']}${row['verifier']}" if row["verifier"] else None,
                "role": "client" if client else "staff", "customer_id": uid if client else None, "primary_vehicle_id": first_vehicle,
                "created_at": created, "state": {"activo": "active", "inactivo": "inactive", "deudor": "inactive",
                    "pendiente_activacion": "pending_activation"}[row["state"]], "workshop_id": workshop_id,
                "registration_workshop_id": registration_id if client else workshop_id}
            imported["users"] += insert_without_overwrite(db, "main", "users", values, ["phone", "email", "role", "customer_id", "workshop_id"])
            if client:
                imported["customers"] += insert_without_overwrite(db, "customer_data", "customers", {
                    "id": uid, "name": values["name"], "phone": row["phone"], "email": row["email"],
                    "created_at": created, "provisioned_via_web": 0}, ["phone"])
        for wid, (row, payload) in workshops.items():
            location = payload["ubicacion"]
            imported["workshops"] += insert_without_overwrite(db, "workshop_data", "workshops", {
                "id": wid, "name": payload["nombre"], "address": ", ".join(location[key] for key in ("direccion", "ciudad", "estado", "codigoPostal")),
                "active": accounts[row["owner_id"]][0]["state"] == "activo", "created_at": payload.get("createdAt") or utc_now_iso(),
                "owner_id": row["owner_id"], "location_json": json.dumps(location, ensure_ascii=False)}, ["owner_id"])
        for vid, (row, payload) in vehicles.items():
            extra = {key: value for key, value in payload.items() if key not in {
                "id", "conductorId", "marca", "modelo", "anio", "placas", "numeroSerie", "color", "createdAt"}}
            imported["vehicles"] += insert_without_overwrite(db, "customer_data", "vehicles", {
                "id": vid, "customer_id": row["owner_id"], "plate": row["plate"] or None, "vin": row["vin"],
                "brand": payload["marca"], "model": payload["modelo"], "year": payload["anio"], "color": payload.get("color") or None,
                "owner_name": accounts[row["owner_id"]][1].get("nombre"), "created_at": payload.get("createdAt") or utc_now_iso(),
                "web_details": json.dumps(extra, ensure_ascii=False)}, ["customer_id", "plate", "vin"])
        for row, payload in orders:
            stage = payload.get("progreso", {}).get("etapa", "Diagnóstico")
            status = {"Diagnóstico": "diagnosis", "Cotización": "diagnosis", "Autorización": "awaiting_approval",
                "Servicio": "in_progress", "Entrega": "ready"}.get(stage, "diagnosis")
            status = {"Finalizada": "delivered", "Cancelada": "cancelled"}.get(payload.get("estado"), status)
            extra = {key: value for key, value in payload.items() if key not in {
                "id", "userId", "vehiculoId", "tallerId", "tallerNombre", "estado", "createdAt", "updatedAt", "motivoServicio"}}
            created = payload.get("createdAt") or utc_now_iso()
            imported["work_orders"] += insert_without_overwrite(db, "workshop_data", "work_orders", {
                "id": row["id"], "workshop_id": row["workshop_id"], "customer_id": row["customer_id"],
                "vehicle_id": payload["vehiculoId"], "description": payload.get("motivoServicio") or "Servicio migrado desde Node",
                "priority": "normal", "status": status,
                "estimated_total": sum(item.get("precioCentavos", 0) for item in payload.get("servicios", [])) / 100,
                "created_at": created, "updated_at": payload.get("updatedAt") or created,
                "web_details": json.dumps(extra, ensure_ascii=False)}, ["workshop_id", "customer_id", "vehicle_id"])
        for activation in snapshot["activations"]:
            uid = activation["account_id"]
            user = db.execute("SELECT state FROM users WHERE id = ?", (uid,)).fetchone()
            if user and user["state"] == "pending_activation" and not db.execute("SELECT 1 FROM activations WHERE user_id = ?", (uid,)).fetchone():
                db.execute("INSERT INTO activations VALUES (?, ?, ?)", (activation["hash"], uid, activation["expires"] / 1000))
                imported["activations"] += 1
    result.update(imported=imported, backup_directory=str(backup_dir))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target-directory", type=Path, default=ROOT / "data")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.source, args.target_directory, args.apply), indent=2))
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        # Do not expose payloads or credentials when reporting a migration error.
        parser.exit(1, f"Migration stopped ({type(error).__name__}). Existing records were not overwritten.\n")


if __name__ == "__main__":
    main()
