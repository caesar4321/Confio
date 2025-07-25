# Generated manually to clean up legacy display names

from django.db import migrations
from django.db.models import Q

def cleanup_legacy_display_names(apps, schema_editor):
    SendTransaction = apps.get_model('send', 'SendTransaction')
    
    # Delete transactions where display names are usernames or empty
    # This ensures all transactions follow the new display name rules
    
    for transaction in SendTransaction.objects.all():
        delete_transaction = False
        
        # Check sender display name
        if transaction.sender_display_name:
            # If it's a username (no spaces, typically alphanumeric)
            if ' ' not in transaction.sender_display_name and transaction.sender_user:
                if transaction.sender_display_name == transaction.sender_user.username:
                    delete_transaction = True
        else:
            # Empty display name
            delete_transaction = True
            
        # Check recipient display name (unless it's External Wallet)
        if transaction.recipient_display_name and transaction.recipient_display_name != "External Wallet":
            # If it's a username
            if ' ' not in transaction.recipient_display_name and transaction.recipient_user:
                if transaction.recipient_display_name == transaction.recipient_user.username:
                    delete_transaction = True
        elif not transaction.recipient_display_name and transaction.recipient_user:
            # Empty display name for a known user
            delete_transaction = True
            
        if delete_transaction:
            transaction.delete()

def reverse_cleanup_legacy_display_names(apps, schema_editor):
    # Cannot reverse deletions
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('send', '0009_populate_phone_fields'),
    ]

    operations = [
        migrations.RunPython(cleanup_legacy_display_names, reverse_cleanup_legacy_display_names),
    ]