"""Move CusdPlusConversion rows into conversion.Conversion.

The savings saga was a parallel model for the same concept, which forced
UnifiedTransactionTable to carry two FKs and every reader to branch — the
source of several mis-rendered rows. Send/Pay/Payroll already span both
chains in one model each; conversions now do too.

Runs BEFORE the FK drop (users.0030) and BEFORE the model delete, so the
old rows and the old column are both still available here.
"""
from django.db import migrations


FIELD_MAP = {
    # old CusdPlusConversion -> merged Conversion
    'direction': 'conversion_type',
    'amount_usd': 'from_amount',
    'quoted_receive_usd': 'to_amount',
    'src_tx_id': 'from_transaction_hash',
    'dest_tx_hash': 'to_transaction_hash',
    'user_algo_address': 'actor_address',
}
CARRIED = (
    'internal_id', 'actor_user_id', 'actor_business_id', 'actor_type',
    'actor_display_name', 'source', 'quoted_cost_pct', 'user_bsc_address',
    'bridge_arrival_tx', 'dest_scan_from_block', 'status', 'error_message',
    'created_at', 'src_committed_at', 'dest_arrived_at', 'completed_at',
    'is_deleted', 'deleted_at',
)


def forwards(apps, schema_editor):
    Old = apps.get_model('cusd_plus', 'CusdPlusConversion')
    Conversion = apps.get_model('conversion', 'Conversion')
    Unified = apps.get_model('users', 'UnifiedTransactionTable')

    for old in Old.objects.all().iterator():
        fields = {new: getattr(old, attr) for attr, new in FIELD_MAP.items()}
        fields.update({name: getattr(old, name) for name in CARRIED})
        # exchange_rate/fee_amount keep their model defaults: a savings
        # conversion is priced by pPlus at execution, not by a stored rate.
        new = Conversion.objects.create(**fields)

        # Repoint the mirror rows before the column disappears. A row may
        # have no mirror (mirror failures are swallowed by design), and the
        # target column is OneToOne, so this is a straight move.
        Unified.objects.filter(cusd_plus_conversion_id=old.id).update(
            cusd_plus_conversion=None, conversion_id=new.id,
        )


def backwards(apps, schema_editor):
    """Move the savings rows back out. Mirrors point back at the old rows."""
    Old = apps.get_model('cusd_plus', 'CusdPlusConversion')
    Conversion = apps.get_model('conversion', 'Conversion')
    Unified = apps.get_model('users', 'UnifiedTransactionTable')

    reverse_map = {v: k for k, v in FIELD_MAP.items()}
    for conv in Conversion.objects.filter(
        conversion_type__in=('to_savings', 'from_savings')
    ).iterator():
        fields = {old_name: getattr(conv, new_name)
                  for new_name, old_name in reverse_map.items()}
        fields.update({name: getattr(conv, name) for name in CARRIED})
        old = Old.objects.create(**fields)
        Unified.objects.filter(conversion_id=conv.id).update(
            conversion=None, cusd_plus_conversion_id=old.id,
        )
        conv.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('cusd_plus', '0010_delete_cusdplusmovement'),
        ('conversion', '0007_conversion_bridge_arrival_tx_and_more'),
        ('users', '0029_unifiedtransactiontable_cusd_plus_conversion'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
