#!/usr/bin/env bash
set -euo pipefail

info() { echo "[pgbouncer-build] $*"; }

info "Installing build dependencies..."
if command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y gcc make libevent-devel openssl-devel c-ares-devel pkgconfig wget tar
elif command -v yum >/dev/null 2>&1; then
  sudo yum groupinstall -y "Development Tools" || true
  sudo yum install -y libevent-devel openssl-devel c-ares-devel pkgconfig wget tar
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y build-essential libevent-dev libssl-dev libc-ares-dev pkg-config wget tar
else
  info "No supported package manager found"; exit 1
fi

cd /tmp
URL=https://github.com/pgbouncer/pgbouncer/releases/download/1.22.1/pgbouncer-1.22.1.tar.gz
info "Downloading PgBouncer from $URL"
wget -qO pgbouncer.tar.gz "$URL"
tar xzf pgbouncer.tar.gz
cd pgbouncer-*
info "Configuring..."
./configure --prefix=/usr/local --with-openssl --with-cares
info "Building..."
make -j"$(nproc || echo 2)"
sudo make install
/usr/local/bin/pgbouncer -V || true

info "Creating pgbouncer user and directories..."
id -u pgbouncer >/dev/null 2>&1 || sudo useradd -r -s /sbin/nologin pgbouncer || true
sudo mkdir -p /etc/pgbouncer /var/log/pgbouncer
sudo chown -R pgbouncer:pgbouncer /etc/pgbouncer /var/log/pgbouncer || true

info "Installing systemd unit..."
sudo tee /etc/systemd/system/pgbouncer.service >/dev/null <<UNIT
[Unit]
Description=PgBouncer Connection Pooler
After=network.target

[Service]
Type=simple
User=pgbouncer
Group=pgbouncer
ExecStart=/usr/local/bin/pgbouncer /etc/pgbouncer/pgbouncer.ini
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
