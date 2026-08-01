"""Bound every invoice's lifetime at the DATABASE, not just in Python.

`Invoice.save()` enforces the 24h ceiling, but `queryset.update()`,
`bulk_update()`, raw SQL and `loaddata` all bypass `save()` — so the
invariant the payment rails rely on was still optional (Codex audit
2026-08-01 [P2]). A check constraint is the only place no code path can
route around.

Existing rows must satisfy it before it can be added. The app has always
sent expiresInHours=24, so the violating population should be empty or
near-empty; the clamp is written to be safe either way and reports what it
touched. Clamping a settled (PAID/EXPIRED/CANCELLED) row is cosmetic — the
money already moved — and clamping a PENDING row to its proper ceiling is
exactly the bound being introduced.
"""
from datetime import timedelta

from django.db import migrations, models
from django.db.models import F

MAX_HOURS = 24


def clamp_overlong_invoices(apps, schema_editor):
    Invoice = apps.get_model('payments', 'Invoice')
    ceiling = F('created_at') + timedelta(hours=MAX_HOURS)
    overlong = Invoice.objects.filter(expires_at__gt=ceiling)
    count = overlong.count()
    if count:
        # .update() deliberately: this migration is the one writer that may
        # set expires_at without going through save()'s ceiling check.
        overlong.update(expires_at=ceiling)
    print(f"\n  clamped {count} invoice(s) to the {MAX_HOURS}h ceiling")


def noop_reverse(apps, schema_editor):
    """Dropping the constraint is reversible; the clamp is not.

    The original expires_at values are not recorded anywhere, so a reverse
    cannot restore them. Reversing therefore only removes the constraint —
    stated plainly rather than pretending the data change undoes.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0008_invoice_settlement_chain'),
    ]

    operations = [
        migrations.RunPython(clamp_overlong_invoices, noop_reverse),
        migrations.AddConstraint(
            model_name='invoice',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    expires_at__lte=F('created_at') + timedelta(hours=MAX_HOURS)),
                name='invoice_lifetime_within_24h',
            ),
        ),
    ]
