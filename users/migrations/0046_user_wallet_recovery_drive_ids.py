from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('users', '0045_funnelevent_ip_country')]
    operations = [migrations.AddField(
        model_name='user', name='wallet_recovery_drive_ids',
        field=models.JSONField(default=list, blank=True),
    )]
