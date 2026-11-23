from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smart_account', '0006_subscription_epoch'),
    ]

    operations = [
        migrations.AddField(
            model_name='smartaccountstandingauthorization',
            name='max_processor_fee_usd',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='smartaccountstandingauthorization',
            name='holder_name',
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
    ]
