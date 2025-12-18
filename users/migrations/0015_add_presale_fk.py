from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('users', '0014_unifiedtransactiontable_referral_reward_event'),
    ]
    operations = [
        migrations.AddField(
            model_name='unifiedtransactiontable',
            name='presale_purchase',
            field=models.OneToOneField(
                to='presale.PresalePurchase',
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='unified_transaction',
            ),
        ),
    ]
