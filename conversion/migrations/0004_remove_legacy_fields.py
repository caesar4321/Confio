# Generated manually

from django.db import migrations, models


def delete_invalid_conversions(apps, schema_editor):
    """Delete conversions that don't have proper actor fields set"""
    Conversion = apps.get_model('conversion', 'Conversion')
    
    # Delete conversions where actor fields are not properly set
    invalid_conversions = Conversion.objects.filter(
        actor_type='user',
        actor_user__isnull=True
    ) | Conversion.objects.filter(
        actor_type='business', 
        actor_business__isnull=True
    )
    
    count = invalid_conversions.count()
    if count > 0:
        print(f"Deleting {count} invalid conversion records...")
        invalid_conversions.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('conversion', '0003_populate_actor_fields'),
    ]

    operations = [
        # First clean up invalid data
        migrations.RunPython(delete_invalid_conversions, migrations.RunPython.noop),
        
        # Remove legacy fields
        migrations.RemoveField(
            model_name='conversion',
            name='user',
        ),
        migrations.RemoveField(
            model_name='conversion',
            name='account',
        ),
        
        # Update indexes to use actor fields
        # Note: The old indexes may not exist, so we'll add the new ones without removing the old ones
        migrations.AddIndex(
            model_name='conversion',
            index=models.Index(fields=['actor_user', 'status'], name='conv_actor_user_status_idx'),
        ),
        migrations.AddIndex(
            model_name='conversion',
            index=models.Index(fields=['actor_business', 'status'], name='conv_actor_bus_status_idx'),
        ),
        migrations.AddIndex(
            model_name='conversion',
            index=models.Index(fields=['actor_type', 'status'], name='conv_actor_type_status_idx'),
        ),
    ]