from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='last_activity_at',
            field=models.DateTimeField(blank=True, null=True, db_index=True),
        ),
    ]

