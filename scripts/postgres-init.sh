#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 \
  --set identity_password="$IDENTITY_DB_PASSWORD" \
  --set customers_password="$CUSTOMERS_DB_PASSWORD" \
  --set workshop_password="$WORKSHOP_DB_PASSWORD" <<'SQL'
CREATE ROLE identity LOGIN PASSWORD :'identity_password';
CREATE ROLE customers LOGIN PASSWORD :'customers_password';
CREATE ROLE workshop LOGIN PASSWORD :'workshop_password';
CREATE DATABASE identity OWNER identity;
CREATE DATABASE customers OWNER customers;
CREATE DATABASE workshop OWNER workshop;
REVOKE CONNECT ON DATABASE identity FROM PUBLIC;
REVOKE CONNECT ON DATABASE customers FROM PUBLIC;
REVOKE CONNECT ON DATABASE workshop FROM PUBLIC;
SQL
