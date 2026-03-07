from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0016_add_algo_to_unified_token_choices'),
    ]

    operations = [
        migrations.AddField(
            model_name='bankinfo',
            name='provider_metadata',
            field=models.JSONField(blank=True, default=dict, help_text='Extra provider-specific fields required by some payout rails'),
        ),
    ]
