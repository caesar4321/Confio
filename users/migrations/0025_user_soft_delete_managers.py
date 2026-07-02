from django.db import migrations
import users.models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0024_add_humanitarian_to_unified_transactions'),
    ]

    operations = [
        migrations.AlterModelManagers(
            name='user',
            managers=[
                ('objects', users.models.SoftDeleteUserManager()),
                ('all_objects', users.models.AllObjectsUserManager()),
            ],
        ),
    ]
