# Manual migration to fix empty transaction hashes
from django.db import migrations

def fix_empty_hashes(apps, schema_editor):
    """Convert empty transaction hashes to NULL"""
    SendTransaction = apps.get_model('send', 'SendTransaction')
    
    # Update all empty strings to NULL
    updated = SendTransaction.objects.filter(transaction_hash='').update(transaction_hash=None)
    print(f"Updated {updated} transactions with empty hashes to NULL")

def reverse_fix(apps, schema_editor):
    """Reverse: convert NULL back to empty strings"""
    SendTransaction = apps.get_model('send', 'SendTransaction')
    
    # Convert NULL back to empty strings
    SendTransaction.objects.filter(transaction_hash__isnull=True).update(transaction_hash='')

class Migration(migrations.Migration):

    dependencies = [
        ('send', '0019_fix_transaction_hash_null'),
    ]

    operations = [
        migrations.RunPython(fix_empty_hashes, reverse_fix),
    ]