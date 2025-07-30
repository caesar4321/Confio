# Generated manually to create default PresaleSettings instance

from django.db import migrations

def create_default_settings(apps, schema_editor):
    PresaleSettings = apps.get_model('presale', 'PresaleSettings')
    # Create default settings with presale disabled
    PresaleSettings.objects.get_or_create(
        id=1,
        defaults={'is_presale_active': False}
    )

def reverse_func(apps, schema_editor):
    PresaleSettings = apps.get_model('presale', 'PresaleSettings')
    PresaleSettings.objects.filter(id=1).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('presale', '0004_presalesettings'),
    ]

    operations = [
        migrations.RunPython(create_default_settings, reverse_func),
    ]