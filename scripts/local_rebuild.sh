#!/usr/bin/env bash
set -euo pipefail

# Local clean rebuild helper (against the DB configured in your .env)
# This will:
# - Reset migrations for local apps (files only)
# - Run makemigrations
# - Run migrate
# - Prompt to create a superuser
#
# Usage:
#   ./scripts/local_rebuild.sh
#
# Requirements:
#   - Ensure your .env points to a CLEAN, EMPTY database (e.g. new RDS DB)
#   - Ensure necessary environment variables (SECRET_KEY, etc.) are set or present in .env

CONFIRM=${CONFIRM:-}
if [[ "$CONFIRM" != "YES" ]]; then
  echo "[SAFEGUARD] This will reset migration files and run fresh migrations."
  echo "Set CONFIRM=YES to proceed:"
  echo "  CONFIRM=YES ./scripts/local_rebuild.sh"
  exit 1
fi

echo "[1/4] Resetting migration files..."
./scripts/reset_migrations.sh

echo "[2/4] Running makemigrations..."
python manage.py makemigrations

echo "[3/4] Applying migrations to the configured DB..."
python manage.py migrate

echo "[4/4] (Optional) Create superuser now"
read -r -p "Create superuser now? [y/N] " yn
if [[ "$yn" =~ ^[Yy]$ ]]; then
  python manage.py createsuperuser
fi

echo "Done. Verify /admin locally, then commit and push if everything looks good."

