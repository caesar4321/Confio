from django.db import migrations, models


TOKENS = [
    ('CUSD', 'Confío Dollar'),
    ('CONFIO', 'Confío Token'),
    ('USDC', 'USD Coin'),
    ('CUSD_PLUS', 'Confío Dollar Plus'),
    ('CUSD_BSC', 'Confío Dollar (BSC)'),
    ('USDT', 'Tether USD (BSC)'),
]


class Migration(migrations.Migration):
    dependencies = [('payroll', '0007_payrollitem_settled_amount')]

    operations = [
        migrations.AlterField(
            model_name='payrollrun',
            name='token_type',
            field=models.CharField(max_length=10, choices=TOKENS, default='CUSD'),
        ),
        migrations.AlterField(
            model_name='payrollitem',
            name='token_type',
            field=models.CharField(max_length=10, choices=TOKENS, default='CUSD'),
        ),
    ]
