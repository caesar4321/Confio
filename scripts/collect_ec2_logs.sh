#!/usr/bin/env bash
set -euo pipefail

# Collects Daphne/Celery statuses and logs from the EC2 instance specified in .env.
# Usage:
#   bash scripts/collect_ec2_logs.sh

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
ENV_FILE="$ROOT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: .env not found at $ENV_FILE" >&2
  exit 1
fi

# Read only required variables from .env without sourcing (handles spaces in other vars)
get_var() {
  local name="$1"
  # Print everything after the first '=' on the matching line
  awk -F= -v v="$name" '$1==v{print substr($0, index($0,$2))}' "$ENV_FILE" | tail -n1
}

EC2_IP=$(get_var EC2_IP)
EC2_USER=$(get_var EC2_USER)
EC2_KEY_PATH=$(get_var EC2_KEY_PATH)

if [[ -z "${EC2_IP:-}" || -z "${EC2_USER:-}" || -z "${EC2_KEY_PATH:-}" ]]; then
  echo "ERROR: Missing EC2_IP or EC2_USER or EC2_KEY_PATH in $ENV_FILE" >&2
  exit 1
fi

# Expand leading tilde and verify key exists
if [[ "${EC2_KEY_PATH:0:2}" == "~/" ]]; then
  EC2_KEY_PATH="$HOME/${EC2_KEY_PATH:2}"
fi
if [[ ! -f "$EC2_KEY_PATH" ]]; then
  echo "ERROR: EC2 key not found at $EC2_KEY_PATH" >&2
  exit 2
fi

TS=$(date +%Y%m%d_%H%M%S)
OUT_DIR="$ROOT_DIR/logs/remote/$TS"
mkdir -p "$OUT_DIR"

run_ssh() {
  ssh -o StrictHostKeyChecking=no -i "$EC2_KEY_PATH" "$EC2_USER@$EC2_IP" "$@"
}

echo "Collecting systemd status..."
run_ssh 'sudo systemctl --no-pager --full status daphne celery celery-beat || true' \
  | tee "$OUT_DIR/systemd_status.txt"

echo "Collecting daphne logs..."
run_ssh 'sudo journalctl -u daphne -b -n 400 --no-pager || true' \
  | tee "$OUT_DIR/daphne_journal.txt"

echo "Collecting celery logs..."
run_ssh 'sudo journalctl -u celery -b -n 400 --no-pager || true' \
  | tee "$OUT_DIR/celery_journal.txt"

echo "Collecting celery-beat logs..."
run_ssh 'sudo journalctl -u celery-beat -b -n 200 --no-pager || true' \
  | tee "$OUT_DIR/celery_beat_journal.txt"

echo "Collecting env summary (/opt/confio/.env exists + perms)..."
run_ssh 'bash -lc "ls -l /opt/confio/.env || echo /opt/confio/.env missing"' \
  | tee "$OUT_DIR/remote_env_summary.txt"

echo "Collecting local Redis/Postgres service status (if present)..."
run_ssh 'sudo systemctl --no-pager --full status redis redis6 postgresql || true' \
  | tee "$OUT_DIR/local_datastores_status.txt"

echo "Checking DB reachability (pg_isready against RDS from .env)..."
run_ssh 'bash -lc "if command -v pg_isready >/dev/null; then pg_isready -h database-1.chgioak6sjdz.eu-central-2.rds.amazonaws.com -p 5432 -d confio -U confio_app; else echo pg_isready not installed; fi"' \
  | tee "$OUT_DIR/db_pg_isready.txt"

echo
echo "Collected logs in: $OUT_DIR"
echo "Please share the files (or errors from them) for analysis."
