from django.db import migrations


def seed_venezuela_volunteer_copy(apps, schema_editor):
    HumanitarianCampaign = apps.get_model('humanitarian', 'HumanitarianCampaign')
    HumanitarianCampaign.objects.filter(slug='venezuela-2026-earthquake').update(
        volunteer_section_title='Voluntarios en Venezuela',
        volunteer_section_subtitle=(
            '¿Estás en Venezuela y puedes comprar y entregar ayuda? Postúlate aquí. '
            'Confirmamos tu identidad antes de enviarte fondos, para que cada donación '
            'llegue a personas reales.'
        ),
        volunteer_service_area_placeholder='Zona donde puedes ayudar',
        volunteer_notes_placeholder='Qué puedes comprar o distribuir',
        volunteer_cta_label='Postular como voluntario',
    )


def clear_venezuela_volunteer_copy(apps, schema_editor):
    HumanitarianCampaign = apps.get_model('humanitarian', 'HumanitarianCampaign')
    HumanitarianCampaign.objects.filter(slug='venezuela-2026-earthquake').update(
        volunteer_section_title='',
        volunteer_section_subtitle='',
        volunteer_service_area_placeholder='Zona donde puedes ayudar',
        volunteer_notes_placeholder='Qué puedes comprar o distribuir',
        volunteer_cta_label='Postular como voluntario',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('humanitarian', '0002_humanitariancampaign_volunteer_section_copy'),
    ]

    operations = [
        migrations.RunPython(seed_venezuela_volunteer_copy, clear_venezuela_volunteer_copy),
    ]
