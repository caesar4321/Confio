"""Canonicalise ledger token_type, then enforce it.

Backfill FIRST: production carries 67 conversion rows written as lowercase
'cUSD', which no account screen queries (the app asks for exact 'CUSD'), so
those cards are invisible to the users who own them. Adding the constraint
before folding them would simply fail.
"""
from django.db import migrations, models

# Kept literal rather than imported from the model: a migration must keep
# working if the alias table is edited later.
ALIASES = {
    'CUSD+': 'CUSD_PLUS',
    'CUSDPLUS': 'CUSD_PLUS',
    'CUSD PLUS': 'CUSD_PLUS',
    'USDT BSC': 'USDT',
    'USDT-BSC': 'USDT',
    'USDTBSC': 'USDT',
    'USDC ALGORAND': 'USDC',
    'USDC POLYGON': 'USDC',
    'USDC-POLYGON': 'USDC',
}
CANONICAL = {'CUSD', 'CONFIO', 'USDC', 'ALGO', 'CUSD_PLUS', 'USDT'}


def canonicalise(apps, schema_editor):
    U = apps.get_model('users', 'UnifiedTransactionTable')
    # .order_by() clears Meta.ordering — Django adds the ordering column to
    # the SELECT, which defeats DISTINCT and yields the same value repeatedly.
    seen = U.objects.order_by().values_list('token_type', flat=True).distinct()
    for raw in list(seen):
        folded = ALIASES.get((raw or '').strip().upper(), (raw or '').strip().upper())
        if folded == raw:
            continue
        n = U.objects.filter(token_type=raw).update(token_type=folded)
        print(f"  token_type {raw!r} -> {folded!r}: {n} row(s)")

    # Anything still outside the canonical set would break AddConstraint, and
    # guessing its meaning is not this migration's job — fail with the actual
    # values so a human decides.
    leftover = set(U.objects.order_by().values_list('token_type', flat=True).distinct()) - CANONICAL
    if leftover:
        raise RuntimeError(
            f"non-canonical token_type values remain: {sorted(leftover)}. "
            f"Add them to TOKEN_TYPE_ALIASES in users/models_unified.py first."
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0030_remove_unifiedtransactiontable_cusd_plus_conversion'),
    ]

    operations = [
        migrations.RunPython(canonicalise, noop),
        migrations.AddConstraint(
            model_name='unifiedtransactiontable',
            constraint=models.CheckConstraint(
                check=models.Q(token_type__in=['ALGO', 'CONFIO', 'CUSD', 'CUSD_PLUS', 'USDC', 'USDT']),
                name='unified_token_type_canonical',
            ),
        ),
    ]
