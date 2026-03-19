from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ramps', '0001_initial'),
        ('users', '0017_bankinfo_provider_metadata'),
    ]

    operations = [
        migrations.AddField(
            model_name='bankinfo',
            name='ramp_payment_method',
            field=models.ForeignKey(
                blank=True,
                help_text='Ramp payment method owned by the ramps domain',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='user_bank_infos',
                to='ramps.ramppaymentmethod',
            ),
        ),
    ]

