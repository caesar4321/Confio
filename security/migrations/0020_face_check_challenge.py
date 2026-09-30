from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0019_face_check_payroll_authority'),
    ]

    operations = [
        migrations.AddField(
            model_name='facecheck',
            name='challenge',
            field=models.CharField(max_length=5, default='full', choices=[
                ('full', 'Movement and light'), ('light', 'Movement only'),
            ]),
        ),
        migrations.AddField(
            model_name='facecheck',
            name='amount_usd',
            field=models.DecimalField(max_digits=19, decimal_places=6, null=True, blank=True),
        ),
    ]
