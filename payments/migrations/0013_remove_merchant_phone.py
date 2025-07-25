# Generated manually to remove merchant_phone field since only businesses can accept payments

from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0012_populate_phone_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='paymenttransaction',
            name='merchant_phone',
        ),
    ]