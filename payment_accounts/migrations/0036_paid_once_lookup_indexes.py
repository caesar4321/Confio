"""Indexes for the paid-once lookups (local_money.holding_payments): a QR's
or order's key in a journey's snapshot, the recipient a snapshot names, and
the QR a recipient row holds. Each expression is the one Django emits for
those filters (`#>` for a nested key, `->` for a top-level one). Hash
indexes: a QR payload can be longer than a btree entry allows. Built
CONCURRENTLY so sends and recipient writes never wait on the build."""
from django.db import migrations

INDEXES = (
    ('infinia_journey_order_key_idx', 'payment_accounts_infiniajourney',
     "(destination_snapshot #> '{store_order,key}')"),
    ('infinia_journey_destination_id_idx', 'payment_accounts_infiniajourney',
     "(destination_snapshot -> 'destination_internal_id')"),
    ('payout_destination_breb_qr_idx', 'payment_accounts_payoutdestination',
     "(provider_data #> '{breb_qr,payload}')"),
    ('payout_destination_qr_code_idx', 'payment_accounts_payoutdestination',
     "(details -> 'qrCode')"),
)


class Migration(migrations.Migration):
    atomic = False   # CREATE INDEX CONCURRENTLY cannot run in a transaction

    dependencies = [
        ('payment_accounts', '0035_payment_intent_agent_source'),
    ]

    operations = [
        migrations.RunSQL(
            sql=f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} USING hash ({expression})',
            reverse_sql=f'DROP INDEX CONCURRENTLY IF EXISTS {name}',
        )
        for name, table, expression in INDEXES
    ]
