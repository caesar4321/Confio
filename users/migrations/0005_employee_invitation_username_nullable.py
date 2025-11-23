from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_employee_invitation_username'),
    ]

    operations = [
        migrations.AlterField(
            model_name='employeeinvitation',
            name='employee_username',
            field=models.CharField(blank=True, max_length=150, null=True, help_text='Confío username of the invited employee (if invited by username)'),
        ),
    ]
