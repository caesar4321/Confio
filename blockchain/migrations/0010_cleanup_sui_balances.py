from django.db import migrations


def delete_sui_balances(apps, schema_editor):
    Balance = apps.get_model('blockchain', 'Balance')
    Balance.objects.filter(token='SUI').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('blockchain', '0009_delete_suiepoch_alter_balance_token'),
    ]

    operations = [
        migrations.RunPython(delete_sui_balances, migrations.RunPython.noop),
    ]

