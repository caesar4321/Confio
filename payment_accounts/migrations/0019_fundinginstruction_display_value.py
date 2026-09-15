from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('payment_accounts', '0018_breblocationcheck')]

    operations = [
        migrations.AlterField(
            model_name='fundinginstruction', name='display_value',
            field=models.TextField(blank=True, default=''),
        ),
    ]
