from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0017_face_check_evidence'),
    ]

    operations = [
        migrations.AddField(
            model_name='facecheck',
            name='start_integrity',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='+', to='security.integrityverdict'),
        ),
        migrations.AddField(
            model_name='facecheck',
            name='complete_integrity',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='+', to='security.integrityverdict'),
        ),
        migrations.AlterField(
            model_name='integrityverdict',
            name='trigger_action',
            field=models.CharField(
                choices=[('signup', 'Signup'), ('reward_claim', 'Reward Claim'),
                         ('transfer', 'Transfer/Withdrawal'), ('login', 'Login'), ('payroll', 'Payroll'),
                         ('topup_sell', 'TopUp/Sell'), ('payment', 'Payment'),
                         ('face_check_start', 'Confío Face start'),
                         ('face_check_complete', 'Confío Face grading'),
                         ('emergency_exit_face', 'Emergency exit (ban route)')],
                help_text='What action triggered this check', max_length=20),
        ),
    ]
