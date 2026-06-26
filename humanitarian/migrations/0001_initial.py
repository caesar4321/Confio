import django.core.validators
import django.db.models.deletion
import django.utils.timezone
import humanitarian.models
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


def create_initial_venezuela_campaign(apps, schema_editor):
    HumanitarianCampaign = apps.get_model('humanitarian', 'HumanitarianCampaign')
    HumanitarianCampaign.objects.get_or_create(
        slug='venezuela-2026-earthquake',
        defaults={
            'title': 'Venezuela: ayuda humanitaria',
            'country_code': 'VEN',
            'description': 'Donaciones y liberaciones transparentes para voluntarios verificados en Venezuela.',
            'status': 'active',
        },
    )


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='HumanitarianCampaign',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.CharField(default=humanitarian.models.generate_public_id, editable=False, max_length=32, unique=True)),
                ('slug', models.SlugField(max_length=80, unique=True)),
                ('title', models.CharField(max_length=160)),
                ('country_code', models.CharField(default='VEN', max_length=3)),
                ('description', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('active', 'Active'), ('paused', 'Paused'), ('closed', 'Closed')], db_index=True, default='draft', max_length=20)),
                ('goal_amount', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=14)),
                ('total_donated', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=14)),
                ('total_released', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=14)),
                ('donation_count', models.PositiveIntegerField(default=0)),
                ('release_count', models.PositiveIntegerField(default=0)),
                ('algorand_app_id', models.PositiveBigIntegerField(blank=True, null=True)),
                ('vault_address', models.CharField(blank=True, default='', max_length=66)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='HumanitarianDonation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.CharField(default=humanitarian.models.generate_public_id, editable=False, max_length=32, unique=True)),
                ('donor_display_name', models.CharField(blank=True, max_length=160)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))])),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('confirmed', 'Confirmed'), ('failed', 'Failed')], db_index=True, default='pending', max_length=20)),
                ('from_address', models.CharField(blank=True, default='', max_length=66)),
                ('transaction_hash', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('donated_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('campaign', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='donations', to='humanitarian.humanitariancampaign')),
                ('donor_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-donated_at']},
        ),
        migrations.CreateModel(
            name='HumanitarianVolunteerApplication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.CharField(default=humanitarian.models.generate_public_id, editable=False, max_length=32, unique=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('suspended', 'Suspended')], db_index=True, default='pending', max_length=20)),
                ('service_area', models.CharField(blank=True, max_length=160)),
                ('local_phone', models.CharField(blank=True, max_length=40)),
                ('notes', models.TextField(blank=True)),
                ('admin_notes', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('campaign', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='volunteer_applications', to='humanitarian.humanitariancampaign')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_humanitarian_applications', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='humanitarian_applications', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at'], 'unique_together': {('user', 'campaign')}},
        ),
        migrations.CreateModel(
            name='HumanitarianRelease',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.CharField(default=humanitarian.models.generate_public_id, editable=False, max_length=32, unique=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))])),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('submitted', 'Submitted'), ('confirmed', 'Confirmed'), ('failed', 'Failed'), ('proof_pending', 'Proof pending'), ('proof_published', 'Proof published'), ('cancelled', 'Cancelled')], db_index=True, default='draft', max_length=20)),
                ('purpose', models.CharField(max_length=240)),
                ('recipient_address', models.CharField(max_length=66)),
                ('transaction_hash', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('admin_note', models.TextField(blank=True)),
                ('public_note', models.TextField(blank=True)),
                ('released_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('campaign', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='releases', to='humanitarian.humanitariancampaign')),
                ('released_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='humanitarian_releases_sent', to=settings.AUTH_USER_MODEL)),
                ('volunteer_application', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='releases', to='humanitarian.humanitarianvolunteerapplication')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='HumanitarianProofLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('url', models.URLField(max_length=600)),
                ('title', models.CharField(blank=True, max_length=180)),
                ('platform', models.CharField(blank=True, help_text='TikTok, Instagram, YouTube, X, etc.', max_length=40)),
                ('is_public', models.BooleanField(default=True)),
                ('position', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('added_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('release', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='proof_links', to='humanitarian.humanitarianrelease')),
            ],
            options={'ordering': ['position', 'created_at']},
        ),
        migrations.AddIndex(model_name='humanitariancampaign', index=models.Index(fields=['status', '-created_at'], name='humanitaria_status_6dd748_idx')),
        migrations.AddIndex(model_name='humanitariancampaign', index=models.Index(fields=['slug'], name='humanitaria_slug_249acb_idx')),
        migrations.AddIndex(model_name='humanitariandonation', index=models.Index(fields=['campaign', 'status', '-donated_at'], name='humanitaria_campaig_775542_idx')),
        migrations.AddIndex(model_name='humanitariandonation', index=models.Index(fields=['transaction_hash'], name='humanitaria_transac_d739fa_idx')),
        migrations.AddIndex(model_name='humanitarianvolunteerapplication', index=models.Index(fields=['campaign', 'status', '-created_at'], name='humanitaria_campaig_ca1fce_idx')),
        migrations.AddIndex(model_name='humanitarianvolunteerapplication', index=models.Index(fields=['user', '-created_at'], name='humanitaria_user_id_5573f0_idx')),
        migrations.AddIndex(model_name='humanitarianrelease', index=models.Index(fields=['campaign', 'status', '-created_at'], name='humanitaria_campaig_a0f659_idx')),
        migrations.AddIndex(model_name='humanitarianrelease', index=models.Index(fields=['recipient_address'], name='humanitaria_recipie_523099_idx')),
        migrations.AddIndex(model_name='humanitarianrelease', index=models.Index(fields=['transaction_hash'], name='humanitaria_transac_93dab8_idx')),
        migrations.AddIndex(model_name='humanitarianprooflink', index=models.Index(fields=['release', 'is_public', 'position'], name='humanitaria_release_843b15_idx')),
        migrations.RunPython(create_initial_venezuela_campaign, reverse_code=migrations.RunPython.noop),
    ]
