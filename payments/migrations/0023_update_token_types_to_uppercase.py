from django.db import migrations


def upgrade_token_types(apps, schema_editor):
    PaymentTransaction = apps.get_model('payments', 'PaymentTransaction')
    Invoice = apps.get_model('payments', 'Invoice')
    # Normalize cUSD -> CUSD for payment transactions
    PaymentTransaction.objects.filter(token_type='cUSD').update(token_type='CUSD')
    # Normalize invoice token types as well for consistency
    Invoice.objects.filter(token_type='cUSD').update(token_type='CUSD')


def downgrade_token_types(apps, schema_editor):
    PaymentTransaction = apps.get_model('payments', 'PaymentTransaction')
    Invoice = apps.get_model('payments', 'Invoice')
    # Revert CUSD -> cUSD
    PaymentTransaction.objects.filter(token_type='CUSD').update(token_type='cUSD')
    Invoice.objects.filter(token_type='CUSD').update(token_type='cUSD')


class Migration(migrations.Migration):
    dependencies = [
        ('payments', '0022_increase_status_field_length'),
    ]

    operations = [
        migrations.RunPython(upgrade_token_types, downgrade_token_types),
    ]

