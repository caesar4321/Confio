"""Backfill PhoneInvite.inviter_address for rows written before 0011.

0011 added the column with default '', and the BSC flow then started treating a
blank inviter_address as "not a BSC invite" — it is the discriminator that keeps
the auto-claim off the older Algorand rail's rows. So any BSC invite created
before 0011 would be invisible to both auto-claim and reclaim while its money
sat in the escrow (Codex audit 2026-08-02 P1).

BSC_INVITE_ENABLED has never been True, so in practice this is expected to
match nothing. It costs one indexed scan and removes the need to be right about
that.

The address is recovered from the linked SendTransaction.sender_address, which
the BSC flow sets to the escrowing account. The 0x guard is what keeps Algorand
rows out: their sender_address is an Algorand address, and their CONFIO rows
would otherwise look exactly like BSC ones.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    PhoneInvite = apps.get_model('send', 'PhoneInvite')
    rows = PhoneInvite.objects.filter(
        inviter_address='',
        token_type__in=('CUSD_PLUS', 'CONFIO'),
        send_transaction__isnull=False,
        send_transaction__sender_address__startswith='0x',
    ).select_related('send_transaction')
    for inv in rows.iterator():
        inv.inviter_address = (inv.send_transaction.sender_address or '').lower()
        inv.save(update_fields=['inviter_address'])


def noop(apps, schema_editor):
    """Reversing would re-strand exactly the rows this repaired."""


class Migration(migrations.Migration):

    dependencies = [
        ('send', '0012_alter_phoneinvite_status'),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
