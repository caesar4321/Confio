Systemd Deployment (Ubuntu EC2)
================================

Overview
--------
- Use systemd to run Daphne (ASGI), Celery worker, Celery Beat, and optionally Flower.
- Works on Ubuntu 20.04/22.04/24.04.

Prereqs
-------
- DNS pointed to your EC2 public IP (optional).
- SSH access as `ubuntu`.
- Code present at `/opt/confio` (aligns with prior `deploy-full-app.sh`).

Quick Start
----------
1) SSH into the instance:
   `ssh -i ~/.ssh/your-key.pem ubuntu@<EC2_PUBLIC_IP>`

2) Place project at `/opt/confio` (git clone, rsync, or scp):
   `sudo mkdir -p /opt/confio && sudo chown $USER:$USER /opt/confio && git clone <repo> /opt/confio` 
   or `rsync -avz ./ ubuntu@<EC2_PUBLIC_IP>:/opt/confio/`

3) Run the installer:
   `bash /opt/confio/scripts/install_systemd_ubuntu.sh`

4) Services on boot and auto-restart:
   - Installer enables and starts: `nginx`, `redis-server`, `postgresql`, `daphne`, `celery`, `celery-beat`
   - Adds Restart=always overrides for nginx/redis/postgresql

Service Files
------------
- `config/systemd/daphne.service`: serves Django via Daphne on `127.0.0.1:8000`.
- `config/systemd/celery.service`: Celery worker.
- `config/systemd/celery-beat.service`: Celery Beat scheduler.
- `config/systemd/flower.service`: Celery Flower monitoring (optional, port 5555).

Environment
-----------
- Systemd services read env from `/opt/confio/.env`.
- Defaults are created by the installer; review and set:
  - `SECRET_KEY`, `ALLOWED_HOSTS`
  - `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT=5432`
  - `DB_SSLMODE=require`, `DB_CONN_MAX_AGE=300`
  - `REDIS_URL`
  - `ALGORAND_NETWORK=mainnet`
  - `ALGORAND_ALGOD_ADDRESS=https://mainnet-api.4160.nodely.dev`
  - `ALGORAND_INDEXER_ADDRESS=https://mainnet-idx.4160.nodely.dev`
  - Required secrets (must be provided): `ALGORAND_SPONSOR_ADDRESS`, `ALGORAND_SPONSOR_MNEMONIC`, `ALGORAND_PAYMENT_APP_ID`

Nginx
-----
- Existing configs in `nginx/` proxy to `http://127.0.0.1:8000` which matches `daphne.service`.
- Copy your preferred file to `/etc/nginx/sites-available/confio` and symlink to `sites-enabled`:
  - `sudo cp nginx/nginx.conf /etc/nginx/sites-available/confio`
  - `sudo ln -sf /etc/nginx/sites-available/confio /etc/nginx/sites-enabled/confio`
  - `sudo nginx -t && sudo systemctl reload nginx`

Management
----------
- Reload units: `sudo systemctl daemon-reload`
- Enable on boot: `sudo systemctl enable daphne celery celery-beat`
- Start/Restart: `sudo systemctl restart daphne celery celery-beat`
- Logs: `sudo journalctl -u daphne -f`, `sudo journalctl -u celery -f`, `sudo journalctl -u celery-beat -f`

Notes
-----
- If your project path or user differs, edit the unit files or adjust `scripts/install_systemd_ubuntu.sh` before installing.
- Use Postgres in production, e.g. `DATABASE_URL=postgresql://user:pass@127.0.0.1:5432/confio`.
- For HTTPS, configure certbot on Nginx.
