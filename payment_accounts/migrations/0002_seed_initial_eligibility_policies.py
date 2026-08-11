import datetime

from django.db import migrations


EFFECTIVE_FROM = datetime.datetime(2026, 8, 11, tzinfo=datetime.timezone.utc)


def seed_policies(apps, schema_editor):
    Policy = apps.get_model('payment_accounts', 'EligibilityPolicy')
    Rule = apps.get_model('payment_accounts', 'EligibilityRule')
    cobre = Policy.objects.create(
        provider='cobre', scope='account_opening', version=1, is_active=True,
        default_decision='review', default_reason_code='cobre_eligibility_not_confirmed',
        description=(
            'Venezuelan nationals are eligible when resident in Colombia, not Venezuela. '
            'Other cohorts require the written provider matrix.'
        ), effective_from=EFFECTIVE_FROM,
    )
    Rule.objects.bulk_create([
        Rule(
            policy=cobre, priority=10, decision='block',
            reason_code='cobre_residence_country_not_supported',
            residence_countries=['VEN'],
            message='Cobre account access is not available to residents of Venezuela.',
        ),
        Rule(
            policy=cobre, priority=20, decision='allow',
            reason_code='cobre_venezuelan_resident_in_colombia',
            nationalities=['VEN'], residence_countries=['COL'], account_countries=['COL'],
            message='Venezuelan national resident in Colombia is eligible.',
        ),
        Rule(
            policy=cobre, priority=30, decision='block',
            reason_code='cobre_venezuelan_residence_not_supported',
            nationalities=['VEN'],
            message='Venezuelan nationals are supported only when resident in Colombia.',
        ),
        Rule(
            policy=cobre, priority=40, decision='allow',
            reason_code='cobre_colombia_resident',
            residence_countries=['COL'], account_countries=['COL'],
            message='Colombia residents may open a Cobre Colombia balance.',
        ),
    ])
    cobre_instruction = Policy.objects.create(
        provider='cobre', scope='funding_instruction', version=1, is_active=True,
        default_decision='review',
        default_reason_code='cobre_funding_instruction_eligibility_not_confirmed',
        description=(
            'Bre-B keys are available to Venezuelan nationals resident in Colombia. '
            'Residents of Venezuela are blocked.'
        ),
        effective_from=EFFECTIVE_FROM,
    )
    Rule.objects.bulk_create([
        Rule(
            policy=cobre_instruction, priority=10, decision='block',
            reason_code='cobre_residence_country_not_supported',
            residence_countries=['VEN'],
            message='Cobre Bre-B keys are not available to residents of Venezuela.',
        ),
        Rule(
            policy=cobre_instruction, priority=20, decision='allow',
            reason_code='cobre_venezuelan_resident_in_colombia',
            nationalities=['VEN'], residence_countries=['COL'], account_countries=['COL'],
            message='Venezuelan national resident in Colombia may receive a Bre-B key.',
        ),
        Rule(
            policy=cobre_instruction, priority=30, decision='block',
            reason_code='cobre_venezuelan_residence_not_supported',
            nationalities=['VEN'],
            message='Venezuelan nationals are supported only when resident in Colombia.',
        ),
        Rule(
            policy=cobre_instruction, priority=40, decision='allow',
            reason_code='cobre_colombia_resident',
            residence_countries=['COL'], account_countries=['COL'],
            message='Colombia residents may receive a Cobre Bre-B key.',
        ),
    ])
    cobre_payout = Policy.objects.create(
        provider='cobre', scope='payout', version=1, is_active=True,
        default_decision='review', default_reason_code='cobre_payout_corridor_not_confirmed',
        description='Initial confirmed Cobre Bre-B payout corridor: Colombia COP to Colombia.',
        effective_from=EFFECTIVE_FROM,
    )
    Rule.objects.bulk_create([
        Rule(
            policy=cobre_payout, priority=10, decision='block',
            reason_code='cobre_destination_country_not_supported',
            destination_countries=['VEN'],
            message='Cobre payouts into Venezuela are not supported.',
        ),
        Rule(
            policy=cobre_payout, priority=20, decision='allow',
            reason_code='cobre_colombia_breb_payout',
            account_countries=['COL'], destination_countries=['COL'],
            message='Cobre Colombia Bre-B payout is supported.',
        ),
    ])
    infinia = Policy.objects.create(
        provider='infinia', scope='account_opening', version=1, is_active=True,
        default_decision='allow', default_reason_code='infinia_supported_non_venezuelan',
        description=(
            'Venezuelan nationality is unsupported regardless of document or residence. '
            'Other cohorts require the written provider matrix.'
        ), effective_from=EFFECTIVE_FROM,
    )
    Rule.objects.create(
        policy=infinia, priority=10, decision='block',
        reason_code='infinia_nationality_not_supported', nationalities=['VEN'],
        message='Infinia does not currently support Venezuelan nationals.',
    )
    infinia_payout = Policy.objects.create(
        provider='infinia', scope='payout', version=1, is_active=True,
        default_decision='allow', default_reason_code='infinia_supported_non_venezuelan',
        description=(
            'Venezuelan nationality is unsupported. Provider account capabilities '
            'and typed destination validation govern supported payout routes.'
        ),
        effective_from=EFFECTIVE_FROM,
    )
    Rule.objects.create(
        policy=infinia_payout, priority=10, decision='block',
        reason_code='infinia_nationality_not_supported', nationalities=['VEN'],
        message='Infinia does not currently support Venezuelan nationals.',
    )
    cobre_conversion = Policy.objects.create(
        provider='cobre', scope='conversion', version=1, is_active=True,
        default_decision='review',
        default_reason_code='cobre_stablefx_contract_not_confirmed',
        description=(
            'StableFX is limited to contracted usd_stable/COPco balances. '
            'It does not accept an end-user Bre-B COP balance directly.'
        ), effective_from=EFFECTIVE_FROM,
    )
    Rule.objects.bulk_create([
        Rule(
            policy=cobre_conversion, priority=10, decision='block',
            reason_code='cobre_residence_country_not_supported',
            residence_countries=['VEN'],
            message='Cobre access is not available to residents of Venezuela.',
        ),
        Rule(
            policy=cobre_conversion, priority=20, decision='block',
            reason_code='cobre_destination_country_not_supported',
            destination_countries=['VEN'],
            message='Cobre money movement into Venezuela is not supported.',
        ),
    ])
    infinia_conversion = Policy.objects.create(
        provider='infinia', scope='conversion', version=1, is_active=True,
        default_decision='allow', default_reason_code='infinia_supported_non_venezuelan',
        description='Infinia internal transfers are governed by account capabilities.',
        effective_from=EFFECTIVE_FROM,
    )
    Rule.objects.create(
        policy=infinia_conversion, priority=10, decision='block',
        reason_code='infinia_nationality_not_supported', nationalities=['VEN'],
        message='Infinia does not currently support Venezuelan nationals.',
    )


def remove_seeded_policies(apps, schema_editor):
    apps.get_model('payment_accounts', 'EligibilityPolicy').objects.filter(
        provider__in=['cobre', 'infinia'],
        scope__in=['account_opening', 'funding_instruction', 'payout', 'conversion'],
        version=1,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('payment_accounts', '0001_initial')]
    operations = [migrations.RunPython(seed_policies, remove_seeded_policies)]
