#!/usr/bin/env bash

set -euo pipefail

# Drop and recreate the configured Postgres database (RDS-friendly), then run Django migrations.
# Usage:
#   ./scripts/db_reset_rds.sh [-e /opt/confio/.env] [-a /opt/confio]
#
# - Expects .env to define DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT (optional), DB_SSLMODE (optional)
# - Requires psql on PATH. Will use $APP_DIR/venv if present for manage.py.

ENV_FILE="/opt/confio/.env"
APP_DIR="/opt/confio"

while getopts ":e:a:" opt; do
  case ${opt} in
    e) ENV_FILE="$OPTARG" ;;
    a) APP_DIR="$OPTARG" ;;
    *) echo "Usage: $0 [-e /path/to/.env] [-a /path/to/app]"; exit 1 ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "❌ .env not found: $ENV_FILE" >&2
  exit 1
fi

# Load only the needed DB_* vars safely
set -a
source "$ENV_FILE"
set +a

: "${DB_NAME:?DB_NAME is required in .env}"
: "${DB_USER:?DB_USER is required in .env}"
: "${DB_PASSWORD:?DB_PASSWORD is required in .env}"
: "${DB_HOST:?DB_HOST is required in .env}"
DB_PORT="${DB_PORT:-5432}"
DB_SSLMODE="${DB_SSLMODE:-require}"

echo "About to DROP and RECREATE database '$DB_NAME' on host '$DB_HOST' as user '$DB_USER' (port $DB_PORT, sslmode=$DB_SSLMODE)."
read -r -p "Type the database name '$DB_NAME' to confirm: " CONFIRM
if [[ "$CONFIRM" != "$DB_NAME" ]]; then
  echo "Aborted."; exit 1
fi

export PGPASSWORD="$DB_PASSWORD"
PSQL_BASE=(psql "host=$DB_HOST" "port=$DB_PORT" "user=$DB_USER" "dbname=postgres" "sslmode=$DB_SSLMODE" -v ON_ERROR_STOP=1 -q)

echo "Terminating connections..."
"${PSQL_BASE[@]}" -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();" || true

echo "Dropping database..."
"${PSQL_BASE[@]}" -c "DROP DATABASE IF EXISTS \"$DB_NAME\";"

echo "Creating database..."
"${PSQL_BASE[@]}" -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\" TEMPLATE template0 ENCODING 'UTF8';"

# Try to enable common extensions if available
echo "Enabling common extensions (if available): pgcrypto, pg_trgm, postgis"
DB_CONN_DB=(psql "host=$DB_HOST" "port=$DB_PORT" "user=$DB_USER" "dbname=$DB_NAME" "sslmode=$DB_SSLMODE" -v ON_ERROR_STOP=0 -q)
"${DB_CONN_DB[@]}" -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;" || true
"${DB_CONN_DB[@]}" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" || true
"${DB_CONN_DB[@]}" -c "CREATE EXTENSION IF NOT EXISTS postgis;" || true

echo "Running Django migrations..."
PYBIN="python3"
if [[ -x "$APP_DIR/venv/bin/python" ]]; then
  PYBIN="$APP_DIR/venv/bin/python"
fi

cd "$APP_DIR"
DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-config.settings} \
"$PYBIN" manage.py migrate --noinput

echo "✅ Database reset and migrations complete."
