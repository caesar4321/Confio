"""
Celery beat schedules for blockchain tasks
Add these to your main celery configuration
"""
from celery.schedules import crontab

BLOCKCHAIN_CELERY_BEAT_SCHEDULE = {
    # Update user address cache every minute
    'update-user-address-cache': {
        'task': 'blockchain.tasks.update_address_cache',
        'schedule': 60.0,  # Every minute
    },

    # DISABLED: Refresh stale balances every 5 minutes
    # REASON: Redundant - on-demand balance fetching already refreshes stale balances when users open app
    # SAVINGS: ~7,200 API calls/day eliminated
    # 'refresh-stale-balances': {
    #     'task': 'blockchain.tasks.refresh_stale_balances',
    #     'schedule': 300.0,  # Every 5 minutes
    # },

    # DISABLED: Full balance reconciliation every hour
    # REASON: Redundant - on-demand fetching has 5-minute stale threshold built-in
    # SAVINGS: ~54,480 API calls/day eliminated (after optimization)
    # 'reconcile-all-balances': {
    #     'task': 'blockchain.tasks.reconcile_all_balances',
    #     'schedule': crontab(minute=0),  # Every hour at :00
    # },

    # Removed cleanup of old Sui events (no event storage)
    
    # Indexer inbound deposit scan (USDC, cUSD, CONFIO)
    'scan-inbound-deposits': {
        'task': 'blockchain.scan_inbound_deposits',
        'schedule': 30.0,  # Every 30 seconds
    },
    
    # Outbound confirmation scan (payments, sends)
    'scan-outbound-confirmations': {
        'task': 'blockchain.scan_outbound_confirmations',
        'schedule': 10.0,  # Every 10 seconds
    },
    
    # Removed Sui epoch tracking
}

# To use in your main celery.py:
# from blockchain.celery_schedules import BLOCKCHAIN_CELERY_BEAT_SCHEDULE
# app.conf.beat_schedule.update(BLOCKCHAIN_CELERY_BEAT_SCHEDULE)
