from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('users', '0014_unifiedtransactiontable_referral_reward_event'),
        # Cross-app FK target must exist before this AddField runs on a
        # fresh database (test runs); live DBs already satisfied it by time.
        ('presale', '0001_initial'),
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
