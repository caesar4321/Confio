# Generated manually to populate phone fields for existing transactions

from django.db import migrations

def populate_phone_fields(apps, schema_editor):
    SendTransaction = apps.get_model('send', 'SendTransaction')
    
    for transaction in SendTransaction.objects.all():
        # Update sender phone
        if transaction.sender_user and not transaction.sender_phone:
            sender = transaction.sender_user
            if hasattr(sender, 'phone_country') and hasattr(sender, 'phone_number'):
                if sender.phone_country and sender.phone_number:
                    transaction.sender_phone = f"{sender.phone_country}{sender.phone_number}"
        
        # Update recipient phone
        if transaction.recipient_user and not transaction.recipient_phone:
            recipient = transaction.recipient_user
            if hasattr(recipient, 'phone_country') and hasattr(recipient, 'phone_number'):
                if recipient.phone_country and recipient.phone_number:
                    transaction.recipient_phone = f"{recipient.phone_country}{recipient.phone_number}"
        
        # Ensure display names are populated
        if not transaction.sender_display_name:
            if transaction.sender_business:
                transaction.sender_display_name = transaction.sender_business.name
            elif transaction.sender_user:
                name = f"{transaction.sender_user.first_name} {transaction.sender_user.last_name}".strip()
                transaction.sender_display_name = name
        
        if not transaction.recipient_display_name:
            if transaction.recipient_business:
                transaction.recipient_display_name = transaction.recipient_business.name
            elif transaction.recipient_user:
                name = f"{transaction.recipient_user.first_name} {transaction.recipient_user.last_name}".strip()
                transaction.recipient_display_name = name
            else:
                transaction.recipient_display_name = "External Wallet"
        
        transaction.save()

def reverse_populate_phone_fields(apps, schema_editor):
    # No need to reverse this migration
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('send', '0008_add_phone_fields'),
    ]

    operations = [
        migrations.RunPython(populate_phone_fields, reverse_populate_phone_fields),
    ]