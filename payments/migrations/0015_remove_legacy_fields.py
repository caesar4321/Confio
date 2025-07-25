# Generated manually to remove all legacy fields

from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0014_cleanup_legacy_display_names'),
    ]

    operations = [
        # Remove legacy fields
        migrations.RemoveField(
            model_name='invoice',
            name='merchant_user',
        ),
        
        migrations.RemoveField(
            model_name='invoice',
            name='transaction',
        ),
        
        migrations.RemoveField(
            model_name='paymenttransaction',
            name='merchant_user',
        ),
        
        # Make fields non-nullable
        migrations.AlterField(
            model_name='invoice',
            name='created_by_user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='invoices_created_by',
                to='users.user',
                help_text='User who created this invoice (business owner or cashier)'
            ),
        ),
        
        migrations.AlterField(
            model_name='invoice',
            name='merchant_business',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='invoices_received',
                to='users.business',
                help_text='Business entity that is the actual merchant'
            ),
        ),
        
        migrations.AlterField(
            model_name='paymenttransaction',
            name='merchant_business',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='payment_transactions_received',
                to='users.business',
                help_text='Business entity that received the payment'
            ),
        ),
    ]