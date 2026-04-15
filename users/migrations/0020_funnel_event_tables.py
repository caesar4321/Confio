from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0019_unifiedtransactiontable_ramp_transaction'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='FunnelEvent',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_name', models.CharField(db_index=True, help_text="Canonical event name, e.g. 'invite_submitted'", max_length=64)),
                ('session_id', models.CharField(blank=True, db_index=True, help_text="Opaque session/fingerprint id for stitching pre-signup events to post-signup ones. Typically the Worker's IP-referral key or a client-generated UUID.", max_length=64)),
                ('country', models.CharField(blank=True, db_index=True, help_text='ISO 3166-1 alpha-2; empty if unknown.', max_length=2)),
                ('platform', models.CharField(blank=True, help_text="'ios', 'android', 'web', or empty.", max_length=16)),
                ('properties', models.JSONField(blank=True, default=dict, help_text='Event-specific payload. Keep small; not indexed.')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('user', models.ForeignKey(blank=True, help_text='Authenticated user, if any. NULL for pre-signup events.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='funnel_events', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Funnel Event',
                'verbose_name_plural': 'Funnel Events (raw, 30d)',
            },
        ),
        migrations.AddIndex(
            model_name='funnelevent',
            index=models.Index(fields=['event_name', 'created_at'], name='users_funne_event_n_c6f_idx'),
        ),
        migrations.AddIndex(
            model_name='funnelevent',
            index=models.Index(fields=['country', 'event_name', 'created_at'], name='users_funne_country_eca_idx'),
        ),
        migrations.AddIndex(
            model_name='funnelevent',
            index=models.Index(fields=['user', 'event_name'], name='users_funne_user_ev_idx'),
        ),
        migrations.AddIndex(
            model_name='funnelevent',
            index=models.Index(fields=['session_id', 'event_name'], name='users_funne_session_idx'),
        ),
        migrations.CreateModel(
            name='FunnelDailyRollup',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(db_index=True)),
                ('event_name', models.CharField(db_index=True, max_length=64)),
                ('country', models.CharField(blank=True, max_length=2)),
                ('platform', models.CharField(blank=True, max_length=16)),
                ('count', models.IntegerField(help_text='Total events on this date/segment.', validators=[MinValueValidator(0)])),
                ('unique_users', models.IntegerField(help_text='Distinct authenticated users. Pre-signup events not counted here.', validators=[MinValueValidator(0)])),
                ('unique_sessions', models.IntegerField(default=0, help_text='Distinct session_ids (includes pre-signup).', validators=[MinValueValidator(0)])),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Funnel Daily Rollup',
                'verbose_name_plural': 'Funnel Daily Rollups',
            },
        ),
        migrations.AddIndex(
            model_name='funneldailyrollup',
            index=models.Index(fields=['-date', 'event_name'], name='users_funne_date_ev_idx'),
        ),
        migrations.AddIndex(
            model_name='funneldailyrollup',
            index=models.Index(fields=['event_name', 'country', '-date'], name='users_funne_ev_co_dt_idx'),
        ),
        migrations.AddConstraint(
            model_name='funneldailyrollup',
            constraint=models.UniqueConstraint(
                fields=('date', 'event_name', 'country', 'platform'),
                name='unique_funnel_rollup',
            ),
        ),
    ]
