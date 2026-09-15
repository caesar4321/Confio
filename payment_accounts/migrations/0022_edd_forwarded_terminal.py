from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('payment_accounts', '0021_journey_wallet_conversion')]

    operations = [
        migrations.RemoveConstraint(
            model_name='limitincreaserequest', name='limit_increase_one_open_uniq'),
        migrations.AddConstraint(
            model_name='limitincreaserequest',
            constraint=models.UniqueConstraint(
                fields=('confio_account',),
                condition=models.Q(status__in=['started', 'submitted', 'in_review']),
                name='limit_increase_one_open_uniq')),
    ]
