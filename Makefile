.PHONY: runserver migrate makemigrations shell test clean db-setup db-migrate db-reset collectstatic

# Virtual environment path
VENV_PATH = ./myvenv
PYTHON = $(VENV_PATH)/bin/python
PIP = $(VENV_PATH)/bin/pip

# Collect static files
collectstatic:
	$(PYTHON) manage.py collectstatic --noinput
	@echo "Static files collected successfully!"

# Run development server
runserver:
	$(PYTHON) manage.py runserver 0.0.0.0:8000

# Run migrations
migrate:
	$(PYTHON) manage.py migrate

# Create new migrations
makemigrations:
	$(PYTHON) manage.py makemigrations

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
	./myvenv/bin/python manage.py runserver 0.0.0.0:8000

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