from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from celery.schedules import crontab

# set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('Duende')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Import blockchain schedules
try:
    from blockchain.celery_schedules import BLOCKCHAIN_CELERY_BEAT_SCHEDULE
    app.conf.beat_schedule.update(BLOCKCHAIN_CELERY_BEAT_SCHEDULE)
except ImportError:
    pass  # Blockchain app not yet installed

# Ensure DB connections are properly managed around every Celery task
try:
    from celery import signals
    from django.db import close_old_connections, connections

    @signals.task_prerun.connect
    def _celery_prerun_close_stale_conns(*args, **kwargs):
        # Drop any stale/dangling DB connections before the task starts
        close_old_connections()

    @signals.task_postrun.connect
    def _celery_postrun_close_all_conns(*args, **kwargs):
        # Aggressively close all DB connections after each task to avoid leaks
        for conn in connections.all():
            try:
                conn.close()
            except Exception:
                pass
except Exception:
    # If imports fail during early startup, skip signals (app will still run)
    pass
