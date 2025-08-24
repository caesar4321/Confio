from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('p2p_exchange', '0033_create_premium_upgrade_request'),
    ]

    operations = [
        migrations.AddField(
            model_name='p2pdispute',
            name='evidence_code',
            field=models.CharField(max_length=12, blank=True, null=True, help_text='One-time Confío code for evidence'),
        ),
        migrations.AddField(
            model_name='p2pdispute',
            name='code_generated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='p2pdispute',
            name='code_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

