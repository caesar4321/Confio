#!/usr/bin/env bash
set -euo pipefail

# Reset (blow away) Django migration files for local apps, keeping __init__.py.
# Usage:
#   ./scripts/reset_migrations.sh            # resets default app list
#   APPS="users payments" ./scripts/reset_migrations.sh   # custom list
#
# NOTE: This only modifies files. It does NOT run makemigrations or migrate.
#       Run those steps separately after pointing to a clean DB.

DEFAULT_APPS=(
  users
  achievements
  security
  telegram_verification
  sms_verification
  send
  payments
  p2p_exchange
  exchange_rates
  conversion
  usdc_transactions
  presale
  notifications
  blockchain
)

IFS=' ' read -r -a APPS <<< "${APPS:-${DEFAULT_APPS[*]}}"

echo "Resetting migrations for apps: ${APPS[*]}"
for app in "${APPS[@]}"; do
  if [ -d "$app/migrations" ]; then
    echo "- $app: cleaning $app/migrations"
    find "$app/migrations" -type f ! -name "__init__.py" -maxdepth 1 -print -delete || true
    # Ensure __init__.py exists
    if [ ! -f "$app/migrations/__init__.py" ]; then
      echo "  creating $app/migrations/__init__.py"
      mkdir -p "$app/migrations"
      printf "" > "$app/migrations/__init__.py"
    fi
  else
    echo "- $app: no migrations/ dir (skipping)"
  fi
done

echo "Done. Next steps:"
echo "  1) Point .env to a clean DB (new RDS DB name)."
echo "  2) Run: python manage.py makemigrations"
echo "  3) Run: python manage.py migrate"
echo "  4) Run: python manage.py createsuperuser"

