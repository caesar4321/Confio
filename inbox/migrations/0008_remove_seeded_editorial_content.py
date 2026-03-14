from django.db import migrations


SEEDED_TITLES = [
    'Argentina tiene uno de los Big Mac mas caros. Y eso no significa que Argentina sea rica.',
    'Confío x Didit - demo video. Ahora verificación de identidad en tiempo real',
    'Integracion Koywe completada',
    'Confío x Didit: verificación en tiempo real',
    'Fase 1-1 activa: $CONFIO a $0.20',
]

SEEDED_BODIES = [
    'Estamos a punto de cerrar el trato con los bancos locales. Vienen en 2-4 semanas.',
]


def remove_seeded_editorial_content(apps, schema_editor):
    ContentItem = apps.get_model('inbox', 'ContentItem')

    ContentItem.objects.filter(
        owner_type='SYSTEM',
        title__in=SEEDED_TITLES,
    ).delete()
    ContentItem.objects.filter(
        owner_type='SYSTEM',
        body__in=SEEDED_BODIES,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0007_contentitem_push_sent_at'),
    ]

    operations = [
        migrations.RunPython(remove_seeded_editorial_content, migrations.RunPython.noop),
    ]
