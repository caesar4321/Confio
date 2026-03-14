from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0006_backfill_video_platform_links'),
    ]

    operations = [
        migrations.AddField(
            model_name='contentitem',
            name='push_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
