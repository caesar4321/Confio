# Generated migration to remove blockchain fields

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('usdc_transactions', '0003_fix_unified_view_no_id'),
    ]

    operations = [
        # Remove blockchain fields from USDCDeposit
        migrations.RemoveField(
            model_name='usdcdeposit',
            name='transaction_hash',
        ),
        migrations.RemoveField(
            model_name='usdcdeposit',
            name='block_number',
        ),
        migrations.RemoveField(
            model_name='usdcdeposit',
            name='network_fee',
        ),
        
        # Remove blockchain fields from USDCWithdrawal
        migrations.RemoveField(
            model_name='usdcwithdrawal',
            name='transaction_hash',
        ),
        migrations.RemoveField(
            model_name='usdcwithdrawal',
            name='block_number',
        ),
        migrations.RemoveField(
            model_name='usdcwithdrawal',
            name='network_fee',
        ),
    ]