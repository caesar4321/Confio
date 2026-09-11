from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('users', '0042_add_bnb_unified_token')]

    operations = [
        migrations.AlterField(
            model_name='bankinfo',
            name='account_number',
            field=models.CharField(
                max_length=254, blank=True, null=True,
                help_text='Account number (for banks) or identifier (for some fintech)',
            ),
        ),
    ]
