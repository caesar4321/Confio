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

app.conf.beat_schedule.setdefault('users-rollup-funnel-events', {
    'task': 'users.rollup_funnel_events',
    'schedule': crontab(hour=3, minute=30),
})

# Keep Koywe ramp limits warm so rampAvailability never computes them inline
# (the off-ramp estimate needs several sequential preview quotes).
app.conf.beat_schedule.setdefault('ramps-refresh-koywe-limits', {
    'task': 'ramps.refresh_koywe_ramp_limits',
    'schedule': crontab(minute=7),
})

# A payout whose confirmer exhausted its retries before the chain answered
# has nothing else watching it: the wage paid, the item stays SUBMITTED, the
# run stays PARTIAL, and no ledger row or notification is ever written.
app.conf.beat_schedule.setdefault('payroll-reconcile-stranded-bsc', {
    'task': 'payroll.reconcile_stranded_bsc_payroll',
    'schedule': crontab(minute='*/15'),
})

# Same gap on the invoice side: a batch that outlived the request which
# broadcast it leaves the merchant paid and the invoice pending, and the
# signed-batch reconciler does not look at 'sent' rows.
app.conf.beat_schedule.setdefault('payments-reconcile-stranded-bsc', {
    'task': 'payments.reconcile_stranded_bsc_payments',
    'schedule': crontab(minute='*/15'),
})

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
