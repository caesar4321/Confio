from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('p2p_exchange', '0036_add_deleted_at_to_evidence'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='p2pdisputeevidence',
            name='is_deleted',
        ),
    ]

