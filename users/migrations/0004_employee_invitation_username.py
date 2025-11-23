from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_add_presale_transaction_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='employeeinvitation',
            name='employee_username',
            field=models.CharField(blank=True, max_length=150, help_text='Confío username of the invited employee (if invited by username)'),
        ),
    ]
