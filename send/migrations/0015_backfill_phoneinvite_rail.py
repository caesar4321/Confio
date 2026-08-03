"""Label existing PhoneInvite rows with the rail that actually holds them.

0014 added `rail` with default 'algorand', which is right for the overwhelming
majority — the BSC escrow has never been enabled in production. This corrects
the exceptions rather than trusting that claim.

A BSC row is identifiable by the 0x inviter_address that 0011/0013 established.
Anything else is Algorand and the default already covers it.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    PhoneInvite = apps.get_model('send', 'PhoneInvite')
    PhoneInvite.objects.filter(inviter_address__startswith='0x').update(rail='bsc')


def unlabel(apps, schema_editor):
    PhoneInvite = apps.get_model('send', 'PhoneInvite')
    PhoneInvite.objects.update(rail='algorand')


class Migration(migrations.Migration):

    dependencies = [
        ('send', '0014_phoneinvite_rail'),
    ]

    operations = [
        migrations.RunPython(backfill, unlabel),
    ]
