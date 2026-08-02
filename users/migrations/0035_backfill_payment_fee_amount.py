"""Record the fee on payment rows that predate the fee_amount field.

Both rails deduct the same 0.9% ceiling fee before crediting the merchant —
BSC in payments/bsc_flow.payment_fee_wei, Algorand in
blockchain/payment_transaction_builder (which sends `net_amount`, not the
gross). So every historical payment row credits the merchant with more than
they received, and the correction is the same arithmetic on both.

Only rows with no fee recorded are touched, so this is safe to re-run and
cannot disturb a row someone has already reasoned about.
"""
from decimal import Decimal

from django.db import migrations

FEE_BPS = 90
BPS = 10_000
MICRO = Decimal(10) ** 6


def backfill(apps, schema_editor):
    U = apps.get_model('users', 'UnifiedTransactionTable')
    rows = U.objects.filter(transaction_type='payment', fee_amount='')
    fixed = 0
    for row in rows.iterator():
        try:
            gross = Decimal(str(row.amount or 0))
        except Exception:  # noqa: BLE001 — a malformed row is not this migration's fight
            continue
        if gross <= 0:
            continue
        # Integer ceiling arithmetic in micro-units, matching both builders.
        micro = int(gross * MICRO)
        fee_micro = (micro * FEE_BPS + BPS - 1) // BPS
        fee = (Decimal(fee_micro) / MICRO).quantize(Decimal('0.000001'))
        row.fee_amount = format(fee.normalize(), 'f')
        row.save(update_fields=['fee_amount'])
        fixed += 1
    print(f"  recorded the fee on {fixed} historical payment row(s)")


def clear(apps, schema_editor):
    U = apps.get_model('users', 'UnifiedTransactionTable')
    U.objects.filter(transaction_type='payment').update(fee_amount='')


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0034_unified_fee_amount'),
    ]

    operations = [
        migrations.RunPython(backfill, clear),
    ]
