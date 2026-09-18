from django.db import migrations


def repair_currency(apps, schema_editor):
    Ledger = apps.get_model('users', 'UnifiedTransactionTable')
    # Repair only the labels emitted by the former Koywe off-ramp shortcut.
    # QuerySet.update does not emit notifications, alter amounts/statuses,
    # revive hidden records, or initiate provider/blockchain operations.
    Ledger.objects.using(schema_editor.connection.alias).filter(
        transaction_type='ramp',
        token_type='USDC',
        ramp_transaction__provider='koywe',
        ramp_transaction__direction='off_ramp',
        ramp_transaction__destination='cusd_plus',
        ramp_transaction__final_amount__isnull=False,
    ).update(token_type='USDT')


class Migration(migrations.Migration):
    dependencies = [
        ('ramps', '0017_restore_unconverted_bsc_ramp_gross'),
        ('users', '0046_user_wallet_recovery_drive_ids'),
    ]
    operations = [migrations.RunPython(repair_currency, migrations.RunPython.noop)]
