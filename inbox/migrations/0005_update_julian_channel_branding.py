from django.db import migrations


def update_julian_channel_branding(apps, schema_editor):
    Channel = apps.get_model('inbox', 'Channel')
    Channel.objects.filter(slug='julian').update(
        title='🇰🇷 Julian Moon 🌙',
        subtitle='@julianmoonluna',
        avatar_type='EMOJI',
        avatar_value='🇰🇷',
    )


def reverse_julian_channel_branding(apps, schema_editor):
    Channel = apps.get_model('inbox', 'Channel')
    Channel.objects.filter(slug='julian').update(
        title='Julian Moon',
        subtitle='Founder · @julianmoonluna',
        avatar_type='EMOJI',
        avatar_value='🇰🇷',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0004_seed_message_content'),
    ]

    operations = [
        migrations.RunPython(update_julian_channel_branding, reverse_julian_channel_branding),
    ]
