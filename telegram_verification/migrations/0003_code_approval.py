from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('telegram_verification', '0002_initial')]
    operations = [
        migrations.AddField(
            model_name='telegramverification', name='approved_code_hash',
            field=models.CharField(max_length=64, blank=True, default=''),
        ),
        migrations.AddField(
            model_name='telegramverification', name='attempts',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
