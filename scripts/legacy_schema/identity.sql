CREATE TABLE activations (
        token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        expires_at REAL NOT NULL);

CREATE TABLE sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

CREATE TABLE users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT UNIQUE,
                password_hash TEXT,
                role TEXT NOT NULL,
                customer_id TEXT,
                primary_vehicle_id TEXT,
                created_at TEXT NOT NULL
            , state TEXT NOT NULL DEFAULT 'active', workshop_id TEXT, registration_workshop_id TEXT);

CREATE UNIQUE INDEX idx_users_phone ON users(phone) WHERE phone IS NOT NULL;
