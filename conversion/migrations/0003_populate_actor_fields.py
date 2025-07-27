# Generated manually

from django.db import migrations


def populate_actor_fields(apps, schema_editor):
    """Populate the new actor fields from existing account data"""
    Conversion = apps.get_model('conversion', 'Conversion')
    
    for conversion in Conversion.objects.all():
        # Get the account to determine actor type
        account = conversion.account
        
        if account.account_type == 'business':
            conversion.actor_type = 'business'
            conversion.actor_business = account.business
            conversion.actor_user = None
            conversion.actor_display_name = account.business.name if account.business else ''
        else:
            conversion.actor_type = 'user'
            conversion.actor_user = conversion.user
            conversion.actor_business = None
            conversion.actor_display_name = conversion.user.username
        
        conversion.actor_address = account.sui_address
        conversion.save()


def reverse_actor_fields(apps, schema_editor):
    """Clear the actor fields"""
    Conversion = apps.get_model('conversion', 'Conversion')
    Conversion.objects.update(
        actor_type='user',
        actor_user=None,
        actor_business=None,
        actor_display_name='',
        actor_address=''
    )


class Migration(migrations.Migration):

    dependencies = [
        ('conversion', '0002_update_conversion_actor_fields'),
    ]

    operations = [
        migrations.RunPython(populate_actor_fields, reverse_actor_fields),
    ]