#!/usr/bin/env bash
set -euo pipefail

info() { echo "[pgbouncer-setup] $*"; }

info "Detecting package manager..."
if command -v dnf >/dev/null 2>&1; then PM=dnf;
elif command -v yum >/dev/null 2>&1; then PM=yum;
elif command -v apt-get >/dev/null 2>&1; then PM=apt;
else info "No supported pkg mgr"; exit 1; fi

info "Installing PgBouncer if needed..."
if ! command -v pgbouncer >/dev/null 2>&1; then
  case "$PM" in
    dnf)
      # Try native repo
      sudo dnf install -y pgbouncer || {
        # Add PGDG repo for EL9 and retry
        sudo dnf install -y 'dnf-command(config-manager)' || true
        sudo dnf -y install https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm || true
        sudo dnf -y install pgbouncer || {
          # Fall back to EL8 repo
          sudo dnf -y remove pgdg-redhat-repo || true
          sudo dnf -y install https://download.postgresql.org/pub/repos/yum/reporpms/EL-8-x86_64/pgdg-redhat-repo-latest.noarch.rpm || true
          sudo dnf -y install pgbouncer || true
        }
      }
      ;;
    yum)
      sudo yum install -y pgbouncer || {
        # Try PGDG EL7 repo
        sudo yum -y install https://download.postgresql.org/pub/repos/yum/reporpms/EL-7-x86_64/pgdg-redhat-repo-latest.noarch.rpm || true
        sudo yum -y install pgbouncer || true
      }
      ;;
    apt)
      sudo apt-get update -y && sudo apt-get install -y pgbouncer ;;
  esac
fi
pgbouncer -V || true

info "Reading DB vars from /opt/confio/.env..."
DBH=$(awk -F= '/^DB_HOST=/{print substr($0,index($0,$2))}' /opt/confio/.env)
DBP=$(awk -F= '/^DB_PORT=/{print substr($0,index($0,$2))}' /opt/confio/.env)
DBN=$(awk -F= '/^DB_NAME=/{print substr($0,index($0,$2))}' /opt/confio/.env)
DBU=$(awk -F= '/^DB_USER=/{print substr($0,index($0,$2))}' /opt/confio/.env)
DBPW=$(awk -F= '/^DB_PASSWORD=/{print substr($0,index($0,$2))}' /opt/confio/.env)
DBP=${DBP:-5432}
info "DB: host=$DBH port=$DBP name=$DBN user=$DBU"

info "Writing /etc/pgbouncer/pgbouncer.ini and userlist.txt..."
sudo mkdir -p /etc/pgbouncer
sudo tee /etc/pgbouncer/pgbouncer.ini >/dev/null <<INI
[databases]
confio = host=${DBH} port=${DBP} dbname=${DBN} user=${DBU} sslmode=require

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
pool_mode = transaction
server_reset_query = DISCARD ALL
server_connect_timeout = 5
server_login_retry = 5
query_timeout = 0
query_wait_timeout = 15
max_client_conn = 1000
default_pool_size = 50
reserve_pool_size = 10
auth_type = plain
auth_file = /etc/pgbouncer/userlist.txt
ignore_startup_parameters = extra_float_digits,options
log_connections = 1
log_disconnections = 1
INI

echo "\"${DBU}\" \"${DBPW}\"" | sudo tee /etc/pgbouncer/userlist.txt >/dev/null
sudo chown -R pgbouncer:pgbouncer /etc/pgbouncer || true
sudo chmod 600 /etc/pgbouncer/userlist.txt || true

info "Enabling and starting PgBouncer..."
sudo systemctl enable pgbouncer || true
sudo systemctl restart pgbouncer
sudo systemctl --no-pager --full status pgbouncer || true

info "Testing PgBouncer connectivity..."
PGPASSWORD="${DBPW}" psql -h 127.0.0.1 -p 6432 -U "${DBU}" -d "${DBN}" -tA -c "select 'pgbouncer_ok'::text;" | sed -n '1,2p' || true

info "Switching Django to use PgBouncer (127.0.0.1:6432, SSL disable to PgBouncer)..."
sudo cp /opt/confio/.env /opt/confio/.env.backup_$(date +%Y%m%d%H%M%S) || true
sudo sed -i -E "s#^DB_HOST=.*#DB_HOST=127.0.0.1#" /opt/confio/.env
if grep -q '^DB_PORT=' /opt/confio/.env; then sudo sed -i -E "s#^DB_PORT=.*#DB_PORT=6432#" /opt/confio/.env; else echo DB_PORT=6432 | sudo tee -a /opt/confio/.env >/dev/null; fi
if grep -q '^DB_SSLMODE=' /opt/confio/.env; then sudo sed -i -E "s#^DB_SSLMODE=.*#DB_SSLMODE=disable#" /opt/confio/.env; else echo DB_SSLMODE=disable | sudo tee -a /opt/confio/.env >/dev/null; fi

info "Restarting services..."
sudo systemctl restart daphne celery celery-beat
sudo systemctl --no-pager --full status daphne || true

info "Final pg_isready via 127.0.0.1:6432"
pg_isready -h 127.0.0.1 -p 6432 -d "$DBN" -U "$DBU" || true
