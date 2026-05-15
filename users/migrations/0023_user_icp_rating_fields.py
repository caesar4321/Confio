"""
Add ICP capture + Rating modal fields to User.

9 nullable columns + 2 partial indexes (Postgres-only). Backfill is done by a
data migration in this file: any user with a COMPLETED usdc_to_cusd Conversion
or a CONFIRMED inbound cUSD SendTransaction gets their first_cusd_acquired_at
populated with the earliest such event's timestamp. Idempotent: re-running is
a no-op because the helper writes only when the field is null.
"""
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxLengthValidator, MinValueValidator, MaxValueValidator
from django.db import migrations, models


def backfill_first_cusd_acquired(apps, schema_editor):
    """Populate first_cusd_acquired_at for existing users.

    Pulls earliest of:
      - Conversion.completed_at WHERE status='COMPLETED' AND conversion_type='usdc_to_cusd' (per actor_user)
      - SendTransaction.updated_at WHERE status='CONFIRMED' AND token_type='CUSD' (per recipient_user)

    Uses updated_at as proxy for SendTransaction since the model has no
    confirmed_at column; for CONFIRMED rows updated_at reflects the
    confirmation transition.
    """
    User = apps.get_model('users', 'User')
    Conversion = apps.get_model('conversion', 'Conversion')
    SendTransaction = apps.get_model('send', 'SendTransaction')

    earliest_by_user = {}

    conv_qs = Conversion.objects.filter(
        status='COMPLETED',
        conversion_type='usdc_to_cusd',
        actor_user__isnull=False,
        completed_at__isnull=False,
        deleted_at__isnull=True,
    ).values_list('actor_user_id', 'completed_at')
    for uid, ts in conv_qs:
        prev = earliest_by_user.get(uid)
        if prev is None or ts < prev:
            earliest_by_user[uid] = ts

    send_qs = SendTransaction.objects.filter(
        status='CONFIRMED',
        token_type='CUSD',
        recipient_user__isnull=False,
        deleted_at__isnull=True,
    ).values_list('recipient_user_id', 'updated_at')
    for uid, ts in send_qs:
        prev = earliest_by_user.get(uid)
        if prev is None or ts < prev:
            earliest_by_user[uid] = ts

    # Idempotent: only write where field is currently null
    for uid, ts in earliest_by_user.items():
        User.objects.filter(pk=uid, first_cusd_acquired_at__isnull=True).update(
            first_cusd_acquired_at=ts
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0022_funnel_rollup_cohort'),
        ('conversion', '0005_revert_algo_conversion_types_to_usdc_to_cusd'),
        ('send', '0006_alter_phoneinvite_token_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='first_cusd_acquired_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='rating_prompt_due_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='confio_icp_tags',
            field=ArrayField(
                base_field=models.CharField(max_length=64),
                blank=True, default=list, size=None,
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='confio_icp_other_text',
            field=models.TextField(
                blank=True, null=True,
                validators=[MaxLengthValidator(500)],
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='confio_icp_captured_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='confio_rating_prompted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='confio_rating_star_count',
            field=models.PositiveSmallIntegerField(
                blank=True, null=True,
                validators=[MinValueValidator(1), MaxValueValidator(5)],
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='confio_rating_action',
            field=models.CharField(
                blank=True, null=True, max_length=10,
                choices=[('FEEDBACK', 'Feedback'), ('STORE', 'Store'), ('SKIP', 'Skip')],
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='confio_rating_feedback_text',
            field=models.TextField(
                blank=True, null=True,
                validators=[MaxLengthValidator(500)],
            ),
        ),
        # Postgres-only partial indexes: cheap because nullable + filtered.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS idx_users_first_cusd_acquired "
                "ON users_user (first_cusd_acquired_at) "
                "WHERE first_cusd_acquired_at IS NOT NULL;"
            ),
            reverse_sql="DROP INDEX IF EXISTS idx_users_first_cusd_acquired;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS idx_users_dormant_rating "
                "ON users_user (confio_icp_captured_at) "
                "WHERE rating_prompt_due_at IS NULL "
                "AND confio_rating_prompted_at IS NULL;"
            ),
            reverse_sql="DROP INDEX IF EXISTS idx_users_dormant_rating;",
        ),
        migrations.RunPython(backfill_first_cusd_acquired, noop_reverse),
    ]
