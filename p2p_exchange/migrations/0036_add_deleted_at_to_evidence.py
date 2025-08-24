from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('p2p_exchange', '0035_create_dispute_evidence'),
    ]

    operations = [
        migrations.AddField(
            model_name='p2pdisputeevidence',
            name='deleted_at',
            field=models.DateTimeField(null=True, blank=True, help_text='Soft delete timestamp'),
        ),
    ]

