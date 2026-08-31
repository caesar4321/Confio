from django.db import migrations


LEGACY_FEE_KEY = 'legacy_payment_accounts_confio_fee'


def archive_legacy_confio_fees(apps, schema_editor):
    MoneyFlow = apps.get_model('payment_accounts', 'MoneyFlow')
    MoneyOperation = apps.get_model('payment_accounts', 'MoneyOperation')

    for flow in MoneyFlow.objects.exclude(confio_fee=0).iterator():
        metadata = dict(flow.metadata or {})
        metadata[LEGACY_FEE_KEY] = str(flow.confio_fee)
        flow.metadata = metadata
        flow.save(update_fields=['metadata'])

    for operation in MoneyOperation.objects.exclude(confio_fee=0).iterator():
        provider_data = dict(operation.provider_data or {})
        provider_data[LEGACY_FEE_KEY] = str(operation.confio_fee)
        operation.provider_data = provider_data
        operation.save(update_fields=['provider_data'])


def restore_legacy_confio_fees(apps, schema_editor):
    MoneyFlow = apps.get_model('payment_accounts', 'MoneyFlow')
    MoneyOperation = apps.get_model('payment_accounts', 'MoneyOperation')

    for flow in MoneyFlow.objects.filter(metadata__has_key=LEGACY_FEE_KEY).iterator():
        metadata = dict(flow.metadata or {})
        flow.confio_fee = metadata.pop(LEGACY_FEE_KEY)
        flow.metadata = metadata
        flow.save(update_fields=['confio_fee', 'metadata'])

    for operation in MoneyOperation.objects.filter(
        provider_data__has_key=LEGACY_FEE_KEY
    ).iterator():
        provider_data = dict(operation.provider_data or {})
        operation.confio_fee = provider_data.pop(LEGACY_FEE_KEY)
        operation.provider_data = provider_data
        operation.save(update_fields=['confio_fee', 'provider_data'])


class Migration(migrations.Migration):
    dependencies = [
        ('payment_accounts', '0003_fundinginstruction_payment_instruction_one_open_kind_uniq'),
    ]

    operations = [
        migrations.RunPython(
            archive_legacy_confio_fees,
            restore_legacy_confio_fees,
        ),
        migrations.RemoveField(
            model_name='moneyflow',
            name='confio_fee',
        ),
        migrations.RemoveField(
            model_name='moneyoperation',
            name='confio_fee',
        ),
    ]
