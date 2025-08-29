#!/usr/bin/env bash

set -euo pipefail

# This script prepares an Ubuntu EC2 to run Confio via systemd (Daphne + Celery)
# Assumes the project code is at /home/ubuntu/Confio (edit PROJECT_DIR if different)

PROJECT_DIR="/opt/confio"
PYTHON_BIN="python3"
VENV_DIR="$PROJECT_DIR/venv"
ENV_FILE="$PROJECT_DIR/.env"

echo "==> Installing OS dependencies (requires sudo)"
sudo apt-get update -y
sudo apt-get install -y \
  ${PYTHON_BIN}-venv \
  nginx redis-server postgresql postgresql-contrib \
  build-essential

echo "==> Ensuring project directory exists at $PROJECT_DIR"
sudo mkdir -p "$PROJECT_DIR"
sudo chown -R root:root "$PROJECT_DIR"
sudo mkdir -p "$PROJECT_DIR/media" "$PROJECT_DIR/staticfiles"
sudo chown -R www-data:www-data "$PROJECT_DIR/media" "$PROJECT_DIR/staticfiles"

echo "==> Creating Python virtualenv at $VENV_DIR"
if [ ! -d "$VENV_DIR" ]; then
  $PYTHON_BIN -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip wheel

if [ -f "$PROJECT_DIR/requirements.txt" ]; then
  echo "==> Installing Python requirements"
  "$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
else
  echo "WARN: $PROJECT_DIR/requirements.txt not found; skipping pip install"
fi

echo "==> Writing environment file to $ENV_FILE (create or keep existing)"
if [ ! -f "$ENV_FILE" ]; then
  sudo tee "$ENV_FILE" >/dev/null <<'EOF'
# Confio environment for systemd services
DJANGO_SETTINGS_MODULE=config.settings
SECRET_KEY=change-me
DEBUG=False
ALLOWED_HOSTS=confio.lat,www.confio.lat,localhost,127.0.0.1
STATIC_ROOT=/opt/confio/staticfiles
MEDIA_ROOT=/opt/confio/media
REDIS_URL=redis://127.0.0.1:6379/0
# PostgreSQL (RDS) configuration — set these after creating RDS
DB_NAME=confio
DB_USER=postgres
DB_PASSWORD=
DB_HOST=
DB_PORT=5432
# Optional DB tuning
DB_SSLMODE=require
DB_CONN_MAX_AGE=300
# Algorand mainnet endpoints (Nodely)
ALGORAND_NETWORK=mainnet
ALGORAND_ALGOD_ADDRESS=https://mainnet-api.4160.nodely.dev
ALGORAND_INDEXER_ADDRESS=https://mainnet-idx.4160.nodely.dev
# Required secrets (placeholders — replace in production)
# ALGORAND_SPONSOR_ADDRESS=
# ALGORAND_SPONSOR_MNEMONIC=
# ALGORAND_PAYMENT_APP_ID=
EOF
  sudo chmod 640 "$ENV_FILE"
  sudo chown root:root "$ENV_FILE"
else
  echo "Keeping existing $ENV_FILE"
fi

echo "==> Running Django collectstatic and migrate (if manage.py exists)"
if [ -f "$PROJECT_DIR/manage.py" ]; then
  "$VENV_DIR/bin/python" "$PROJECT_DIR/manage.py" collectstatic --noinput || true
  "$VENV_DIR/bin/python" "$PROJECT_DIR/manage.py" migrate --noinput || true
fi

echo "==> Installing systemd unit files"
if [ -f "$PROJECT_DIR/config/systemd/daphne.service" ]; then
  sudo cp "$PROJECT_DIR/config/systemd/daphne.service" /etc/systemd/system/daphne.service
fi
if [ -f "$PROJECT_DIR/config/systemd/celery.service" ]; then
  sudo cp "$PROJECT_DIR/config/systemd/celery.service" /etc/systemd/system/celery.service
fi
if [ -f "$PROJECT_DIR/config/systemd/celery-beat.service" ]; then
  sudo cp "$PROJECT_DIR/config/systemd/celery-beat.service" /etc/systemd/system/celery-beat.service
fi
if [ -f "$PROJECT_DIR/config/systemd/flower.service" ]; then
  sudo cp "$PROJECT_DIR/config/systemd/flower.service" /etc/systemd/system/flower.service
fi

echo "==> Enabling OS services (nginx, redis, postgresql)"
sudo systemctl enable --now nginx
sudo systemctl enable --now redis-server
sudo systemctl enable --now postgresql

echo "==> Adding Restart=always overrides for OS services"
sudo mkdir -p /etc/systemd/system/nginx.service.d
sudo tee /etc/systemd/system/nginx.service.d/override.conf >/dev/null <<'EOF'
[Service]
Restart=always
RestartSec=5s
EOF

sudo mkdir -p /etc/systemd/system/redis-server.service.d
sudo tee /etc/systemd/system/redis-server.service.d/override.conf >/dev/null <<'EOF'
[Service]
Restart=always
RestartSec=5s
EOF

sudo mkdir -p /etc/systemd/system/postgresql.service.d
sudo tee /etc/systemd/system/postgresql.service.d/override.conf >/dev/null <<'EOF'
[Service]
Restart=always
RestartSec=5s
EOF

echo "==> Reloading systemd and enabling app services"
sudo systemctl daemon-reload
sudo systemctl enable daphne.service
sudo systemctl enable celery.service
sudo systemctl enable celery-beat.service
# Optional:
# sudo systemctl enable flower.service

echo "==> Starting services"
sudo systemctl restart daphne.service
sudo systemctl restart celery.service
sudo systemctl restart celery-beat.service

echo "==> Restarting OS services to apply overrides"
sudo systemctl restart nginx
sudo systemctl restart redis-server
sudo systemctl restart postgresql

echo "==> Done. Useful commands:"
echo "  sudo systemctl status daphne"
echo "  sudo systemctl status celery"
echo "  sudo systemctl status celery-beat"
echo "  sudo systemctl status nginx redis-server postgresql"
echo "  sudo journalctl -u daphne -f"
echo "  sudo journalctl -u celery -f"
echo "  sudo journalctl -u celery-beat -f"
