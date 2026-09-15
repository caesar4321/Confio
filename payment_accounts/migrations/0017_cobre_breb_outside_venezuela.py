import datetime

from django.db import migrations


# Bre-B is for anyone, anywhere, except residents of Venezuela (Julian,
# 2026-09-15). v1 only allowed Colombia residents; payout and conversion
# already block Venezuela and stay as they are.
EFFECTIVE_FROM = datetime.datetime(2026, 9, 15, tzinfo=datetime.timezone.utc)
SCOPES = ('account_opening', 'funding_instruction')


def outside_venezuela(apps, schema_editor):
    Policy = apps.get_model('payment_accounts', 'EligibilityPolicy')
    Rule = apps.get_model('payment_accounts', 'EligibilityRule')
    for scope in SCOPES:
        # One active policy per provider/scope: deactivate the others first.
        Policy.objects.filter(provider='cobre', scope=scope, is_active=True).exclude(version=2).update(is_active=False)
        kept = Policy.objects.filter(provider='cobre', scope=scope, version=2).first()
        if kept:
            # Re-applied after a rollback: v2 was kept (decisions reference it).
            Policy.objects.filter(pk=kept.pk).update(is_active=True)
            continue
        policy = Policy.objects.create(
            provider='cobre', scope=scope, version=2, is_active=True,
            default_decision='allow', default_reason_code='cobre_breb_outside_venezuela',
            description=(
                'Bre-B is available from anywhere except Venezuela: residents of Venezuela are '
                'blocked, everyone else may apply. The app also confirms the device is not in Venezuela.'
            ),
            effective_from=EFFECTIVE_FROM,
        )
        Rule.objects.create(
            policy=policy, priority=10, decision='block',
            reason_code='cobre_residence_country_not_supported', residence_countries=['VEN'],
            message='Bre-B no está disponible para residentes de Venezuela.',
        )


def colombia_only(apps, schema_editor):
    Policy = apps.get_model('payment_accounts', 'EligibilityPolicy')
    for scope in SCOPES:
        # v2 stays as evidence (eligibility decisions reference it, PROTECT);
        # it is only deactivated, before v1 becomes the active policy again.
        Policy.objects.filter(provider='cobre', scope=scope, version=2).update(is_active=False)
        Policy.objects.filter(provider='cobre', scope=scope, version=1).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [('payment_accounts', '0016_brebappattestkey')]
    operations = [migrations.RunPython(outside_venezuela, colombia_only)]
