# Generated manually to update existing transactions with invitation status

from django.db import migrations

def update_invitation_status(apps, schema_editor):
    """Update is_invitation field for existing transactions where recipient_user is null"""
    SendTransaction = apps.get_model('send', 'SendTransaction')
    
    # Update all transactions where recipient_user is null to be invitations
    updated = SendTransaction.objects.filter(
        recipient_user__isnull=True,
        is_invitation=False
    ).update(is_invitation=True)
    
    print(f"Updated {updated} transactions to be marked as invitations")

def reverse_update(apps, schema_editor):
    """Reverse the update"""
    SendTransaction = apps.get_model('send', 'SendTransaction')
    SendTransaction.objects.filter(is_invitation=True).update(is_invitation=False)

class Migration(migrations.Migration):

    dependencies = [
        ('send', '0012_add_invitation_tracking_fields'),
    ]

    operations = [
        migrations.RunPython(update_invitation_status, reverse_update),
    ]