"""Backfill UserReferral.cohort from attribution_data / referrer_identifier.

Runs once. Idempotent: rows that already have a non-empty cohort are skipped.
"""
from django.db import migrations


CREATOR_REFERRAL_CODE = 'JULIANMOONLUNA'


def _derive_cohort_for_row(row_attribution_data, row_referrer_identifier):
    """Mirror of UserReferral._derive_cohort for backfill use.

    Kept inline (not imported) so this migration is self-contained and survives
    future model changes.
    """
    data = row_attribution_data or {}
    source_type = str(data.get('source_type') or '').lower()
    referral_code = (
        str(data.get('referral_code') or '').strip().upper()
        or str((data.get('properties') or {}).get('referral_code') or '').strip().upper()
    )
    ident = (row_referrer_identifier or '').strip().upper()

    if source_type == 'send_invite':
        return 'send_invite'
    if source_type == 'referral_link':
        if referral_code == CREATOR_REFERRAL_CODE or ident == CREATOR_REFERRAL_CODE:
            return 'creator_julianmoonluna'
        if referral_code or ident:
            return 'user_driven'
        return 'organic'
    # No source_type on attribution_data — fall back to identifier
    if ident == CREATOR_REFERRAL_CODE:
        return 'creator_julianmoonluna'
    if ident:
        return 'user_driven'
    return 'organic'


def forward(apps, schema_editor):
    UserReferral = apps.get_model('achievements', 'UserReferral')
    qs = UserReferral.objects.filter(cohort='')
    updated = 0
    for row in qs.iterator(chunk_size=500):
        cohort = _derive_cohort_for_row(row.attribution_data, row.referrer_identifier)
        if cohort:
            row.cohort = cohort[:32]
            row.save(update_fields=['cohort'])
            updated += 1
    print(f"  backfilled cohort for {updated} UserReferral rows")


def reverse(apps, schema_editor):
    # Non-destructive: clear the column so a re-run of the forward migration repopulates.
    UserReferral = apps.get_model('achievements', 'UserReferral')
    UserReferral.objects.exclude(cohort='').update(cohort='')


class Migration(migrations.Migration):

    dependencies = [
        ('achievements', '0016_add_userreferral_cohort_index'),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
