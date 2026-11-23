"""The paid-once check looks only at the order key now (no fixed-amount QR
was ever paid before QRs carried it): the indexes 0036 added for the older
lookups are dropped. infinia_journey_order_key_idx stays."""
from django.db import migrations

DROPPED = (
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
    atomic = False   # DROP/CREATE INDEX CONCURRENTLY cannot run in a transaction

    dependencies = [
        ('payment_accounts', '0036_paid_once_lookup_indexes'),
    ]

    operations = [
        migrations.RunSQL(
            sql=f'DROP INDEX CONCURRENTLY IF EXISTS {name}',
            reverse_sql=f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} USING hash ({expression})',
        )
        for name, table, expression in DROPPED
    ]
