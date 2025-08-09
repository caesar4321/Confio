# Data migration to fix businesses without owner BusinessEmployee records

from django.db import migrations


def fix_missing_owners(apps, schema_editor):
    """Create BusinessEmployee records with role='owner' for businesses that don't have them"""
    Account = apps.get_model('users', 'Account')
    BusinessEmployee = apps.get_model('users', 'BusinessEmployee')
    
    # Find all business accounts
    business_accounts = Account.objects.filter(
        account_type='business',
        deleted_at__isnull=True
    ).select_related('user', 'business')
    
    for account in business_accounts:
        if not account.business:
            continue
            
        # Check if this business already has an owner
        existing_owner = BusinessEmployee.objects.filter(
            business=account.business,
            role='owner',
            deleted_at__isnull=True
        ).first()
        
        if not existing_owner:
            # Create owner BusinessEmployee record
            BusinessEmployee.objects.create(
                business=account.business,
                user=account.user,
                role='owner',
                hired_by=account.user,  # Owner hires themselves
                is_active=True
            )
            print(f"Created owner record for business: {account.business.name} (user: {account.user.username})")


def reverse_fix(apps, schema_editor):
    """Remove owner BusinessEmployee records (reverse migration)"""
    # This is intentionally a no-op since we don't want to remove valid data
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0055_fix_business_owner_employee'),
    ]

    operations = [
        migrations.RunPython(fix_missing_owners, reverse_fix),
    ]