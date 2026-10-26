from django.db import migrations, models


def seed(apps, schema_editor):
    Category = apps.get_model('marketplace', 'MarketplaceCategory')
    food = Category.objects.filter(key='alimentos').first()
    Category.objects.update_or_create(key='bebidas_alcoholicas', defaults={
        'label': 'Vinos, cervezas y licores', 'group': food.group if food else 'Comida envasada',
        'group_order': food.group_order if food else 30, 'sort_order': 50, 'icon': 'droplet',
        'is_active': True, 'age_restricted': True})


class Migration(migrations.Migration):
    dependencies = [('marketplace', '0011_delivery_pin')]
    operations = [
        migrations.AddField(
            model_name='marketplacecategory', name='age_restricted',
            field=models.BooleanField(default=False, help_text='Adults only: buyers must be of legal age (verified ID)'),
        ),
        migrations.AddField(
            model_name='order', name='age_restricted',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
