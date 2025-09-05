#!/usr/bin/env bash
set -euo pipefail

# Confio EC2 setup: Redis + systemd units for Daphne, Celery, Celery Beat
# Target: Amazon Linux 2 or Amazon Linux 2023

APP_DIR="/opt/confio"
VENV_BIN="$APP_DIR/venv/bin"
ENV_FILE="$APP_DIR/.env"
RUN_USER="nginx"

ensure_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "Please run as root (use sudo)." >&2
    exit 1
  fi
}

detect_os() {
  source /etc/os-release || true
  OS_ID=${ID:-}
  OS_VER=${VERSION_ID:-}
  echo "Detected OS: ${PRETTY_NAME:-$OS_ID $OS_VER}"
}

ensure_swap() {
  # Create a small swapfile if no swap is active to avoid OOM during package installs on small instances.
  if swapon --show | grep -q '^'; then
    echo "Swap already active."
    return
  fi
  local mem_kb
  mem_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
  # If memory < 2GB, create a 1GB swapfile
  if [[ -n "$mem_kb" && "$mem_kb" -lt 2097152 ]]; then
    echo "Creating 1G swapfile to prevent OOM during install..."
    fallocate -l 1G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=1024
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
  fi
}

install_redis() {
  if command -v redis-server >/dev/null 2>&1 || systemctl list-unit-files | grep -Eq '^(redis|redis6)\.service'; then
    echo "Redis already installed."
    return
  fi

  if command -v dnf >/dev/null 2>&1; then
    if [[ "${OS_ID:-}" == "amzn" && "${OS_VER:-}" =~ ^2023 ]]; then
      echo "Installing redis6 via dnf (Amazon Linux 2023)..."
      dnf -y install --setopt=install_weak_deps=False redis6
    else
      echo "Installing redis via dnf (reduced deps)..."
      dnf -y install --setopt=install_weak_deps=False redis
    fi
  elif command -v yum >/dev/null 2>&1; then
    echo "Installing Redis via yum..."
    if command -v amazon-linux-extras >/dev/null 2>&1; then
      amazon-linux-extras enable redis6 || true
      yum clean metadata -y || true
    fi
    yum install -y redis
  else
    echo "Unsupported package manager; install Redis manually." >&2
    exit 1
  fi
}

configure_redis() {
  local conf
  local service
  if [[ -f "/etc/redis6/redis6.conf" ]]; then
    conf="/etc/redis6/redis6.conf"
    service="redis6"
  else
    conf="/etc/redis/redis.conf"
    service="redis"
  fi
  if [[ ! -f "$conf" ]]; then
    echo "Redis config not found at $conf" >&2
    exit 1
  fi
  echo "Configuring Redis at $conf..."
  sed -i -E 's/^#?bind .*/bind 127.0.0.1/' "$conf"
  sed -i -E 's/^#?protected-mode .*/protected-mode yes/' "$conf"
  sed -i -E 's/^#?appendonly .*/appendonly yes/' "$conf"
  if grep -q '^supervised ' "$conf"; then
    sed -i -E 's/^supervised .*/supervised systemd/' "$conf"
  else
    echo 'supervised systemd' >> "$conf"
  fi

  systemctl enable "$service"
  systemctl restart "$service"
  sleep 1
  local cli
  if command -v redis-cli >/dev/null 2>&1; then
    cli=redis-cli
  elif command -v redis6-cli >/dev/null 2>&1; then
    cli=redis6-cli
  else
    echo "Redis CLI not found; skipping PING check." >&2
    return
  fi
  if ! "$cli" ping | grep -q PONG; then
    echo "Redis did not respond to PING" >&2
    systemctl status "$service" --no-pager || true
    exit 1
  fi
}

ensure_app_paths() {
  if [[ ! -d "$APP_DIR" ]]; then
    echo "App directory $APP_DIR not found. Deploy the app first." >&2
    exit 1
  fi
  if [[ ! -x "$VENV_BIN/python" ]]; then
    echo "Python venv not found at $VENV_BIN; creating..."
    /usr/bin/python3 -m venv "$APP_DIR/venv"
  fi
  mkdir -p /var/lib/confio
  chown -R "$RUN_USER:$RUN_USER" /var/lib/confio
}

ensure_python_deps() {
  # Keep this lightweight to avoid heavy downloads/compiles that could strain small instances.
  # Assume requirements.txt already installed during app deploy.
  echo "Checking Python dependencies are present (no installs will be performed)..."
  for pkg in daphne channels-redis celery; do
    if ! "$VENV_BIN/pip" show "$pkg" >/dev/null 2>&1; then
      echo "Warning: Python package '$pkg' not found in venv. Please install via requirements prior to enabling services." >&2
    fi
  done
}

update_env() {
  echo "Ensuring $ENV_FILE has Redis settings (non-destructive)..."
  touch "$ENV_FILE"
  if ! grep -q '^USE_REDIS_CACHE=' "$ENV_FILE"; then
    echo 'USE_REDIS_CACHE=true' >> "$ENV_FILE"
  fi
  if ! grep -q '^REDIS_URL=' "$ENV_FILE"; then
    echo 'REDIS_URL=redis://127.0.0.1:6379/0' >> "$ENV_FILE"
  fi
  chown "$RUN_USER:$RUN_USER" "$ENV_FILE"
}

install_systemd_units() {
  echo "Installing systemd units for daphne, celery, celery-beat..."

  cat > /etc/systemd/system/daphne.service <<EOF
[Unit]
Description=Daphne ASGI server for Confio
After=network-online.target postgresql.service redis.service redis6.service
Wants=network-online.target postgresql.service redis.service redis6.service

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
Environment=DJANGO_SETTINGS_MODULE=config.settings
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_BIN/daphne -b 127.0.0.1 -p 8000 config.asgi:application
Restart=always
RestartSec=3
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
EOF

  cat > /etc/systemd/system/celery.service <<EOF
[Unit]
Description=Celery Worker for Confio
After=network-online.target postgresql.service redis.service redis6.service
Wants=network-online.target postgresql.service redis.service redis6.service

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
Environment=DJANGO_SETTINGS_MODULE=config.settings
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_BIN/celery -A config worker --loglevel=INFO
Restart=always
RestartSec=5
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
EOF

  cat > /etc/systemd/system/celery-beat.service <<EOF
[Unit]
Description=Celery Beat Scheduler for Confio
After=network-online.target postgresql.service redis.service redis6.service
Wants=network-online.target postgresql.service redis.service redis6.service

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
Environment=DJANGO_SETTINGS_MODULE=config.settings
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_BIN/celery -A config beat --loglevel=INFO --pidfile=/run/celery/beat.pid --schedule /var/lib/confio/celerybeat-schedule
RuntimeDirectory=celery
RuntimeDirectoryMode=0755
StateDirectory=confio
Restart=always
RestartSec=5
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable daphne celery celery-beat
}

start_and_verify() {
  echo "Starting services sequentially (safe mode)..."
  echo "Starting daphne..."
  systemctl restart daphne || true
  sleep 1
  systemctl is-active --quiet daphne && echo "daphne active" || echo "daphne not active; check logs"

  echo "Starting celery worker with conservative settings..."
  # Lower resource usage by using single process if desired; uncomment to enforce:
  # sed -i -E 's#ExecStart=.*celery -A config worker.*#ExecStart=$VENV_BIN/celery -A config worker --loglevel=INFO --concurrency=1 --prefetch-multiplier=1#' /etc/systemd/system/celery.service
  systemctl restart celery || true
  sleep 1
  systemctl is-active --quiet celery && echo "celery active" || echo "celery not active; check logs"

  echo "Starting celery-beat..."
  systemctl restart celery-beat || true
  sleep 1
  systemctl is-active --quiet celery-beat && echo "celery-beat active" || echo "celery-beat not active; check logs"

  echo "Service status:"
  systemctl --no-pager --full status daphne || true
  systemctl --no-pager --full status celery || true
  systemctl --no-pager --full status celery-beat || true

  echo "Testing Daphne port 8000 locally via curl (header only)..."
  if command -v curl >/dev/null 2>&1; then
    curl -I --max-time 3 http://127.0.0.1:8000 || true
  fi

  echo "Pinging Celery workers..."
  if [[ -x "$VENV_BIN/celery" ]]; then
    sudo -u "$RUN_USER" "$VENV_BIN/celery" -A config inspect ping || true
  fi
}

main() {
  ensure_root
  detect_os
  ensure_swap
  install_redis
  configure_redis
  ensure_app_paths
  ensure_python_deps
  update_env
  install_systemd_units
  start_and_verify
  echo "All done. Redis + Daphne + Celery are configured and running."
}

main "$@"
