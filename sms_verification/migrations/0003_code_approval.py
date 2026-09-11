from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('sms_verification', '0002_initial')]
    operations = [
        migrations.AddField(
            model_name='smsverification', name='approved_code_hash',
            field=models.CharField(max_length=64, blank=True, default=''),
        ),
    ]
