from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0002_add_ip_device_user_tracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='identityverification',
            name='document_front_url',
            field=models.URLField(blank=True, help_text='S3 URL to front side of document (if uploaded directly)', null=True),
        ),
        migrations.AddField(
            model_name='identityverification',
            name='document_back_url',
            field=models.URLField(blank=True, help_text='S3 URL to back side of document (if uploaded directly)', null=True),
        ),
        migrations.AddField(
            model_name='identityverification',
            name='selfie_url',
            field=models.URLField(blank=True, help_text='S3 URL to selfie with document (if uploaded directly)', null=True),
        ),
    ]

