# Generated manually to convert string amounts to decimal
from django.db import migrations
from decimal import Decimal

def convert_amounts_to_decimal(apps, schema_editor):
    """Convert string amounts to decimal values"""
    PaymentTransaction = apps.get_model('payments', 'PaymentTransaction')
    Invoice = apps.get_model('payments', 'Invoice')
    
    # Convert PaymentTransaction amounts
    for transaction in PaymentTransaction.objects.all():
        if transaction.amount and isinstance(transaction.amount, str):
            try:
                decimal_amount = Decimal(transaction.amount)
                transaction.amount = decimal_amount
                transaction.save(update_fields=['amount'])
            except Exception as e:
                print(f"Error converting payment transaction {transaction.id}: {e}")
    
    # Convert Invoice amounts
    for invoice in Invoice.objects.all():
        if invoice.amount and isinstance(invoice.amount, str):
            try:
                decimal_amount = Decimal(invoice.amount)
                invoice.amount = decimal_amount
                invoice.save(update_fields=['amount'])
            except Exception as e:
                print(f"Error converting invoice {invoice.id}: {e}")

def reverse_amounts_to_string(apps, schema_editor):
    """Reverse migration: convert decimal amounts back to strings"""
    PaymentTransaction = apps.get_model('payments', 'PaymentTransaction')
    Invoice = apps.get_model('payments', 'Invoice')
    
    # Reverse PaymentTransaction amounts
    for transaction in PaymentTransaction.objects.all():
        if transaction.amount:
            transaction.amount = str(transaction.amount)
            transaction.save(update_fields=['amount'])
    
    # Reverse Invoice amounts
    for invoice in Invoice.objects.all():
        if invoice.amount:
            invoice.amount = str(invoice.amount)
            invoice.save(update_fields=['amount'])

class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0019_alter_invoice_amount_alter_paymenttransaction_amount'),
    ]

    operations = [
        migrations.RunPython(
            convert_amounts_to_decimal,
            reverse_amounts_to_string,
        ),
    ]