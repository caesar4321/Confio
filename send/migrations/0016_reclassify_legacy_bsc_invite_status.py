"""Reclassify BSC invite rows written under the old two-meaning 'pending'.

Before 0012, 'pending' meant BOTH "prepared, nothing broadcast" and "escrow
funded, awaiting claim". 0012 split those into 'draft' / 'creating' / 'pending'
but left existing rows alone, so a legacy row now reads as FUNDED: it cannot be
submitted (submit_create wants 'draft'), cannot be recycled by a fresh prepare
(which refuses anything that is not draft/failed), and the auto-claim would try
to release an escrow slot that may not exist (Codex follow-up audit 2026-08-02).

The linked SendTransaction says which it really was:
  PENDING    → nothing was ever broadcast          → 'draft'
  SUBMITTED  → a create is in flight               → 'creating'
  CONFIRMED  → the escrow is funded                → 'pending' (already right)

Algorand rows are untouched: 'pending' still means exactly one thing there.

BSC_INVITE_ENABLED has never been True, so this is expected to match nothing.
"""
from django.db import migrations


def reclassify(apps, schema_editor):
    PhoneInvite = apps.get_model('send', 'PhoneInvite')
    base = PhoneInvite.objects.filter(rail='bsc', status='pending')
    base.filter(send_transaction__status='PENDING').update(status='draft')
    base.filter(send_transaction__status='SUBMITTED').update(status='creating')
    # A BSC row with no history row at all predates the row being written and
    # cannot be shown to be funded. Left as 'pending' deliberately: reclaim
    # still works from there, and guessing 'draft' would invite a second create
    # against a slot that might hold money.


def noop(apps, schema_editor):
    """Reversing would restore the ambiguity this resolved."""


class Migration(migrations.Migration):

    dependencies = [
        ('send', '0015_backfill_phoneinvite_rail'),
    ]

    operations = [
        migrations.RunPython(reclassify, noop),
    ]
