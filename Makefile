.PHONY: runserver migrate makemigrations shell test clean

# Virtual environment path
VENV_PATH = /Users/julianmoon/Confio/myvenv
PYTHON = $(VENV_PATH)/bin/python
PIP = $(VENV_PATH)/bin/pip

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
	/Users/julianmoon/Confio/myvenv/bin/python manage.py runserver 0.0.0.0:8000 