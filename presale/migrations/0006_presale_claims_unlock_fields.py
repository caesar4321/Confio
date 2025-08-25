from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('presale', '0005_create_default_presale_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='presalesettings',
            name='is_presale_claims_unlocked',
            field=models.BooleanField(default=False, help_text='If enabled, users can claim their CONFIO presale tokens'),
        ),
        migrations.AddField(
            model_name='presalesettings',
            name='presale_finished_at',
            field=models.DateTimeField(blank=True, help_text='Timestamp when presale was marked finished', null=True),
        ),
        migrations.AddField(
            model_name='presalesettings',
            name='claims_unlocked_at',
            field=models.DateTimeField(blank=True, help_text='Timestamp when claims were unlocked', null=True),
        ),
    ]

