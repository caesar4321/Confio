import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):
    """Per-wallet stock history lookups (Tu mes "Tus acciones"): an index on
    the expression __iexact compiles to, so they stop reading every stock
    batch of every user on each open and settling poll."""

    dependencies = [
        ('blockchain', '0015_include_cusd_in_payment_uniqueness'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='sponsoredbatch',
            index=models.Index(
                django.db.models.functions.text.Upper('user_bsc_address'),
                models.F('kind'),
                name='cpsb_addr_kind_idx',
            ),
        ),
    ]
