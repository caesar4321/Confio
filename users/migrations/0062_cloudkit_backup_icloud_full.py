from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0061_cloudkit_backup_proof'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='cloudkit_backup_state',
            field=models.CharField(blank=True, choices=[('proven', 'Proven'), ('no_icloud_account', 'No iCloud account'), ('icloud_restricted', 'iCloud restricted'), ('icloud_full', 'iCloud storage full'), ('failed', 'Failed')], db_index=True, default='', help_text='Empty means no report reached the server, for any reason', max_length=20),
        ),
    ]
