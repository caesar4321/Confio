"""Per-country presale access replaces the US-only switch.

Seeds the US at whatever PresaleSettings.us_access says (waitlist on prod),
KR and GB blocked. Every row covers the user's country and the request IP,
so KR is now refused by IP too (it never was before). The waitlist's 'us' region becomes the ISO code 'US'. The old
us_access column stays, unused, until a later migration.
"""
from django.db import migrations, models


def seed(apps, schema_editor):
    Settings = apps.get_model('presale', 'PresaleSettings')
    Access = apps.get_model('presale', 'PresaleCountryAccess')
    Waitlist = apps.get_model('presale', 'PresaleWaitlist')
    row = Settings.objects.filter(id=1).first()
    us = getattr(row, 'us_access', None) or 'waitlist'
    for country, access in (('US', us), ('KR', 'blocked'), ('GB', 'blocked')):
        Access.objects.update_or_create(country=country, defaults={'access': access})
    Waitlist.objects.filter(region='us').update(region='US')


def unseed(apps, schema_editor):
    Settings = apps.get_model('presale', 'PresaleSettings')
    Access = apps.get_model('presale', 'PresaleCountryAccess')
    Waitlist = apps.get_model('presale', 'PresaleWaitlist')
    us = Access.objects.filter(country='US').first()
    Settings.objects.filter(id=1).update(us_access=us.access if us else 'waitlist')
    Waitlist.objects.filter(region='US').update(region='us')


class Migration(migrations.Migration):

    dependencies = [
        ('presale', '0015_presale_us_access'),
    ]

    operations = [
        migrations.CreateModel(
            name='PresaleCountryAccess',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('country', models.CharField(help_text='ISO-2, upper case (US, KR, GB)', max_length=2, unique=True)),
                ('access', models.CharField(choices=[('blocked', 'Blocked'), ('waitlist', 'Waitlist only'), ('open', 'Open')], default='blocked', help_text="Blocked: no purchase, no waitlist. Waitlist only: no purchase, may join the country's waitlist. Open: may buy (open US also drops the not-US attestation).", max_length=16)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Presale Country Access',
                'verbose_name_plural': 'Presale Country Access',
                'ordering': ['country'],
            },
        ),
        migrations.RunPython(seed, unseed),
        migrations.AlterField(
            model_name='presalewaitlist',
            name='region',
            field=models.CharField(db_index=True, default='launch', max_length=16),
        ),
        # us_access stays until a later migration: workers running the old
        # code still select it while this one deploys.
        migrations.AlterField(
            model_name='presalesettings',
            name='us_access',
            field=models.CharField(default='waitlist', editable=False, max_length=16),
        ),
    ]
