import hashlib
import json
import time

from test_integration import ServiceFixture
from scripts.migrate_node_sqlite import migrate
from services.common.database import connect
from services.identity_service.security import verify_password


class NodeMigrationTests(ServiceFixture):
    def legacy_fixture(self):
        source = self.directory / "legacy.sqlite"
        salt = "ab" * 16
        verifier = hashlib.scrypt(b"ClaveMigrada123!", salt=salt.encode(), n=16384, r=8, p=1, dklen=64).hex()
        created = "2026-10-19T10:00:00+00:00"
        owner = {"uid": "legacy-owner", "nombre": "Ana", "email": "legacy@prueba.test", "createdAt": created}
        customer = {"uid": "legacy-customer", "nombre": "Luis", "celular": "2223334444", "createdAt": created}
        location = {"direccion": "Calle 10", "ciudad": "Puebla", "estado": "Puebla", "codigoPostal": "72000", "pais": "México"}
        workshop = {"id": "legacy-workshop", "nombre": "Taller migrado", "ubicacion": location, "createdAt": created}
        vehicle = {"id": "legacy-vehicle", "marca": "Volkswagen", "modelo": "Jetta", "anio": 2020,
            "placas": "XYZ123", "numeroSerie": "3VW2K7AJ5EM123456", "cilindros": 4, "combustible": "Gasolina",
            "kilometraje": 45000, "createdAt": created}
        order = {"id": "legacy-order", "vehiculoId": vehicle["id"], "motivoServicio": "Frenos", "createdAt": created,
            "estado": "Revision", "servicios": [{"precioCentavos": 12550}]}
        with connect(str(source)) as db:
            db.executescript('''CREATE TABLE accounts (id TEXT PRIMARY KEY, role TEXT, email TEXT, phone TEXT, state TEXT, payload TEXT, salt TEXT, verifier TEXT);
                CREATE TABLE workshops (id TEXT, owner_id TEXT, payload TEXT);
                CREATE TABLE vehicles (id TEXT, owner_id TEXT, vin TEXT, plate TEXT, payload TEXT);
                CREATE TABLE orders (id TEXT, workshop_id TEXT, customer_id TEXT, payload TEXT);
                CREATE TABLE activations (hash TEXT, account_id TEXT, expires INTEGER);''')
            db.execute("INSERT INTO accounts VALUES (?, 'taller', ?, NULL, 'activo', ?, ?, ?)", (owner["uid"], owner["email"], json.dumps(owner), salt, verifier))
            db.execute("INSERT INTO accounts VALUES (?, 'user', NULL, ?, 'pendiente_activacion', ?, NULL, NULL)",
                       (customer["uid"], customer["celular"], json.dumps(customer)))
            db.execute("INSERT INTO workshops VALUES (?, ?, ?)", (workshop["id"], owner["uid"], json.dumps(workshop)))
            db.execute("INSERT INTO vehicles VALUES (?, ?, ?, ?, ?)", (vehicle["id"], customer["uid"], vehicle["numeroSerie"], vehicle["placas"], json.dumps(vehicle)))
            db.execute("INSERT INTO orders VALUES (?, ?, ?, ?)", (order["id"], workshop["id"], customer["uid"], json.dumps(order)))
            db.execute("INSERT INTO activations VALUES (?, ?, ?)", (hashlib.sha256(b"A" * 43).hexdigest(), customer["uid"], int((time.time() + 86400) * 1000)))
        return source

    def test_preview_does_not_create_destination_or_modify_source(self):
        source = self.legacy_fixture()
        before = source.read_bytes()
        target = self.directory / "new-target"
        result = migrate(source, target)
        self.assertEqual(result["source_counts"]["accounts"], 2)
        self.assertFalse(target.exists())
        self.assertEqual(source.read_bytes(), before)

    def test_import_preserves_ids_passwords_tokens_and_is_repeatable(self):
        source = self.legacy_fixture()
        result = migrate(source, self.directory, apply=True)
        self.assertEqual(result["imported"]["users"], 2)
        self.assertEqual(result["imported"]["work_orders"], 1)
        with connect(str(self.directory / "identity.db")) as db:
            saved = db.execute("SELECT * FROM users WHERE id = 'legacy-owner'").fetchone()
            self.assertEqual(saved["workshop_id"], "legacy-workshop")
            self.assertTrue(verify_password("ClaveMigrada123!", saved["password_hash"]))
            self.assertFalse(verify_password("incorrecta", saved["password_hash"]))
            self.assertEqual(db.execute("SELECT count(*) FROM activations WHERE user_id = 'legacy-customer'").fetchone()[0], 1)
            # An already-migrated account may change its password; rerunning never overwrites it.
            db.execute("UPDATE users SET password_hash = 'changed-after-migration' WHERE id = 'legacy-owner'")
        repeated = migrate(source, self.directory, apply=True)
        self.assertTrue(all(count == 0 for count in repeated["imported"].values()))
        with connect(str(self.directory / "identity.db")) as db:
            self.assertEqual(db.execute("SELECT password_hash FROM users WHERE id = 'legacy-owner'").fetchone()[0], "changed-after-migration")
        with connect(str(self.directory / "workshop.db")) as db:
            self.assertEqual(db.execute("SELECT estimated_total FROM work_orders WHERE id = 'legacy-order'").fetchone()[0], 125.5)

    def test_conflict_rolls_back_import_across_databases(self):
        source = self.legacy_fixture()
        with connect(str(self.directory / "workshop.db")) as db:
            db.execute("INSERT INTO workshops (id, name, address, active, created_at, owner_id) VALUES ('legacy-workshop', 'Existing', 'Existing address', 1, '2026-10-19', 'different-owner')")
        with self.assertRaises(ValueError):
            migrate(source, self.directory, apply=True)
        with connect(str(self.directory / "identity.db")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users WHERE id LIKE 'legacy-%'").fetchone()[0], 0)
        with connect(str(self.directory / "customers.db")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM customers WHERE id = 'legacy-customer'").fetchone()[0], 0)
