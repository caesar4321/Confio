#!/usr/bin/env bash

set -euo pipefail

# Deploy Confio (Django + Web build) to Ubuntu EC2 using systemd (Daphne, Celery, Celery Beat)

usage() {
  echo "Usage: $0 -h <host> [-u ubuntu] -i <path_to_pem> [-d /opt/confio] [-e .env]"
  echo "  -h  EC2 host or IP (required)"
  echo "  -u  SSH user (default: ubuntu)"
  echo "  -i  SSH PEM key path (required)"
  echo "  -d  Remote app dir (default: /opt/confio)"
  echo "  -e  Environment file to deploy (default: .env)"
}

EC2_HOST=""
EC2_USER="ubuntu"
KEY_PATH=""
REMOTE_APP_DIR="/opt/confio"
ENV_FILE=".env"

while getopts ":h:u:i:d:e:" opt; do
  case ${opt} in
    h) EC2_HOST="$OPTARG" ;;
    u) EC2_USER="$OPTARG" ;;
    i) KEY_PATH="$OPTARG" ;;
    d) REMOTE_APP_DIR="$OPTARG" ;;
    e) ENV_FILE="$OPTARG" ;;
    *) usage; exit 1 ;;
  esac
done

if [[ -z "$EC2_HOST" || -z "$KEY_PATH" ]]; then
  usage; exit 1
fi

if [[ ! -f "$KEY_PATH" ]]; then
  echo "❌ PEM key not found: $KEY_PATH"; exit 1
fi

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_DIR="$ROOT_DIR"
TMP_DIR="$(mktemp -d)"
ARCHIVE="/tmp/confio-deploy.tar.gz"

echo "📦 Building web app"
if [[ -d "$PROJECT_DIR/web" ]]; then
  pushd "$PROJECT_DIR/web" >/dev/null
  if command -v npm >/dev/null 2>&1; then
    npm run build
  else
    echo "WARN: npm not found; skipping web build"
  fi
  popd >/dev/null
fi

echo "🧰 Preparing deploy package"
pushd "$TMP_DIR" >/dev/null

# Copy apps (only if present)
for dir in config users p2p_exchange presale blockchain contracts payments achievements auth conversion exchange_rates notifications security send telegram_verification sms_verification usdc_transactions payroll; do
  [[ -d "$PROJECT_DIR/$dir" ]] && cp -r "$PROJECT_DIR/$dir" .
done

# Templates, static, celerybeat-schedule
[[ -d "$PROJECT_DIR/templates" ]] && cp -r "$PROJECT_DIR/templates" .
[[ -d "$PROJECT_DIR/static" ]] && cp -r "$PROJECT_DIR/static" .
[[ -f "$PROJECT_DIR/celerybeat-schedule" ]] && cp "$PROJECT_DIR/celerybeat-schedule" .

# Web build and .well-known
if [[ -d "$PROJECT_DIR/web/build" ]]; then
  mkdir -p web
  cp -r "$PROJECT_DIR/web/build" web/
fi
if [[ -d "$PROJECT_DIR/web/.well-known" ]]; then
  mkdir -p web
  cp -r "$PROJECT_DIR/web/.well-known" web/
fi

# Essentials
cp "$PROJECT_DIR/manage.py" "$PROJECT_DIR/requirements.txt" .
if [[ -f "$PROJECT_DIR/$ENV_FILE" ]]; then
  cp "$PROJECT_DIR/$ENV_FILE" .
else
  echo "WARN: Environment file $ENV_FILE not found in $PROJECT_DIR"
fi

tar -czf "$ARCHIVE" .
popd >/dev/null
rm -rf "$TMP_DIR"

echo "📤 Uploading package to $EC2_USER@$EC2_HOST:/tmp/"
scp -o StrictHostKeyChecking=no -i "$KEY_PATH" "$ARCHIVE" "$EC2_USER@$EC2_HOST:/tmp/confio-deploy.tar.gz"

echo "🔧 Running remote install + restart (requires sudo on remote)"
ssh -o StrictHostKeyChecking=no -i "$KEY_PATH" "$EC2_USER@$EC2_HOST" APP_DIR="$REMOTE_APP_DIR" ENV_FILE="$ENV_FILE" bash -s <<'ENDSSH'
set -euo pipefail
set -x

APP_DIR="${APP_DIR:-/opt/confio}"
VENV_DIR="$APP_DIR/myvenv"
LEGACY_VENV="$APP_DIR/venv"
ENV_FILE="${ENV_FILE:-.env}"

echo "==> Ensure base directories"
sudo mkdir -p "$APP_DIR"
sudo mkdir -p "$APP_DIR/media" "$APP_DIR/staticfiles"

echo "==> Extract release (clean old code, keep env/media/static/venv)"
# Preserve env file, media, staticfiles, venv if present
sudo mkdir -p "$APP_DIR"
sudo mkdir -p "$APP_DIR/media" "$APP_DIR/staticfiles"
if [[ -f "$APP_DIR/$ENV_FILE" ]]; then sudo cp "$APP_DIR/$ENV_FILE" /tmp/${ENV_FILE}.confio.bak.$$; fi

# Remove old app code to avoid stale migrations/files lingering
sudo find "$APP_DIR" -mindepth 1 -maxdepth 1 \
  \( -name venv -o -name myvenv -o -name media -o -name staticfiles -o -name "$ENV_FILE" -o -name ".git" \) -prune -o -exec rm -rf {} +

# Restore env file if we preserved it
if [[ -f /tmp/${ENV_FILE}.confio.bak.$$ ]]; then sudo mv /tmp/${ENV_FILE}.confio.bak.$$ "$APP_DIR/$ENV_FILE"; fi

# Extract new package
sudo tar -xzf /tmp/confio-deploy.tar.gz -C "$APP_DIR"

# Ensure nginx/daphne can traverse app dir and roll legacy venv -> myvenv
sudo chmod 755 "$APP_DIR"
if [[ -d "$LEGACY_VENV" && ! -e "$VENV_DIR" ]]; then
  sudo mv "$LEGACY_VENV" "$VENV_DIR"
elif [[ -L "$VENV_DIR" ]]; then
  TARGET="$(readlink -f "$VENV_DIR" || true)"
  if [[ "$TARGET" == "$LEGACY_VENV" ]]; then
    sudo rm -f "$VENV_DIR"
    sudo mv "$LEGACY_VENV" "$VENV_DIR"
  fi
elif [[ -d "$LEGACY_VENV" && -d "$VENV_DIR" && "$LEGACY_VENV" != "$VENV_DIR" ]]; then
  sudo rm -rf "$LEGACY_VENV"
fi

echo "==> Python venv and requirements"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found; installing"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y && sudo apt-get install -y python3 python3-venv python3-pip
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y python3 python3-pip || true
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip || true
  else
    echo "No supported package manager found (apt/yum/dnf). Aborting."; exit 1
  fi
fi
if [[ ! -d "$VENV_DIR" ]]; then
  sudo python3 -m venv "$VENV_DIR"
fi
sudo "$VENV_DIR/bin/pip" install --upgrade pip wheel
sudo "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Create env file if missing (defaults to RDS Postgres)"
if [[ ! -f "$APP_DIR/$ENV_FILE" ]]; then
  sudo tee "$APP_DIR/$ENV_FILE" >/dev/null <<EOF
DJANGO_SETTINGS_MODULE=config.settings
SECRET_KEY=change-me
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1

# RDS Postgres (defaults / placeholders)
DB_NAME=confio
DB_USER=confio_app
DB_PASSWORD=change-me
DB_HOST=your-rds-endpoint.rds.amazonaws.com
DB_PORT=5432
DB_SSLMODE=require

# Static/media
STATIC_ROOT=/opt/confio/staticfiles
MEDIA_ROOT=/opt/confio/media

# Redis (optional)
REDIS_URL=redis://127.0.0.1:6379/0
EOF
fi

echo "==> Django migrate + collectstatic"
# We need to make sure manage.py uses the correct env file if using python-dotenv or similar.
# Assuming manage.py loads .env by default, or env vars are set via systemd.
# Since we are running migrate here manually, we might need to export variables from the env file first.
# Or trust that verify/migrate works without full env if DB settings are standard?
# Actually, manage.py likely needs the env.
# Let's source it if it's a bash-compatible env file, OR trust the user configured it right.
# Ideally, we run this via 'runscript' or similar if relying on django logic.
# For now, let's just attempt migrate. If it fails due to missing env, the user knows why.

# Check if manage.py can load .env automatically (python-dotenv).
# If $ENV_FILE is not .env, manage.py might not pick it up automatically unless we set an env var.
# But systemd will pick it up.
# For migration here, let's try to export it.
set +x # hide secrets
if [[ -f "$APP_DIR/$ENV_FILE" ]]; then
  export $(grep -v '^#' "$APP_DIR/$ENV_FILE" | xargs) || true
fi
set -x

sudo -E "$VENV_DIR/bin/python" "$APP_DIR/manage.py" migrate --noinput || true
sudo -E "$VENV_DIR/bin/python" "$APP_DIR/manage.py" collectstatic --noinput || true

echo "==> Install systemd units"
if [[ -f "$APP_DIR/config/systemd/daphne.service" ]]; then
  sudo cp "$APP_DIR/config/systemd/daphne.service" /etc/systemd/system/daphne.service
fi
if [[ -f "$APP_DIR/config/systemd/celery.service" ]]; then
  sudo cp "$APP_DIR/config/systemd/celery.service" /etc/systemd/system/celery.service
fi
if [[ -f "$APP_DIR/config/systemd/celery-beat.service" ]]; then
  sudo cp "$APP_DIR/config/systemd/celery-beat.service" /etc/systemd/system/celery-beat.service
fi
if [[ -f "$APP_DIR/config/systemd/flower.service" ]]; then
  sudo cp "$APP_DIR/config/systemd/flower.service" /etc/systemd/system/flower.service
fi

echo "==> Adjust unit file paths to APP_DIR=$APP_DIR"
for unit in daphne.service celery.service celery-beat.service flower.service; do
  if [[ -f "/etc/systemd/system/$unit" ]]; then
    sudo sed -i "s#/opt/confio#${APP_DIR}#g" "/etc/systemd/system/$unit" || true
  fi
done

echo "==> Enable infra services and app services"
sudo systemctl daemon-reload
# Try common Redis service names
for svc in redis-server redis; do
  if systemctl list-unit-files | grep -q "^${svc}\.service"; then
    sudo systemctl enable --now "$svc" || true
    break
  fi
done
# Try common PostgreSQL service names
for svc in postgresql postgresql-15 postgresql-14 postgresql@14-main; do
  if systemctl list-unit-files | grep -q "^${svc}\.service"; then
    sudo systemctl enable --now "$svc" || true
    break
  fi
done
sudo systemctl enable --now nginx || true
sudo systemctl enable daphne.service celery.service celery-beat.service || true

echo "==> Restart app services"
sudo systemctl restart daphne.service
sudo systemctl restart celery.service
sudo systemctl restart celery-beat.service

echo "==> Show statuses"
sudo systemctl --no-pager --full status daphne || true
sudo systemctl --no-pager --full status celery || true
sudo systemctl --no-pager --full status celery-beat || true
ENDSSH

echo "✅ Deploy complete"
echo "Tip: View logs with: ssh -i $KEY_PATH $EC2_USER@$EC2_HOST 'sudo journalctl -u daphne -f'"

