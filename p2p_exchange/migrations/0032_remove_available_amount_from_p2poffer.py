from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('p2p_exchange', '0031_alter_p2ptrade_status'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='p2poffer',
            name='available_amount',
        ),
    ]

