from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_country_bank_bankinfo'),
    ]

    operations = [
        migrations.AddField(
            model_name='bankinfo',
            name='ownership_proof_url',
            field=models.URLField(blank=True, help_text='S3 URL to screenshot or statement proving ownership of this payout method', null=True),
        ),
    ]

