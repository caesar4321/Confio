from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('humanitarian', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='humanitariancampaign',
            name='volunteer_cta_label',
            field=models.CharField(
                blank=True,
                default='Postular como voluntario',
                help_text='Submit button label for volunteer applications.',
                max_length=80,
            ),
        ),
        migrations.AddField(
            model_name='humanitariancampaign',
            name='volunteer_notes_placeholder',
            field=models.CharField(
                blank=True,
                default='Qué puedes comprar o distribuir',
                help_text='Placeholder for the volunteer notes input.',
                max_length=160,
            ),
        ),
        migrations.AddField(
            model_name='humanitariancampaign',
            name='volunteer_section_subtitle',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Body copy shown above the volunteer application form.',
            ),
        ),
        migrations.AddField(
            model_name='humanitariancampaign',
            name='volunteer_section_title',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Title shown above the volunteer application form.',
                max_length=160,
            ),
        ),
        migrations.AddField(
            model_name='humanitariancampaign',
            name='volunteer_service_area_placeholder',
            field=models.CharField(
                blank=True,
                default='Zona donde puedes ayudar',
                help_text='Placeholder for the volunteer service area input.',
                max_length=120,
            ),
        ),
    ]
