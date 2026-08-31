from types import SimpleNamespace
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings

from payment_accounts.providers.cobre import CobreProvider
from payment_accounts.providers.common import account_status, operation_status
from payment_accounts.providers.infinia import InfiniaProvider


class StatusNormalizationTests(SimpleTestCase):
    def test_cobre_nested_status_is_normalized(self):
        self.assertEqual(
            operation_status({'status': {'state': 'pending_approval'}}),
            ('needs_review', 'PENDING_APPROVAL'),
        )

    def test_infinia_account_lifecycle_is_normalized(self):
        self.assertEqual(account_status({'status': 'PROVISIONING'}), ('pending', 'PROVISIONING'))
        self.assertEqual(account_status({'status': 'ACTIVE'}), ('active', 'ACTIVE'))


class AdapterPayloadTests(SimpleTestCase):
    @mock.patch('payment_accounts.providers.infinia.build_infinia_self_declared_payload')
    @mock.patch('payment_accounts.providers.infinia.retrieve_didit_decision')
    def test_infinia_owner_uses_didit_self_declared_handoff(
        self, retrieve_decision, build_payload
    ):
        client = mock.Mock()
        client.find_owner.return_value = []
        client.create_owner.return_value = {'id': 'owner_1', 'status': 'COMPLETED'}
        retrieve_decision.return_value = {'status': 'Approved', 'session_kind': 'user'}
        build_payload.return_value = (
            {
                'type': 'INDIVIDUAL',
                'kyc_mode': 'SELF_DECLARED',
                'idempotency_key': 'profile-id',
                'individual': {'identity_document_id': 'doc_1'},
            },
            [{'document_id': 'doc_1', 'front_sha256': 'hash'}],
        )
        profile = SimpleNamespace(
            internal_id='profile-id',
            owner_type='individual',
            kyc_mode='SELF_DECLARED',
            provider_data={'compliance_consent': {'granted': True}},
            identity_verification=SimpleNamespace(
                risk_factors={'didit': {'session_id': 'didit_1'}}
            ),
            confio_account=SimpleNamespace(
                user=SimpleNamespace(id=7), business_id=None
            ),
        )

        result = InfiniaProvider(client=client).provision_profile(profile)

        self.assertEqual(result.status, 'active')
        self.assertEqual(client.create_owner.call_args.args[0]['kyc_mode'], 'SELF_DECLARED')
        retrieve_decision.assert_called_once_with(
            session_id='didit_1',
            expected_user=profile.confio_account.user,
            expected_account_type='personal',
            expected_business_id=None,
        )

    def test_infinia_owner_recovers_by_idempotency_before_reuploading_documents(self):
        client = mock.Mock()
        client.find_owner.return_value = [{'id': 'owner_1', 'status': 'COMPLETED'}]
        profile = SimpleNamespace(
            internal_id='profile-id',
            kyc_mode='SELF_DECLARED',
            provider_data={'compliance_consent': {'granted': True}},
        )

        result = InfiniaProvider(client=client).provision_profile(profile)

        self.assertEqual(result.resource_id, 'owner_1')
        client.create_owner.assert_not_called()

    def test_cobre_reuses_account_found_by_stable_alias(self):
        client = mock.Mock()
        client.find_account.return_value = [{'id': 'acc_1', 'obtained_balance': 123, 'connectivity': {'status': 'connected'}}]
        account = SimpleNamespace(
            internal_id='local-id',
            country='COL',
            asset='COP',
            provider_profile=SimpleNamespace(confio_account_id=7),
        )

        result = CobreProvider(client=client).provision_account(account)

        self.assertEqual(result.resource_id, 'acc_1')
        self.assertEqual(str(result.current_balance), '1.23')
        client.create_account.assert_not_called()

    def test_infinia_payout_uses_origin_id_and_named_source_account(self):
        client = mock.Mock()
        client.create_payout.return_value = {'id': 'po_1', 'status': 'IN_PROGRESS'}
        operation = SimpleNamespace(
            idempotency_key='idem',
            source_amount=Decimal('100.00'),
            source_account=SimpleNamespace(provider_account_id='account_1'),
            external_destination={'destination_account': {'country': 'CO'}},
        )

        result = InfiniaProvider(client=client).create_payout(operation)

        payload = client.create_payout.call_args.args[0]
        self.assertEqual(payload, {
            'originId': 'idem',
            'amount': 100.0,
            'sourceAccountId': 'account_1',
            'destinationAccount': {'country': 'CO'},
        })
        self.assertEqual(result.status, 'processing')

    def test_infinia_completed_transfer_remains_settling_until_credit(self):
        client = mock.Mock()
        client.create_internal_transfer.return_value = {
            'id': 'it_1', 'status': 'COMPLETED'
        }
        operation = SimpleNamespace(
            idempotency_key='idem',
            source_amount=10,
            source_account=SimpleNamespace(provider_account_id='source'),
            destination_account=SimpleNamespace(provider_account_id='target'),
            provider_data={},
        )

        result = InfiniaProvider(client=client).create_transfer(operation)

        self.assertEqual(result.status, 'settling')

    def test_infinia_transfer_passes_full_provider_amount_without_platform_fee(self):
        client = mock.Mock()
        client.create_internal_transfer.return_value = {
            'id': 'it_2', 'status': 'IN_PROGRESS'
        }
        operation = SimpleNamespace(
            idempotency_key='idem-face-value',
            source_amount=Decimal('100.00'),
            source_account=SimpleNamespace(provider_account_id='source'),
            destination_account=SimpleNamespace(provider_account_id='target'),
            provider_data={},
        )

        InfiniaProvider(client=client).create_transfer(operation)

        payload = client.create_internal_transfer.call_args.args[0]
        self.assertEqual(payload, {
            'idempotency_key': 'idem-face-value',
            'source_account_id': 'source',
            'target_account_id': 'target',
            'source_amount': 100.0,
        })

    def test_infinia_account_uses_alpha2_and_balance_details(self):
        client = mock.Mock()
        client.create_account.return_value = {
            'id': 491,
            'status': 'ACTIVE',
            'balance_details': {'total': 12.5, 'available': 10.25},
            'products': ['PAYINS'],
        }
        account = SimpleNamespace(
            internal_id='local-id',
            country='COL',
            asset='COP',
            provider_profile=SimpleNamespace(provider_owner_id='owner-id'),
        )

        result = InfiniaProvider(client=client).provision_account(account)

        payload = client.create_account.call_args.args[0]
        self.assertEqual(payload['country'], 'CO')
        self.assertEqual(result.available_balance, Decimal('10.25'))
        self.assertEqual(result.current_balance, Decimal('12.5'))

    @override_settings(COBRE_DOCUMENT_TYPE_MAP={'VEN:national_id': 'die'})
    def test_cobre_uses_issuing_country_for_document_mapping(self):
        client = mock.Mock()
        client.find_key.return_value = []
        client.create_key.return_value = {
            'id': 'key_1', 'connectivity': {'status': 'processing'}
        }
        account = SimpleNamespace(
            provider_account_id='acc_1',
            internal_id='local',
            provider_profile=SimpleNamespace(
                identity_snapshot={
                    'full_name': 'Persona Venezolana',
                    'document_number': 'V123',
                    'document_type': 'national_id',
                    'document_issuing_country': 'VEN',
                }
            ),
        )

        CobreProvider(client=client).create_funding_instruction(
            account, kind='breb_key', alias='stable-alias'
        )

        payload = client.create_key.call_args.args[1]
        self.assertEqual(payload['holder']['id_type'], 'die')
        self.assertEqual(payload['key_config'], 'random')

    def test_cobre_stablefx_uses_quote_then_cross_border_movement(self):
        client = mock.Mock()
        client.create_fx_quote.return_value = {
            'id': 'fxq_1', 'status': 'completed', 'destination_amount': 400000
        }
        client.create_cross_border_movement.return_value = {
            'id': 'mm_1', 'status': {'state': 'initiated'}
        }
        operation = SimpleNamespace(
            idempotency_key='123456789',
            source_amount=Decimal('10.25'),
            source_account=SimpleNamespace(
                asset='USD_STABLE', provider_account_id='acc_usd'
            ),
            destination_account=SimpleNamespace(
                asset='COPCO', provider_account_id='acc_copco'
            ),
        )

        result = CobreProvider(client=client).create_transfer(operation)

        self.assertEqual(result.status, 'submitted')
        self.assertEqual(result.raw['target_amount'], '4000')
        client.create_fx_quote.assert_called_once_with({
            'currency_pair': 'usd_stable/copco',
            'source_amount': 1025,
            'type': 'static_quote',
        })
        movement = client.create_cross_border_movement.call_args.args[0]
        self.assertEqual(movement['forex_quote_id'], 'fxq_1')
        self.assertEqual(movement['source_id'], 'acc_usd')

    def test_cobre_stablefx_rejects_breb_cop_balance(self):
        operation = SimpleNamespace(
            source_amount=Decimal('100'),
            source_account=SimpleNamespace(asset='COP', provider_account_id='acc_cop'),
            destination_account=SimpleNamespace(
                asset='USD_STABLE', provider_account_id='acc_usd'
            ),
        )
        with self.assertRaisesRegex(Exception, 'cannot be used directly'):
            CobreProvider(client=mock.Mock()).create_transfer(operation)
