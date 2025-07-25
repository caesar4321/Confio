# Generated manually to populate phone fields for existing payment transactions

from django.db import migrations

def populate_phone_fields(apps, schema_editor):
    PaymentTransaction = apps.get_model('payments', 'PaymentTransaction')
    
    for transaction in PaymentTransaction.objects.all():
        # Update payer phone
        if transaction.payer_user and not transaction.payer_phone:
            payer = transaction.payer_user
            if hasattr(payer, 'phone_country') and hasattr(payer, 'phone_number'):
                if payer.phone_country and payer.phone_number:
                    transaction.payer_phone = f"{payer.phone_country}{payer.phone_number}"
        
        
        # Ensure display names are populated
        if not transaction.payer_display_name:
            if transaction.payer_business:
                transaction.payer_display_name = transaction.payer_business.name
            elif transaction.payer_user:
                name = f"{transaction.payer_user.first_name} {transaction.payer_user.last_name}".strip()
                transaction.payer_display_name = name
        
        # Merchant is ALWAYS a business for payments
        if not transaction.merchant_display_name:
            if transaction.merchant_business:
                transaction.merchant_display_name = transaction.merchant_business.name
        
        transaction.save()

def reverse_populate_phone_fields(apps, schema_editor):
    # No need to reverse this migration
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0011_add_phone_fields'),
    ]

    operations = [
        migrations.RunPython(populate_phone_fields, reverse_populate_phone_fields),
    ]