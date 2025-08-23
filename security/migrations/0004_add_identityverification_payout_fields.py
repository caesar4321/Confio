from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0003_add_identityverification_s3_url_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='identityverification',
            name='payout_method_label',
            field=models.CharField(blank=True, help_text='Label/name of payout method being proven (e.g., Nequi, Banco de Venezuela)', max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='identityverification',
            name='payout_proof_url',
            field=models.URLField(blank=True, help_text='S3 URL to payout ownership proof (integrated with ID verification)', null=True),
        ),
    ]

