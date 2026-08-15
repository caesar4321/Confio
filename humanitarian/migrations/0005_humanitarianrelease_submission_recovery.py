from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('humanitarian', '0004_humanitarianrelease_donation_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='humanitarianrelease',
            name='signed_transaction_b64',
            field=models.TextField(blank=True, default='', editable=False, help_text='Exact signed Algorand transaction claimed for crash-safe rebroadcast.'),
        ),
        migrations.AddField(
            model_name='humanitarianrelease',
            name='submitted_first_valid_round',
            field=models.PositiveBigIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='humanitarianrelease',
            name='submitted_last_valid_round',
            field=models.PositiveBigIntegerField(blank=True, editable=False, null=True),
        ),
    ]
