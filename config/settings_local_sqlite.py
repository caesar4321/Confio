from .settings import *  # noqa
import os

# Override database to use a local SQLite file for clean rebuild/tests
BASE_DIR = Path(__file__).resolve().parent.parent
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# Make local checks easy
DEBUG = True
ALLOWED_HOSTS = ['*']

