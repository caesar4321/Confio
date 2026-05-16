from django.db import migrations, models


class Migration(migrations.Migration):
    """Convert RampTransaction.conversion from OneToOneField to ForeignKey.

    Motivation: a single internal Conversion can settle multiple ramp
    transactions when a user accumulates several deposits and converts them
    together (e.g. user 985: 3 Koywe deposits of 28.52 + 1997.75 + 28.50 USDC
    all consumed by one conv 661 for 2054.759450 USDC). With OneToOne we
    could only attribute the swap to one of the three ramps.

    Also renames the reverse accessor from `ramp_transaction` (singular,
    misleading for a manager) to `ramp_transactions` (plural).
    """

    dependencies = [
        ('conversion', '0001_initial'),
        ('ramps', '0009_rampuseraddress_mexico_compliance_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ramptransaction',
            name='conversion',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name='ramp_transactions',
                to='conversion.conversion',
            ),
        ),
    ]
