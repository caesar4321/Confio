"""Retire this app's models.

BnbAutoConvert is DROPPED for real (0 rows; its concept now lives as
blockchain.PendingAutoSwap asset_type='BNB', alongside its ALGO/USDC twin).

SponsoredBatch only leaves this app's STATE — the table and its 8 rows stay
exactly where they are on disk and are adopted by blockchain.0007, which
then renames them. A plain DeleteModel here would drop the ledger.
"""
from django.db import migrations


def refuse_if_bnb_rows_exist(apps, schema_editor):
    """Prod was verified empty by hand, but a comment is not a guard.

    Any other environment (a dev DB, a restored snapshot, a late write from an
    old worker) could hold rows, and the DeleteModel below would discard them
    silently instead of carrying them over as PendingAutoSwap(asset_type='BNB').
    Fail loudly so a human migrates them.
    """
    Bnb = apps.get_model('cusd_plus', 'BnbAutoConvert')
    n = Bnb.objects.count()
    if n:
        raise RuntimeError(
            f'{n} BnbAutoConvert row(s) present. This migration drops the table; '
            "carry them over as blockchain.PendingAutoSwap(asset_type='BNB') "
            'first, then re-run.'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('cusd_plus', '0012_delete_cusdplusconversion'),
    ]

    operations = [
        # Real: the concept moved to PendingAutoSwap. Guarded, not assumed.
        migrations.RunPython(refuse_if_bnb_rows_exist, migrations.RunPython.noop),
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
