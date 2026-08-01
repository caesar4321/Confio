"""Retire this app's models.

BnbAutoConvert is DROPPED for real (0 rows; its concept now lives as
blockchain.PendingAutoSwap asset_type='BNB', alongside its ALGO/USDC twin).

SponsoredBatch only leaves this app's STATE — the table and its 8 rows stay
exactly where they are on disk and are adopted by blockchain.0007, which
then renames them. A plain DeleteModel here would drop the ledger.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('cusd_plus', '0012_delete_cusdplusconversion'),
    ]

    operations = [
        # Real: the table is empty and the concept moved to PendingAutoSwap.
        migrations.DeleteModel(name='BnbAutoConvert'),
        # State only: hand the table over without touching it.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name='sponsoredbatch', name='user'),
                migrations.DeleteModel(name='SponsoredBatch'),
            ],
            database_operations=[],
        ),
    ]
