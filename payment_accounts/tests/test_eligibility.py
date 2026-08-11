from django.test import TestCase
from django.utils import timezone

from payment_accounts.eligibility import (
    EligibilityContext,
    EligibilityPolicyNotConfigured,
    evaluate_active_policy,
    evaluate_policy,
)
from payment_accounts.models import EligibilityPolicy, EligibilityRule


class ProviderEligibilityTests(TestCase):
    def _policy(self, provider, *, default='block'):
        EligibilityPolicy.objects.filter(
            provider=provider, scope='account_opening', is_active=True
        ).update(is_active=False)
        return EligibilityPolicy.objects.create(
            provider=provider,
            scope='account_opening',
            version=99,
            is_active=True,
            default_decision=default,
            effective_from=timezone.now(),
        )

    def test_cobre_allows_venezuelan_resident_in_colombia(self):
        policy = self._policy('cobre')
        EligibilityRule.objects.create(
            policy=policy,
            priority=10,
            decision='allow',
            reason_code='venezuelan_resident_in_colombia',
            nationalities=['VEN'],
            residence_countries=['COL'],
            account_countries=['COL'],
            document_types=['national_id'],
        )

        result = evaluate_policy(
            policy,
            EligibilityContext(
                nationality='ven',
                residence_country='col',
                account_country='col',
                document_type='national_id',
                document_issuing_country='VEN',
            ),
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.reason_code, 'venezuelan_resident_in_colombia')

    def test_cobre_does_not_allow_same_nationality_inside_venezuela(self):
        policy = self._policy('cobre')
        EligibilityRule.objects.create(
            policy=policy,
            priority=10,
            decision='allow',
            reason_code='venezuelan_resident_in_colombia',
            nationalities=['VEN'],
            residence_countries=['COL'],
            account_countries=['COL'],
        )

        result = evaluate_policy(
            policy,
            EligibilityContext(
                nationality='VEN', residence_country='VEN', account_country='COL'
            ),
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason_code, 'no_matching_eligibility_rule')

    def test_infinia_can_block_venezuelan_nationality_regardless_of_passport(self):
        policy = self._policy('infinia', default='review')
        EligibilityRule.objects.create(
            policy=policy,
            priority=10,
            decision='block',
            reason_code='nationality_not_supported',
            nationalities=['VEN'],
        )

        result = evaluate_policy(
            policy,
            EligibilityContext(
                nationality='VEN',
                residence_country='COL',
                account_country='COL',
                document_type='passport',
                document_issuing_country='VEN',
            ),
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.decision, 'block')
        self.assertEqual(result.reason_code, 'nationality_not_supported')

    def test_payout_policy_can_block_destination_independently_from_residence(self):
        EligibilityPolicy.objects.filter(
            provider='cobre', scope='payout', is_active=True
        ).update(is_active=False)
        policy = EligibilityPolicy.objects.create(
            provider='cobre',
            scope='payout',
            version=99,
            is_active=True,
            default_decision='allow',
            effective_from=timezone.now(),
        )
        EligibilityRule.objects.create(
            policy=policy,
            priority=10,
            decision='block',
            reason_code='destination_country_not_supported',
            destination_countries=['VEN'],
        )

        result = evaluate_policy(
            policy,
            EligibilityContext(
                nationality='VEN',
                residence_country='COL',
                account_country='COL',
                destination_country='VEN',
            ),
        )

        self.assertEqual(result.decision, 'block')
        self.assertEqual(result.reason_code, 'destination_country_not_supported')

    def test_first_matching_rule_makes_exception_order_explicit(self):
        policy = self._policy('cobre')
        EligibilityRule.objects.create(
            policy=policy,
            priority=10,
            decision='allow',
            reason_code='approved_colombia_exception',
            nationalities=['VEN'],
            residence_countries=['COL'],
        )
        EligibilityRule.objects.create(
            policy=policy,
            priority=20,
            decision='block',
            reason_code='nationality_block',
            nationalities=['VEN'],
        )

        result = evaluate_policy(
            policy,
            EligibilityContext(nationality='VEN', residence_country='COL'),
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.reason_code, 'approved_colombia_exception')

    def test_missing_active_policy_fails_closed_for_the_caller(self):
        with self.assertRaises(EligibilityPolicyNotConfigured):
            evaluate_active_policy(
                provider='infinia',
                scope='payin',
                context=EligibilityContext(nationality='COL'),
            )


class SeededProviderEligibilityTests(TestCase):
    def test_seeded_cobre_policy_allows_venezuelan_in_colombia(self):
        result = evaluate_active_policy(
            provider='cobre',
            scope='account_opening',
            context=EligibilityContext(
                nationality='VEN', residence_country='COL', account_country='COL'
            ),
        )
        self.assertTrue(result.allowed)

    def test_seeded_cobre_policy_blocks_residence_in_venezuela(self):
        result = evaluate_active_policy(
            provider='cobre',
            scope='account_opening',
            context=EligibilityContext(
                nationality='VEN', residence_country='VEN', account_country='COL'
            ),
        )
        self.assertEqual(result.decision, 'block')
        self.assertEqual(result.reason_code, 'cobre_residence_country_not_supported')

    def test_seeded_infinia_policy_blocks_venezuelan_with_passport(self):
        result = evaluate_active_policy(
            provider='infinia',
            scope='account_opening',
            context=EligibilityContext(
                nationality='VEN',
                residence_country='COL',
                account_country='COL',
                document_type='passport',
            ),
        )
        self.assertEqual(result.decision, 'block')
        self.assertEqual(result.reason_code, 'infinia_nationality_not_supported')

    def test_seeded_cobre_payout_policy_allows_colombia_breb_corridor(self):
        result = evaluate_active_policy(
            provider='cobre',
            scope='payout',
            context=EligibilityContext(
                nationality='VEN',
                residence_country='COL',
                account_country='COL',
                destination_country='COL',
            ),
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason_code, 'cobre_colombia_breb_payout')

    def test_seeded_cobre_payout_policy_explicitly_blocks_venezuela(self):
        result = evaluate_active_policy(
            provider='cobre',
            scope='payout',
            context=EligibilityContext(
                nationality='VEN',
                residence_country='COL',
                account_country='COL',
                destination_country='VEN',
            ),
        )
        self.assertEqual(result.decision, 'block')
        self.assertEqual(result.reason_code, 'cobre_destination_country_not_supported')

    def test_seeded_cobre_policy_allows_other_colombia_residents(self):
        result = evaluate_active_policy(
            provider='cobre',
            scope='account_opening',
            context=EligibilityContext(
                nationality='COL', residence_country='COL', account_country='COL'
            ),
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason_code, 'cobre_colombia_resident')

    def test_seeded_infinia_policy_allows_non_venezuelan(self):
        result = evaluate_active_policy(
            provider='infinia',
            scope='account_opening',
            context=EligibilityContext(
                nationality='COL', residence_country='COL', account_country='COL'
            ),
        )
        self.assertTrue(result.allowed)

    def test_seeded_infinia_payout_blocks_venezuelan_nationality(self):
        result = evaluate_active_policy(
            provider='infinia',
            scope='payout',
            context=EligibilityContext(
                nationality='VEN', residence_country='COL', destination_country='COL'
            ),
        )
        self.assertEqual(result.decision, 'block')
