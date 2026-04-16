from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('presale', '0006_presalepurchase_terms_acceptance'),
    ]

    operations = [
        migrations.AddField(
            model_name='presalesettings',
            name='telegram_group_enabled',
            field=models.BooleanField(
                default=False,
                help_text='If enabled, a modal will appear after presale purchase inviting user to join the private Telegram group',
            ),
        ),
        migrations.AddField(
            model_name='presalesettings',
            name='telegram_group_url',
            field=models.URLField(
                blank=True,
                default='',
                help_text='Invite URL for the private Telegram group (e.g. https://t.me/+AbCdEfGhIjK)',
                max_length=500,
            ),
        ),
    ]
