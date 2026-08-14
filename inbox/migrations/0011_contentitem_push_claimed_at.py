from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('inbox', '0010_contentplatformclickdailystat'),
    ]

    operations = [
        migrations.AddField(
            model_name='contentitem',
            name='push_claimed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
