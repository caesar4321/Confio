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
  - Required secrets (must be provided): `ALGORAND_SPONSOR_ADDRESS`, `USE_KMS_SIGNING=True`, `KMS_KEY_ALIAS`, `KMS_REGION`, `ALGORAND_PAYMENT_APP_ID`

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

Routine Deploy
--------------
Run these in order. Installing dependencies BEFORE restarting is not optional:
`git pull` can introduce a new entry in `INSTALLED_APPS` whose package is not
yet installed. The running process keeps serving from memory, so nothing looks
wrong until the next restart fails to boot. A local `manage.py check` will not
catch it either, because the local virtualenv already has the dependency.

```bash
cd /opt/confio
git pull --ff-only
myvenv/bin/pip install -r requirements.txt
myvenv/bin/python manage.py check          # fails here rather than mid-restart
myvenv/bin/python manage.py showmigrations --plan | grep '^\[ \]'   # review first
myvenv/bin/python manage.py migrate --noinput
sudo systemctl restart daphne celery celery-beat
systemctl is-active daphne celery celery-beat
```

Verify afterwards that the deployed commit is the one you pushed
(`git log --oneline -1`) and that nothing is erroring:
`sudo journalctl -u daphne --since '5 min ago' -p err --no-pager`.

The virtualenv is `/opt/confio/myvenv`, matching the `myvenv/bin/python`
convention in CLAUDE.md. There is no `/opt/confio/venv`.

Wallet Reenrollment Release Gate
--------------------------------
When a backend release includes the legacy wallet reenrollment assessment
migration, deploy the backend before the mobile client. Apply migrations,
restart every process that loads Django or the Celery schedule, and warm the
finite legacy cohort:

```bash
cd /opt/confio
sudo /opt/confio/myvenv/bin/python manage.py migrate --noinput
sudo systemctl restart daphne celery celery-beat
sudo /opt/confio/myvenv/bin/python manage.py precompute_wallet_reenrollment
```

The precompute command scans candidates synchronously and exits non-zero if any
assessment remains incomplete. Repeat it after resolving transient Algod,
Indexer, BSC RPC, or database failures. Release the new iOS/Android build only
when the final line reports `remaining=0`. The daily Celery Beat task retries
future transient failures; it is not a substitute for this release gate.

Assessment version 2 retains compatible version-1 `sponsor_only_empty_wallet`
eligible proofs with matching wallet addresses and valid snapshot/funding data.
Those accounts do not need a manual reset or a forced rescan after deployment.
Version-1 refusals are not reused: the precompute command reassesses them under
the new eligibility rules. Compatibility does not rewrite stored proofs or
bypass completion checks; replacement still rechecks chain state and pending
database activity immediately before retiring the old wallet address.

Notes
-----
- If your project path or user differs, edit the unit files or adjust `scripts/install_systemd_ubuntu.sh` before installing.
- Use Postgres in production, e.g. `DATABASE_URL=postgresql://user:pass@127.0.0.1:5432/confio`.
- For HTTPS, configure certbot on Nginx.
