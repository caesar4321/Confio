from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ramps', '0003_rename_ramps_rampt_provide_e3d64c_idx_ramps_rampt_provide_c12b6c_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='RampWebhookEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(choices=[('koywe', 'Koywe'), ('guardarian', 'Guardarian')], max_length=20)),
                ('event_id', models.CharField(max_length=120, unique=True)),
                ('event_type', models.CharField(blank=True, max_length=120)),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('processed_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-processed_at'],
            },
        ),
        migrations.AddIndex(
            model_name='rampwebhookevent',
            index=models.Index(fields=['provider', 'processed_at'], name='ramps_ramp_provide_8e5d53_idx'),
        ),
        migrations.AddIndex(
            model_name='rampwebhookevent',
            index=models.Index(fields=['event_type', 'processed_at'], name='ramps_ramp_event_t_1f9d0d_idx'),
        ),
    ]
