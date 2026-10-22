CREATE TABLE app_notifications (
                id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                related_entity_type TEXT,
                related_entity_id TEXT,
                read_at TEXT,
                created_at TEXT NOT NULL
            );

CREATE TABLE appointment_payment_requests (
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
            );

CREATE TABLE appointment_services (
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
            );

CREATE TABLE appointments (
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
            );

CREATE TABLE evidence (
                id TEXT PRIMARY KEY,
                work_order_id TEXT NOT NULL,
                file_url TEXT NOT NULL,
                caption TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (work_order_id) REFERENCES work_orders(id) ON DELETE CASCADE
            );

CREATE TABLE payments (
                id TEXT PRIMARY KEY,
                work_order_id TEXT NOT NULL,
                amount REAL NOT NULL,
                provider TEXT NOT NULL,
                reference TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (work_order_id) REFERENCES work_orders(id) ON DELETE CASCADE
            );

CREATE TABLE purchase_tickets (
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
            );

CREATE TABLE quote_items (
                id TEXT PRIMARY KEY,
                quote_id TEXT NOT NULL,
                service_id TEXT,
                cylinder_count INTEGER,
                description TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL DEFAULT 0,
                total REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (quote_id) REFERENCES quotes(id) ON DELETE CASCADE
            );

CREATE TABLE quotes (
                id TEXT PRIMARY KEY,
                work_order_id TEXT NOT NULL,
                status TEXT NOT NULL,
                subtotal REAL NOT NULL DEFAULT 0,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (work_order_id) REFERENCES work_orders(id) ON DELETE CASCADE
            );

CREATE TABLE recommendations (
                id TEXT PRIMARY KEY,
                vehicle_id TEXT NOT NULL,
                title TEXT NOT NULL,
                notes TEXT,
                priority TEXT NOT NULL,
                due_date TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

CREATE TABLE service_cart_items (
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
            );

CREATE TABLE service_carts (
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
            );

CREATE TABLE service_catalog (
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
            );

CREATE TABLE vehicle_intake_photos (
                id TEXT PRIMARY KEY,
                intake_id TEXT NOT NULL,
                photo_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (intake_id) REFERENCES vehicle_intakes(id) ON DELETE CASCADE
            );

CREATE TABLE vehicle_intakes (
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
            );

CREATE TABLE work_order_tasks (
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
            );

CREATE TABLE work_orders (
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
            , web_details TEXT);

CREATE TABLE workshop_notifications (
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
            );

CREATE TABLE workshops (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                photo_url TEXT,
                phone TEXT,
                description TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            , owner_id TEXT, location_json TEXT);

CREATE UNIQUE INDEX idx_workshops_owner ON workshops(owner_id) WHERE owner_id IS NOT NULL;
