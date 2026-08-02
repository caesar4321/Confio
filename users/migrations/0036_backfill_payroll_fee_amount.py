"""Record gross + fee on payroll rows written before fee_amount existed.

Those rows stored net_amount for BOTH sides, so a business's own history
understated what each run cost them by the fee on every wage. PayrollItem has
carried gross_amount and net_amount all along, so the correction is exact —
no arithmetic assumption, unlike the payments backfill which had to recompute
the rate.

Only rows with no fee recorded are touched, so this is safe to re-run.
"""
from decimal import Decimal

from django.db import migrations


def backfill(apps, schema_editor):
    U = apps.get_model('users', 'UnifiedTransactionTable')
    fixed = skipped = 0
    rows = U.objects.filter(transaction_type='payroll', fee_amount='')
    for row in rows.select_related('payroll_item').iterator():
        item = row.payroll_item
        if item is None:
            skipped += 1
            continue
        gross = item.gross_amount
        # What the employee actually received: the settled figure once the
        # confirmer has decoded PaidOut, else the nominal net.
        received = getattr(item, 'settled_amount', None)
        if received is None:
            received = item.net_amount
        if gross is None or received is None:
            skipped += 1
            continue
        fee = Decimal(str(gross)) - Decimal(str(received))
        if fee < 0:
            # Never invent a negative credit; leave the row alone and say so.
            print(f"  payroll row {row.id}: received exceeds gross — left untouched")
            skipped += 1
            continue
        row.amount = format(Decimal(str(gross)).normalize(), 'f')
        row.fee_amount = ('' if fee == 0
                          else format(fee.quantize(Decimal('0.000001')).normalize(), 'f'))
        row.save(update_fields=['amount', 'fee_amount'])
        fixed += 1
    print(f"  payroll rows corrected to gross+fee: {fixed} (skipped {skipped})")


def clear(apps, schema_editor):
    U = apps.get_model('users', 'UnifiedTransactionTable')
    U.objects.filter(transaction_type='payroll').update(fee_amount='')


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0035_backfill_payment_fee_amount'),
    ]

    operations = [
        migrations.RunPython(backfill, clear),
    ]
