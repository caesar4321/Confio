from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0004_add_identityverification_payout_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='identityverification',
            name='document_front_image',
            field=models.FileField(blank=True, null=True, help_text='Front side of identification document', upload_to='verification_documents/'),
        ),
        migrations.AlterField(
            model_name='identityverification',
            name='selfie_with_document',
            field=models.FileField(blank=True, null=True, help_text='Selfie holding the identification document', upload_to='verification_documents/'),
        ),
    ]

