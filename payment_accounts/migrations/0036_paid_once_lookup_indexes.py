"""Indexes for the paid-once lookups (local_money.holding_payments): a QR's
or order's key in a journey's snapshot, the recipient a snapshot names, and
the QR a recipient row holds. Each expression is the one Django emits for
those filters (`#>` for a nested key, `->` for a top-level one). Hash
indexes: a QR payload can be longer than a btree entry allows. Built
CONCURRENTLY so sends and recipient writes never wait on the build; a
build cut short leaves an invalid index of that name, so each is dropped
first (this migration is not recorded until every index is built)."""
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
    ('money_flow_local_destination_idx', 'payment_accounts_moneyflow',
     "(metadata -> 'local_destination_id')"),
)


class Migration(migrations.Migration):
    atomic = False   # CREATE INDEX CONCURRENTLY cannot run in a transaction

    dependencies = [
        ('payment_accounts', '0035_payment_intent_agent_source'),
    ]

    operations = [
        operation
        for name, table, expression in INDEXES
        for operation in (
            migrations.RunSQL(sql=f'DROP INDEX CONCURRENTLY IF EXISTS {name}', reverse_sql=migrations.RunSQL.noop),
            migrations.RunSQL(
                sql=f'CREATE INDEX CONCURRENTLY {name} ON {table} USING hash ({expression})',
                reverse_sql=f'DROP INDEX CONCURRENTLY IF EXISTS {name}',
            ),
        )
    ]
