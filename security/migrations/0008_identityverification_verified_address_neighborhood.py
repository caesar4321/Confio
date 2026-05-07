from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0007_identityverification_document_number_normalized'),
    ]

    operations = [
        migrations.AddField(
            model_name='identityverification',
            name='verified_address_neighborhood',
            field=models.CharField(blank=True, default='', help_text='Neighborhood/colonia as verified from documents', max_length=120),
        ),
    ]
