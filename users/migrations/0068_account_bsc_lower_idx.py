import django.db.models.functions.text
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # Built CONCURRENTLY: users_account takes writes (sign-ins) throughout.
    atomic = False

    dependencies = [
        ('users', '0067_retire_closed_account_bsc_addresses'),
    ]

    operations = [
        AddIndexConcurrently(
            model_name='account',
            index=models.Index(django.db.models.functions.text.Lower('bsc_address'), name='account_bsc_lower_idx'),
        ),
    ]
