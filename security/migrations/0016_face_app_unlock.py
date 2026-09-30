from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('security', '0015_payin_face_hold')]
    operations = [migrations.AlterField(
        model_name='facecheck', name='purpose',
        field=models.CharField(max_length=20, choices=[
            ('app_unlock', 'App unlock'), ('on_ramp', 'Deposit order'),
            ('withdrawal', 'Withdrawal'), ('emergency_exit', 'Emergency exit'),
            ('payin_release', 'Receive held pay-in'),
        ]),
    )]
