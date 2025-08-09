# Generated manually to rename aptos_address to algorand_address

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0056_fix_missing_business_owners'),
    ]

    operations = [
        # Remove the old aptos_address column if it exists
        migrations.RemoveField(
            model_name='account',
            name='aptos_address',
        ),
    ]