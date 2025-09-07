"""
Celery beat schedules for blockchain tasks
Add these to your main celery configuration
"""
from celery.schedules import crontab

BLOCKCHAIN_CELERY_BEAT_SCHEDULE = {
    # Update user address cache every 3 minutes (reduced from 1 minute)
    'update-user-address-cache': {
        'task': 'blockchain.tasks.update_address_cache',
        'schedule': 180.0,  # Every 3 minutes
    },
    
    # Refresh stale balances every 10 minutes (reduced from 5 minutes)
    'refresh-stale-balances': {
        'task': 'blockchain.tasks.refresh_stale_balances',
        'schedule': 600.0,  # Every 10 minutes
    },
    
    # Full balance reconciliation every hour
    'reconcile-all-balances': {
        'task': 'blockchain.tasks.reconcile_all_balances',
        'schedule': crontab(minute=0),  # Every hour at :00
    },
    
    # Removed cleanup of old Sui events (no event storage)
    
    # Indexer inbound deposit scan (USDC, cUSD, CONFIO) - reduced from 30s to 2min
    'scan-inbound-deposits': {
        'task': 'blockchain.scan_inbound_deposits',
        'schedule': 120.0,  # Every 2 minutes
    },
    
    # Outbound confirmation scan (payments, sends) - reduced from 10s to 30s
    'scan-outbound-confirmations': {
        'task': 'blockchain.scan_outbound_confirmations',
        'schedule': 30.0,  # Every 30 seconds
    },
    
    # Removed Sui epoch tracking
}

# To use in your main celery.py:
# from blockchain.celery_schedules import BLOCKCHAIN_CELERY_BEAT_SCHEDULE
# app.conf.beat_schedule.update(BLOCKCHAIN_CELERY_BEAT_SCHEDULE)
