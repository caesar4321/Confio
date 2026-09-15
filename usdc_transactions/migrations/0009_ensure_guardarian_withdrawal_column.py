from django.db import migrations


def ensure_withdrawal_column(apps, schema_editor):
    """0004 assumed an existing production column; fresh databases need it too."""
    model = apps.get_model('usdc_transactions', 'GuardarianTransaction')
    field = model._meta.get_field('onchain_withdrawal')
    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name for column in schema_editor.connection.introspection.get_table_description(
                cursor, model._meta.db_table,
            )
        }
    if field.column not in columns:
        schema_editor.add_field(model, field)


class Migration(migrations.Migration):
    dependencies = [
        ('usdc_transactions', '0008_guardarian_confio_fee_metadata'),
    ]

    # The field is already in migration state. Keep pre-existing production
    # data intact on rollback; this only repairs a missing database column.
    operations = [migrations.RunPython(ensure_withdrawal_column, migrations.RunPython.noop)]
