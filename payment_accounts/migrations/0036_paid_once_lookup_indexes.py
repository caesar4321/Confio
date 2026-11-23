"""Indexes for the paid-once lookups (local_money.holding_payments): a QR's
or order's key in a journey's snapshot, and the QR a recipient row holds.
Hash indexes: a QR payload can be longer than a btree entry allows."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('payment_accounts', '0035_payment_intent_agent_source'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "CREATE INDEX IF NOT EXISTS infinia_journey_order_key_idx ON payment_accounts_infiniajourney "
                "USING hash (((destination_snapshot -> 'store_order') -> 'key'))",
                "CREATE INDEX IF NOT EXISTS infinia_journey_destination_id_idx ON payment_accounts_infiniajourney "
                "USING hash ((destination_snapshot -> 'destination_internal_id'))",
                "CREATE INDEX IF NOT EXISTS payout_destination_breb_qr_idx ON payment_accounts_payoutdestination "
                "USING hash (((provider_data -> 'breb_qr') -> 'payload'))",
                "CREATE INDEX IF NOT EXISTS payout_destination_qr_code_idx ON payment_accounts_payoutdestination "
                "USING hash ((details -> 'qrCode'))",
            ],
            reverse_sql=[
                'DROP INDEX IF EXISTS infinia_journey_order_key_idx',
                'DROP INDEX IF EXISTS infinia_journey_destination_id_idx',
                'DROP INDEX IF EXISTS payout_destination_breb_qr_idx',
                'DROP INDEX IF EXISTS payout_destination_qr_code_idx',
            ],
        ),
    ]
