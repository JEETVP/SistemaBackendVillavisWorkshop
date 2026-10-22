CREATE TABLE customers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT,
                created_at TEXT NOT NULL
            , provisioned_via_web INTEGER NOT NULL DEFAULT 0);

CREATE TABLE "vehicles" (
            id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            plate TEXT UNIQUE, vin TEXT UNIQUE, brand TEXT NOT NULL, model TEXT NOT NULL, year INTEGER,
            vehicle_type TEXT, color TEXT, engine_number TEXT, service_type TEXT, owner_name TEXT, created_at TEXT NOT NULL, web_details TEXT);

CREATE UNIQUE INDEX idx_vehicle_normalized_plate
        ON vehicles(UPPER(REPLACE(REPLACE(plate, '-', ''), ' ', ''))) WHERE plate IS NOT NULL AND plate != '';
