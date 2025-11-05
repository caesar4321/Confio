from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('achievements', '0002_initial'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='InfluencerReferral',
            new_name='UserReferral',
        ),
        migrations.RenameField(
            model_name='userreferral',
            old_name='influencer_user',
            new_name='referrer_user',
        ),
        migrations.AlterModelOptions(
            name='userreferral',
            options={'ordering': ['-created_at'], 'verbose_name': 'User Referral', 'verbose_name_plural': 'User Referrals'},
        ),
        migrations.AlterField(
            model_name='userreferral',
            name='referrer_user',
            field=models.ForeignKey(
                blank=True,
                help_text='Usuario de Confío que hizo la invitación (si está registrado)',
                null=True,
                on_delete=models.SET_NULL,
                related_name='referrals_as_referrer',
                to='users.user',
            ),
        ),
        migrations.AlterField(
            model_name='userreferral',
            name='status',
            field=models.CharField(
                choices=[('pending', 'Pendiente'), ('active', 'Activo'), ('converted', 'Convertido'), ('inactive', 'Inactivo')],
                default='active',
                max_length=20,
            ),
        ),
    ]
