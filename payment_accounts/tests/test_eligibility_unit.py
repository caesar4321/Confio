from types import SimpleNamespace

from django.test import SimpleTestCase

from payment_accounts.eligibility import (
    EligibilityContext,
    context_from_identity,
    evaluate_policy,
)


class _Rules:
    def __init__(self, rules):
        self.rules = rules

    def filter(self, **kwargs):
        return self

    def order_by(self, *args):
        return self.rules


def _rule(priority, decision, reason, **selectors):
    defaults = {
        'nationalities': [],
        'residence_countries': [],
        'account_countries': [],
        'document_types': [],
        'document_issuing_countries': [],
        'destination_countries': [],
    }
    defaults.update(selectors)
    return SimpleNamespace(
        priority=priority,
        decision=decision,
        reason_code=reason,
        **defaults,
    )


def _policy(*rules, default='block'):
    return SimpleNamespace(
        rules=_Rules(list(rules)),
        default_decision=default,
        default_reason_code='default',
    )


class EligibilityEngineUnitTests(SimpleTestCase):
    def test_cobre_colombia_exception_precedes_nationality_block(self):
        policy = _policy(
            _rule(
                10,
                'allow',
                'colombia_exception',
                nationalities=['VEN'],
                residence_countries=['COL'],
                account_countries=['COL'],
            ),
            _rule(20, 'block', 'nationality_block', nationalities=['VEN']),
        )
        result = evaluate_policy(
            policy,
            EligibilityContext(
                nationality='ven', residence_country='col', account_country='col'
            ),
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason_code, 'colombia_exception')

    def test_infinia_nationality_block_ignores_passport_and_residence(self):
        policy = _policy(
            _rule(10, 'block', 'nationality_block', nationalities=['VEN']),
            default='review',
        )
        result = evaluate_policy(
            policy,
            EligibilityContext(
                nationality='VEN',
                residence_country='COL',
                document_type='passport',
            ),
        )
        self.assertEqual(result.decision, 'block')

    def test_destination_is_evaluated_independently(self):
        policy = _policy(
            _rule(10, 'block', 'blocked_destination', destination_countries=['VEN']),
            default='allow',
        )
        result = evaluate_policy(
            policy,
            EligibilityContext(residence_country='COL', destination_country='VEN'),
        )
        self.assertEqual(result.reason_code, 'blocked_destination')

    def test_identity_context_uses_verified_residence_not_phone_country(self):
        identity = SimpleNamespace(
            verified_nationality='VEN',
            verified_country='COL',
            document_type='national_id',
            document_issuing_country='VEN',
        )
        context = context_from_identity(identity, account_country='COL')
        self.assertEqual(context.residence_country, 'COL')
        self.assertEqual(context.document_issuing_country, 'VEN')
