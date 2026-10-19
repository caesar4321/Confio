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

# Tu mes "Tu ahorro ganó": one cUSD+ price + holdings snapshot per UTC day.
# Hourly from 00:15 to 06:15: the first run that succeeds writes the day,
# later runs see it exists, so one RPC blip no longer loses the day.
app.conf.beat_schedule.setdefault('cusd-plus-snapshot-savings-daily', {
    'task': 'cusd_plus.snapshot_savings_daily',
    'schedule': crontab(hour='0-6', minute=15),
})

# Tu mes "Tu dólar te protegió": keep one Binance P2P rate per day (the 1st
# of the month is the baseline where there is no Confío on-ramp).
# Crypto & metals prices from PancakeSwap (cusd_plus/crypto_prices.py): the
# displayed price, 24h change and sparkline. Cheap (one quote per token).
# Heartbeat in the relay's Redis: sponsor-signing ops commands refuse to
# broadcast unless they can read it (they must share the sponsor nonce lock).
app.conf.beat_schedule.setdefault('relay-cache-heartbeat', {
    'task': 'cusd_plus.relay_cache_heartbeat',
    'schedule': crontab(minute='*'),
})

app.conf.beat_schedule.setdefault('crypto-snapshot-prices', {
    'task': 'cusd_plus.snapshot_crypto_prices',
    'schedule': crontab(minute='*/15'),
})

app.conf.beat_schedule.setdefault('exchange-rates-snapshot-daily-rates', {
    'task': 'exchange_rates.snapshot_daily_rates',
    'schedule': crontab(minute=20),
})

app.conf.beat_schedule.setdefault('security-purge-face-check-evidence', {
    'task': 'security.purge_face_check_evidence',
    'schedule': crontab(hour=4, minute=20),
})

app.conf.beat_schedule.setdefault('security-reconcile-face-blocklist', {
    'task': 'security.reconcile_face_blocklist',
    'schedule': crontab(minute=17),
})

app.conf.beat_schedule.setdefault('security-retry-pending-same-face', {
    'task': 'security.retry_pending_same_face',
    'schedule': crontab(minute=41),
})

app.conf.beat_schedule.setdefault('users-rollup-funnel-events', {
    'task': 'users.rollup_funnel_events',
    'schedule': crontab(hour=3, minute=30),
})

# Precompute the finite legacy-wallet safety cohort away from authentication.
# Backend is deployed before mobile, so these rows are warm when capable
# clients begin requesting self-heal grants.
app.conf.beat_schedule.setdefault('users-wallet-reenrollment-assessments', {
    'task': 'users.queue_wallet_reenrollment_assessments',
    # The production rollout command warms the complete finite cohort. This
    # daily pass only retries transient inspection failures; scanning every
    # legacy row once a minute after prewarm created permanent O(N) DB load.
    'schedule': crontab(hour=3, minute=45),
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
# Comunidad shares tapped before the activity settled: published as soon
# as it does (a stock trade finalizes in seconds).
app.conf.beat_schedule.setdefault('inbox-resolve-activity-share-intents', {
    'task': 'inbox.tasks.resolve_activity_share_intents_task',
    'schedule': 15.0,
})

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

# The update pop-up follows the stores: latest_version only moves up once
# the App Store or a 100% Play production rollout actually serves the build.
app.conf.beat_schedule.setdefault('security-sync-store-versions', {
    'task': 'security.sync_store_versions',
    'schedule': crontab(minute=33),
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

    # With DB_POOL, a pool opened in the prefork parent must not be inherited:
    # its sockets and worker threads would be shared across processes. Close
    # pools in the parent before it forks; in each child, forget anything
    # inherited without closing it (closing would hang up the parent's sockets).
    @signals.worker_init.connect
    def _celery_parent_close_db_pools(*args, **kwargs):
        for conn in connections.all():
            try:
                if getattr(conn, 'pool', None):
                    conn.close_pool()
                else:
                    conn.close()
            except Exception:
                pass

    @signals.worker_process_init.connect
    def _celery_child_drop_inherited_db_state(*args, **kwargs):
        for conn in connections.all(initialized_only=True):
            conn.connection = None
            getattr(type(conn), '_connection_pools', {}).clear()
except Exception:
    # If imports fail during early startup, skip signals (app will still run)
    pass
