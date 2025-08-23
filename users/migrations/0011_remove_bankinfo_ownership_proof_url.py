from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0010_add_bankinfo_ownership_proof_url'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='bankinfo',
            name='ownership_proof_url',
        ),
    ]

