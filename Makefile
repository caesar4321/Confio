.PHONY: runserver runserver-dev runserver-wsgi migrate makemigrations migrate-fake-initial migrate-fake-contrib migrate-reset-fake migrate-reset-history reset-migrations rebuild-clean shell test clean db-setup db-migrate db-reset collectstatic celery-worker celery-beat

# Virtual environment path
VENV_PATH = ./myvenv
PYTHON = $(VENV_PATH)/bin/python
PIP = $(VENV_PATH)/bin/pip

# Collect static files
collectstatic:
	$(PYTHON) manage.py collectstatic --noinput
	@echo "Static files collected successfully!"

# Run development server with Django Channels (ASGI)
runserver:
	DEBUG=True $(PYTHON) -m daphne -b 0.0.0.0 -p 8000 config.asgi:application

# Run Daphne with HTTP/2 + TLS (dev)
# Requires: pip install "twisted[tls,http2]" service-identity
# Usage: make runserver-h2 DEV_SSL_CERT=dev.crt DEV_SSL_KEY=dev.key DEV_PORT=8443
runserver-h2:
	@if [ -z "$(DEV_SSL_CERT)" ] || [ -z "$(DEV_SSL_KEY)" ]; then \
		echo "DEV_SSL_CERT/DEV_SSL_KEY not set. Usage: make runserver-h2 DEV_SSL_CERT=dev.crt DEV_SSL_KEY=dev.key [DEV_PORT=8443]"; \
		exit 1; \
	fi
	DEBUG=True $(PYTHON) -m daphne -b 0.0.0.0 -p $${DEV_PORT:-8443} -e "ssl:port=$${DEV_PORT:-8443}:privateKey=$(DEV_SSL_KEY):certificate=$(DEV_SSL_CERT)" config.asgi:application
	@echo "Daphne running with HTTP/2 + TLS on port $${DEV_PORT:-8443}"

# Run Django development server with ASGI support (alternative)
runserver-dev:
	DEBUG=True DJANGO_SETTINGS_MODULE=config.settings $(PYTHON) -m uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --reload

# Run standard Django server (WSGI) - for comparison/fallback
runserver-wsgi:
	DEBUG=True $(PYTHON) manage.py runserver 0.0.0.0:8000

# Run migrations
migrate:
	$(PYTHON) manage.py migrate

# Run migrations and mark existing tables as applied (no data loss)
migrate-fake-initial:
	$(PYTHON) manage.py migrate --fake-initial

# Mark contrib apps as fully applied (no-op SQL), useful after history reset
migrate-fake-contrib:
	$(PYTHON) manage.py migrate contenttypes --fake
	$(PYTHON) manage.py migrate auth --fake
	$(PYTHON) manage.py migrate sessions --fake
	$(PYTHON) manage.py migrate admin --fake

# Force-reset migration history (fake-unapply to zero), then mark initial as applied.
# WARNING: This does NOT drop tables; it only rewrites migration history.
migrate-reset-fake:
	@APPS="users achievements security telegram_verification sms_verification send payments p2p_exchange exchange_rates conversion usdc_transactions presale notifications blockchain"; \
	for app in $$APPS; do \
		echo "[fake-unapply] $$app -> zero"; \
		$(PYTHON) manage.py migrate $$app zero --fake || exit 1; \
	done; \
	echo "[apply] migrate --fake-initial"; \
	$(PYTHON) manage.py migrate --fake-initial

# Reset migration history rows in django_migrations (no table drops), then mark initial applied
migrate-reset-history:
	$(PYTHON) manage.py reset_migration_history --noinput --apps "admin,auth,contenttypes,sessions,users,achievements,security,telegram_verification,sms_verification,send,payments,p2p_exchange,exchange_rates,conversion,usdc_transactions,presale,notifications,blockchain"
	$(PYTHON) manage.py migrate --fake-initial

# Create new migrations
makemigrations:
	$(PYTHON) manage.py makemigrations

# Remove all migration files (keep __init__.py) and regenerate 0001s
reset-migrations:
	./scripts/reset_migrations.sh
	$(PYTHON) manage.py makemigrations

# Reset migrations, then apply with --fake-initial (DB must be intact)
rebuild-clean:
	./scripts/reset_migrations.sh
	$(PYTHON) manage.py makemigrations
	$(PYTHON) manage.py migrate --fake-initial

# Open Django shell
shell:
	$(PYTHON) manage.py shell

# Run tests
test:
	$(PYTHON) manage.py test

# Clean up Python cache files
clean:
	find . -type d -name "__pycache__" -exec rm -r {} +
	find . -type f -name "*.pyc" -delete

# Install dependencies
install:
	$(PIP) install -r requirements.txt

# Create superuser
createsuperuser:
	$(PYTHON) manage.py createsuperuser

# Run with full path (alternative to runserver)
run:
	DEBUG=True ./myvenv/bin/python -m daphne -b 0.0.0.0 -p 8000 config.asgi:application

# Celery worker
celery-worker:
	$(VENV_PATH)/bin/celery -A config worker -l info

# Celery beat (scheduler)
celery-beat:
	$(VENV_PATH)/bin/celery -A config beat -l info

# Strict deploy targets
deploy-cusd:
	ALGORAND_NETWORK=$${ALGORAND_NETWORK:-testnet} \
	ALGORAND_ALGOD_ADDRESS=$${ALGORAND_ALGOD_ADDRESS} \
	ALGORAND_ALGOD_TOKEN=$${ALGORAND_ALGOD_TOKEN} \
	ALGORAND_SPONSOR_MNEMONIC=$${ALGORAND_SPONSOR_MNEMONIC} \
	ALGORAND_SPONSOR_ADDRESS=$${ALGORAND_SPONSOR_ADDRESS} \
	./myvenv/bin/python contracts/cusd/deploy_cusd.py

deploy-payment:
	ALGORAND_NETWORK=$${ALGORAND_NETWORK:-testnet} \
	ALGORAND_ALGOD_ADDRESS=$${ALGORAND_ALGOD_ADDRESS} \
	ALGORAND_ALGOD_TOKEN=$${ALGORAND_ALGOD_TOKEN} \
	ALGORAND_ADMIN_MNEMONIC=$${ALGORAND_ADMIN_MNEMONIC} \
	ALGORAND_SPONSOR_ADDRESS=$${ALGORAND_SPONSOR_ADDRESS} \
	ALGORAND_CUSD_ASSET_ID=$${ALGORAND_CUSD_ASSET_ID} \
	ALGORAND_CONFIO_ASSET_ID=$${ALGORAND_CONFIO_ASSET_ID} \
	./myvenv/bin/python contracts/payment/deploy_payment.py

deploy-invite-send:
	ALGORAND_NETWORK=$${ALGORAND_NETWORK:-testnet} \
	ALGORAND_ALGOD_ADDRESS=$${ALGORAND_ALGOD_ADDRESS} \
	ALGORAND_ALGOD_TOKEN=$${ALGORAND_ALGOD_TOKEN} \
	ALGORAND_DEPLOYER_MNEMONIC=$${ALGORAND_ADMIN_MNEMONIC} \
	ALGORAND_SPONSOR_ADDRESS=$${ALGORAND_SPONSOR_ADDRESS} \
	ALGORAND_CUSD_ASSET_ID=$${ALGORAND_CUSD_ASSET_ID} \
	ALGORAND_CONFIO_ASSET_ID=$${ALGORAND_CONFIO_ASSET_ID} \
	./myvenv/bin/python contracts/invite_send/deploy_invite_send.py

# Database setup
db-setup:
	@echo "Creating PostgreSQL user and database..."
	@psql postgres -c "CREATE USER confio WITH PASSWORD 'Kj8#mP2$vL9nQ5@xR3&tY7*wZ4!cB6';" || true
	@psql postgres -c "CREATE DATABASE confio OWNER confio;" || true
	@echo "Database setup complete!"

# Run migrations
db-migrate:
	@echo "Running database migrations..."
	@$(PYTHON) manage.py migrate
	@echo "Migrations complete!"

# Reset database (WARNING: This will delete all data)
db-reset:
	@echo "Resetting database..."
	@psql postgres -c "DROP DATABASE IF EXISTS confio;"
	@psql postgres -c "DROP USER IF EXISTS confio;"
	@make db-setup
	@make db-migrate
	@echo "Database reset complete!" 
