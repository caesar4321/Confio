from types import SimpleNamespace
from unittest import mock

import graphene
from django.test import SimpleTestCase, TestCase, override_settings

from payment_accounts.incoming_details import sender_details, incoming_credit
from payment_accounts.journey_schema import JourneyQuery, InfiniaDepositType
from .test_infinia_journeys import JourneyTests


class SenderDetailsTests(SimpleTestCase):
    def entry(self, sender):
        return SimpleNamespace(provider='infinia', direction='credit',
            provider_data={'third_party': sender})

    def test_allowlisted_masked_provider_fields_only(self):
        result = sender_details(self.entry({'type': 'FIAT', 'full_name': ' Ana  Pérez ',
            'bank_name': 'Banco', 'bank_code': '001', 'account_number': '1234567890',
            'source_reference': 'REF-1', 'document_number': 'secret-id', 'document_type': 'DNI'}))
        self.assertEqual(result, {'name': 'Ana Pérez', 'bank_name': 'Banco', 'bank_code': '001',
            'account_masked': '•••• 7890', 'reference': 'REF-1'})
        self.assertNotIn('secret-id', str(result))
        self.assertNotIn('1234567890', str(result))
        self.assertEqual(InfiniaDepositType.resolve_sender(self.entry({
            'type': 'FIAT', 'full_name': 'Ana Pérez'}), None)['name'], 'Ana Pérez')

    def test_missing_malformed_and_crypto_evidence_does_not_invent_sender(self):
        for sender in (None, [], 'bad', {'type': 'CRYPTO', 'full_name': 'Bridge'}):
            self.assertIsNone(sender_details(self.entry(sender)))
        result = sender_details(self.entry({'type': 'FIAT', 'full_name': {'bad': 'name'},
            'bank_name': 123, 'account_number': '1234', 'voucher_id': 'V1'}))
        self.assertEqual(result['name'], '')
        self.assertEqual(result['bank_name'], '')
        self.assertEqual(result['account_masked'], '••••')
        self.assertEqual(result['reference'], 'V1')

    def test_sender_is_only_from_the_original_local_credit(self):
        entry = self.entry({'type': 'FIAT', 'full_name': 'Ana Pérez'})
        entry.financial_account_id = 1
        journey = SimpleNamespace(direction='to_wallet', local_account_id=1, funding_credit=entry)
        self.assertIs(incoming_credit(journey), entry)
        journey.local_account_id = 2
        self.assertIsNone(incoming_credit(journey))
        journey.local_account_id = 1
        journey.direction = 'to_bank'
        self.assertIsNone(incoming_credit(journey))
        entry.direction = 'debit'
        self.assertIsNone(sender_details(entry))


@override_settings(INFINIA_JOURNEYS_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True)
class IncomingSenderSchemaTests(TestCase):
    setUp = JourneyTests.setUp
    credit = JourneyTests.credit
    inbound = JourneyTests.inbound

    def test_sender_fields_are_scoped_to_owned_journey(self):
        j = self.inbound()
        entry = j.funding_credit
        entry.provider_data = {'third_party': {'type': 'FIAT', 'full_name': 'Ana Pérez',
            'account_number': '1234567890', 'bank_name': 'Banco', 'voucher_id': 'V1'}}
        entry.save(update_fields=['provider_data'])
        schema = graphene.Schema(query=JourneyQuery)
        query = '''query($id: UUID!) { infiniaJourney(internalId: $id) {
            receivedFiatAmount sender { name bankName bankCode accountMasked reference }
        }}'''
        with mock.patch('payment_accounts.schema._active_account', return_value=self.owner):
            result = schema.execute(query, variable_values={'id': str(j.internal_id)})
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['infiniaJourney']['sender']['name'], 'Ana Pérez')
        self.assertEqual(result.data['infiniaJourney']['sender']['accountMasked'], '•••• 7890')
        self.assertEqual(float(result.data['infiniaJourney']['receivedFiatAmount']), float(entry.amount))
        other = type(self.owner)(pk=self.owner.pk + 10000)
        with mock.patch('payment_accounts.schema._active_account', return_value=other):
            result = schema.execute(query, variable_values={'id': str(j.internal_id)})
        self.assertIsNone(result.errors)
        self.assertIsNone(result.data['infiniaJourney'])
