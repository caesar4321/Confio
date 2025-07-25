# Generated manually to clean up legacy display names

from django.db import migrations

def cleanup_legacy_display_names(apps, schema_editor):
    PaymentTransaction = apps.get_model('payments', 'PaymentTransaction')
    
    # Delete payment transactions that don't follow the new rules:
    # 1. Merchant must always be a business (merchant_business must exist)
    # 2. Display names must not be usernames
    
    for transaction in PaymentTransaction.objects.all():
        delete_transaction = False
        
        # Payment transactions MUST have a merchant business
        if not transaction.merchant_business:
            delete_transaction = True
            
        # Check payer display name
        if transaction.payer_display_name:
            # If it's a username (no spaces) and payer is personal
            if ' ' not in transaction.payer_display_name and transaction.payer_user and not transaction.payer_business:
                if transaction.payer_display_name == transaction.payer_user.username:
                    delete_transaction = True
        else:
            # Empty display name
            delete_transaction = True
            
        # Check merchant display name (should always be business name)
        if not transaction.merchant_display_name and transaction.merchant_business:
            # Empty display name for a business
            delete_transaction = True
            
        if delete_transaction:
            transaction.delete()

def reverse_cleanup_legacy_display_names(apps, schema_editor):
    # Cannot reverse deletions
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0013_remove_merchant_phone'),
    ]

    operations = [
        migrations.RunPython(cleanup_legacy_display_names, reverse_cleanup_legacy_display_names),
    ]