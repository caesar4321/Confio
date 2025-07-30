# Generated manually to convert string amounts to decimal
from django.db import migrations
from decimal import Decimal

def convert_amounts_to_decimal(apps, schema_editor):
    """Convert string amounts to decimal values"""
    SendTransaction = apps.get_model('send', 'SendTransaction')
    
    for transaction in SendTransaction.objects.all():
        if transaction.amount and isinstance(transaction.amount, str):
            try:
                # Convert string to decimal
                decimal_amount = Decimal(transaction.amount)
                transaction.amount = decimal_amount
                transaction.save(update_fields=['amount'])
            except Exception as e:
                print(f"Error converting transaction {transaction.id}: {e}")

def reverse_amounts_to_string(apps, schema_editor):
    """Reverse migration: convert decimal amounts back to strings"""
    SendTransaction = apps.get_model('send', 'SendTransaction')
    
    for transaction in SendTransaction.objects.all():
        if transaction.amount:
            transaction.amount = str(transaction.amount)
            transaction.save(update_fields=['amount'])

class Migration(migrations.Migration):

    dependencies = [
        ('send', '0017_alter_sendtransaction_amount'),
    ]

    operations = [
        migrations.RunPython(
            convert_amounts_to_decimal,
            reverse_amounts_to_string,
        ),
    ]