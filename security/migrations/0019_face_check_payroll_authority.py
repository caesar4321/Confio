from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0018_face_check_app_check'),
    ]

    operations = [
        migrations.AlterField(
            model_name='facecheck',
            name='purpose',
            field=models.CharField(max_length=20, choices=[
                ('app_unlock', 'App unlock'), ('on_ramp', 'Deposit order'),
                ('withdrawal', 'Withdrawal'), ('emergency_exit', 'Emergency exit'),
                ('payin_release', 'Receive held pay-in'),
                ('payroll_authority', 'Payroll authority change'),
            ]),
        ),
    ]
