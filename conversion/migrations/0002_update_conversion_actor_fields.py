# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('conversion', '0001_initial'),
        ('users', '0019_add_conversions_to_unified_view'),
    ]

    operations = [
        # Add new fields for actor pattern
        migrations.AddField(
            model_name='conversion',
            name='actor_user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='user_conversions',
                to='users.user',
                help_text='User who initiated the conversion (if personal account)'
            ),
        ),
        migrations.AddField(
            model_name='conversion',
            name='actor_business',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='business_conversions',
                to='users.business',
                help_text='Business that initiated the conversion (if business account)'
            ),
        ),
        migrations.AddField(
            model_name='conversion',
            name='actor_type',
            field=models.CharField(
                choices=[('user', 'Personal'), ('business', 'Business')],
                default='user',
                max_length=10,
                help_text='Type of actor (user or business)'
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='conversion',
            name='actor_display_name',
            field=models.CharField(
                blank=True,
                max_length=255,
                help_text='Display name of the actor at conversion time'
            ),
        ),
        migrations.AddField(
            model_name='conversion',
            name='actor_address',
            field=models.CharField(
                blank=True,
                max_length=66,
                help_text='Blockchain address of the actor'
            ),
        ),
    ]