import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0030_smart_account_trades'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='communityactivityshare',
            name='unified_transaction',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='community_shares', to='users.unifiedtransactiontable'),
        ),
        migrations.AddField(
            model_name='communityactivityshare',
            name='account_trade',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='community_shares', to='inbox.smartaccounttrade'),
        ),
    ]
