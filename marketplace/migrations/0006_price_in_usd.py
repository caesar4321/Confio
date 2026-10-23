from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    """Products are priced in US dollars (the escrow's unit and what the seller
    receives); local currency becomes a display-only reference. Shipped while
    prod had no products or orders, so nothing is converted: the one-off
    defaults below never meet a real row."""

    dependencies = [('marketplace', '0005_seed_categories')]

    operations = [
        migrations.RemoveField(model_name='product', name='price_local'),
        migrations.RemoveField(model_name='product', name='currency_code'),
        migrations.AddField(
            model_name='product', name='price_usd',
            field=models.DecimalField(
                decimal_places=2, max_digits=12, help_text='Price in US dollars',
                validators=[django.core.validators.MinValueValidator(Decimal('0.50'))],
                default=Decimal('0')),
            preserve_default=False,
        ),
        migrations.RemoveField(model_name='order', name='unit_price_local'),
        migrations.RemoveField(model_name='order', name='subtotal_local'),
        migrations.RemoveField(model_name='order', name='currency_code'),
        migrations.RemoveField(model_name='order', name='fx_rate'),
        migrations.AddField(
            model_name='order', name='unit_price_usd',
            field=models.DecimalField(decimal_places=2, max_digits=12, default=Decimal('0')),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='order', name='delivery_currency',
            field=models.CharField(blank=True, default='', max_length=3),
        ),
    ]
