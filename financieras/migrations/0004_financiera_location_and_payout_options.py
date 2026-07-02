# Generated manually on 2026-07-01

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financieras', '0003_financierareview_sent_token_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='financiera',
            name='has_physical_location',
            field=models.BooleanField(
                default=True,
                help_text='Has a physical storefront/local users can visit',
            ),
        ),
        migrations.AddField(
            model_name='financiera',
            name='cash_usd',
            field=models.BooleanField(default=True, help_text='Can deliver USD cash'),
        ),
        migrations.AddField(
            model_name='financiera',
            name='cash_local',
            field=models.BooleanField(default=False, help_text='Can deliver local currency in cash (Bs., COP, S/, ...)'),
        ),
        migrations.AddField(
            model_name='financiera',
            name='digital_local',
            field=models.BooleanField(
                default=False,
                help_text='Can deliver local currency digitally (bank transfer / pago móvil / Nequi / Yape ...)',
            ),
        ),
    ]
