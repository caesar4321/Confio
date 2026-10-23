from django.db import migrations

# A broad starting taxonomy of physical goods sold by small LATAM sellers.
# Admin-managed afterwards (MarketplaceCategory): add, rename, reorder or
# hide without a release. The eight original keys are kept as-is so existing
# listings stay valid. Prohibited goods (medicines, alcohol, weapons, live
# animals, counterfeits…) are deliberately absent; moderation rejects them.
GROUPS = [
    ('Moda y accesorios', [
        ('ropa_mujer', 'Ropa de mujer', 'shopping-bag'),
        ('ropa_hombre', 'Ropa de hombre', 'shopping-bag'),
        ('ropa_ninos', 'Ropa de niños y bebés', 'smile'),
        ('calzado', 'Calzado', 'navigation'),
        ('bolsos', 'Bolsos, carteras y mochilas', 'briefcase'),
        ('joyeria', 'Joyería y bisutería', 'star'),
        ('accesorios', 'Accesorios', 'watch'),
    ]),
    ('Artesanía y regalos', [
        ('artesanias', 'Artesanías', 'feather'),
        ('textiles', 'Textiles y tejidos', 'layers'),
        ('arte', 'Arte y cuadros', 'image'),
        ('regalos', 'Regalos y detalles', 'gift'),
        ('fiestas', 'Fiestas y decoración de eventos', 'award'),
    ]),
    ('Hogar', [
        ('hogar', 'Hogar y decoración', 'home'),
        ('cocina', 'Cocina y vajilla', 'coffee'),
        ('muebles', 'Muebles', 'box'),
        ('plantas', 'Plantas y jardín', 'sun'),
        ('limpieza', 'Limpieza del hogar', 'droplet'),
    ]),
    ('Comida envasada', [
        ('alimentos', 'Alimentos envasados', 'package'),
        ('dulces', 'Dulces, chocolates y repostería envasada', 'heart'),
        ('cafe', 'Café, té, hierbas y especias', 'coffee'),
        ('conservas', 'Mermeladas, salsas y conservas', 'archive'),
    ]),
    ('Belleza y cuidado', [
        ('belleza', 'Belleza y maquillaje', 'smile'),
        ('cuidado_personal', 'Jabones y cuidado personal', 'droplet'),
        ('perfumes', 'Perfumes y aromas', 'wind'),
    ]),
    ('Niños y bebés', [
        ('juguetes', 'Juguetes', 'gift'),
        ('bebes', 'Artículos para bebés', 'smile'),
        ('escolar', 'Útiles escolares', 'edit-3'),
    ]),
    ('Tecnología', [
        ('electronica', 'Electrónica', 'cpu'),
        ('celular_accesorios', 'Accesorios para celular', 'smartphone'),
    ]),
    ('Deporte y tiempo libre', [
        ('deportes', 'Deportes y fitness', 'activity'),
        ('libros', 'Libros y papelería', 'book'),
        ('musica', 'Música e instrumentos', 'music'),
    ]),
    ('Mascotas', [
        ('mascotas', 'Accesorios y alimento para mascotas', 'heart'),
    ]),
    ('Otros', [
        ('herramientas', 'Herramientas y ferretería', 'tool'),
        ('autos', 'Repuestos y accesorios para auto', 'truck'),
        ('otros', 'Otros', 'tag'),
    ]),
]


def seed(apps, schema_editor):
    Category = apps.get_model('marketplace', 'MarketplaceCategory')
    for group_order, (group, items) in enumerate(GROUPS, start=1):
        for sort_order, (key, label, icon) in enumerate(items, start=1):
            Category.objects.update_or_create(key=key, defaults={
                'label': label, 'group': group, 'group_order': group_order * 10,
                'sort_order': sort_order * 10, 'icon': icon, 'is_active': True})


class Migration(migrations.Migration):
    dependencies = [('marketplace', '0004_marketplacecategory_alter_product_category')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
