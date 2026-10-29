"""Claimed BSC invites, recorded right.

Before 2026-10-29 a confirmed claim only flagged the inviter's send as
claimed: it still named nobody, and the inbound scanner booked the escrow's
payout to the claimer as an "external deposit". Each claim becomes a send to
its claimer (one history row, both sides), and those duplicate deposit rows
are soft-deleted. The one row keeps the send's date and token for both sides
by choice: two rows would show the same money twice to one of them.
"""
from django.db import migrations
from django.utils import timezone


def repair(apps, schema_editor):
    PhoneInvite = apps.get_model('send', 'PhoneInvite')
    SendTransaction = apps.get_model('send', 'SendTransaction')
    Unified = apps.get_model('users', 'UnifiedTransactionTable')
    now = timezone.now()
    claimed = PhoneInvite.objects.filter(
        rail='bsc', status='claimed', claimed_by__isnull=False).select_related('claimed_by', 'send_transaction')
    for invite in claimed.iterator(chunk_size=200):
        claimer = invite.claimed_by
        name = ((f'{claimer.first_name} {claimer.last_name}').strip() or claimer.username or '')[:255]
        stx = invite.send_transaction
        if stx is not None and stx.recipient_user_id is None:
            SendTransaction.objects.filter(pk=stx.pk).update(
                recipient_user=claimer, recipient_type='user', recipient_display_name=name)
            Unified.objects.filter(send_transaction_id=stx.pk).update(
                counterparty_user=claimer, counterparty_type='user', counterparty_display_name=name)
        if invite.claimed_txid:
            dupes = SendTransaction.objects.filter(
                transaction_hash__iexact=invite.claimed_txid, sender_type='external', deleted_at__isnull=True)
            dupe_ids = list(dupes.values_list('pk', flat=True))
            if dupe_ids:
                SendTransaction.objects.filter(pk__in=dupe_ids).update(deleted_at=now)
                Unified.objects.filter(send_transaction_id__in=dupe_ids).update(deleted_at=now)


class Migration(migrations.Migration):

    dependencies = [
        ('send', '0019_recipient_phone_from_sender'),
        ('users', '0059_location_readings'),
    ]

    operations = [migrations.RunPython(repair, migrations.RunPython.noop)]
