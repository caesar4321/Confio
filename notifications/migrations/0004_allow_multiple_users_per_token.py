# Generated migration to allow multiple users per FCM token
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0003_add_account_context_to_notification_read'),
    ]

    operations = [
        # Remove the unique constraint from token field
        migrations.AlterField(
            model_name='fcmdevicetoken',
            name='token',
            field=models.TextField(help_text='FCM token - can be shared by multiple users'),
        ),
        
        # Add unique constraint on (user, token) combination
        migrations.AlterUniqueTogether(
            name='fcmdevicetoken',
            unique_together={('user', 'token')},
        ),
        
        # Add indexes for better query performance
        migrations.AddIndex(
            model_name='fcmdevicetoken',
            index=models.Index(fields=['token', 'is_active'], name='fcm_token_active_idx'),
        ),
        migrations.AddIndex(
            model_name='fcmdevicetoken',
            index=models.Index(fields=['user', 'is_active'], name='fcm_user_active_idx'),
        ),
    ]