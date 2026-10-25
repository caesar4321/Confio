"""One Agenda entry per live Mis cuentas row (own account), like the mirror."""
from django.db import migrations


def _entry_values(row):
    method = row.ramp_payment_method or row.payment_method
    method_name = str(getattr(method, 'display_name', '') or 'Cuenta')
    country = str(getattr(method, 'country_code', '') or '').upper()
    if not country and row.country_id:
        country = str(row.country.code or '').upper()
    identifier = (row.account_number or row.phone_number or row.email or row.username or '').strip()
    return dict(
        confio_account_id=row.account_id, rail='bank_info', country=country[:2], relationship='own',
        label=(f"{method_name} ···{identifier[-4:]}" if identifier else method_name)[:100],
        holder_name=(row.account_holder_name or '')[:255], holder_id_type='',
        holder_id_number=(row.identification_number or '')[:100],
        details={'method': method_name, 'identifier_last4': identifier[-4:]},
        is_default=bool(row.is_default),
    )


def backfill(apps, schema_editor):
    BankInfo = apps.get_model('users', 'BankInfo')
    AgendaEntry = apps.get_model('payment_accounts', 'AgendaEntry')
    rows = BankInfo.objects.filter(deleted_at__isnull=True, agenda_entry__isnull=True).select_related(
        'payment_method', 'ramp_payment_method', 'country')
    batch = [AgendaEntry(bank_info_id=row.pk, **_entry_values(row)) for row in rows.iterator(chunk_size=500)]
    AgendaEntry.objects.bulk_create(batch, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('payment_accounts', '0030_agenda_entry'),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
