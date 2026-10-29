from django.db import migrations, models
from django.db.models import F


def backfill(apps, schema_editor):
    # Everyone who completed the phone step counted as a real user until now;
    # dating them at signup keeps every existing daily series unchanged.
    User = apps.get_model('users', 'User')
    User.objects.filter(onboarded_at__isnull=True, phone_number__isnull=False).exclude(
        phone_number='').update(onboarded_at=F('created_at'))


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0057_direct_receive_block'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='onboarded_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
