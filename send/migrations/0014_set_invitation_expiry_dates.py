# Generated manually to set expiry dates for existing invitation transactions

from django.db import migrations
from django.utils import timezone
from datetime import timedelta

def set_expiry_dates(apps, schema_editor):
    """Set invitation_expires_at for existing invitation transactions"""
    SendTransaction = apps.get_model('send', 'SendTransaction')
    
    # Update all invitation transactions that don't have an expiry date
    invitations = SendTransaction.objects.filter(
        is_invitation=True,
        invitation_expires_at__isnull=True
    )
    
    count = 0
    for tx in invitations:
        # Set expiry to 7 days from creation
        tx.invitation_expires_at = tx.created_at + timedelta(days=7)
        tx.save()
        count += 1
    
    print(f"Updated {count} invitation transactions with expiry dates")

def reverse_update(apps, schema_editor):
    """Reverse the update"""
    SendTransaction = apps.get_model('send', 'SendTransaction')
    SendTransaction.objects.filter(is_invitation=True).update(invitation_expires_at=None)

class Migration(migrations.Migration):

    dependencies = [
        ('send', '0013_update_existing_invitation_transactions'),
    ]

    operations = [
        migrations.RunPython(set_expiry_dates, reverse_update),
    ]