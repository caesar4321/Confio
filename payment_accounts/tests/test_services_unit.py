from types import SimpleNamespace
from unittest import mock
import uuid

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from payment_accounts.models import (
    FinancialAccount, MoneyFlow, MoneyOperation, PayoutDestination,
    ProviderProfile,
)
from payment_accounts.schema import (
    MoneyFlowType,
    MoneyOperationType,
    _destination_details,
)
from payment_accounts.services import (
    PaymentAccountError,
    _validate_infinia_destination,
    create_and_submit_payout,
    provision_payment_account,
)
from security.models import FaceCheck, IdentityVerification
from users.models import Account, User


class DestinationValidationTests(SimpleTestCase):
    def test_typed_graphql_destination_maps_to_provider_camel_case(self):
        details = _destination_details({
            'type': 'BREB_KEY',
            'breb_key': '@persona',
            'accepts_retries': False,
        })
        self.assertEqual(details['brebKey'], '@persona')
        self.assertIs(details['acceptsRetries'], False)

    def test_infinia_breb_requires_colombia_and_key(self):
        details = {'type': 'BREB_KEY', 'brebKey': '@persona'}
        _validate_infinia_destination(
            kind='breb_key', country='COL', details=details
        )
        with self.assertRaises(PaymentAccountError):
            _validate_infinia_destination(
                kind='breb_key', country='VEN', details=dict(details)
            )

    def test_infinia_destination_reports_missing_required_fields(self):
        with self.assertRaisesRegex(PaymentAccountError, 'accountNumber'):
            _validate_infinia_destination(
                kind='bank_account',
                country='COL',
                details={
                    'type': 'ACCOUNT_COLOMBIA',
                    'fullName': 'Persona',
                    'documentType': 'CC',
                    'documentNumber': '1',
                    'bankCode': '1007',
                    'accountType': 'SAVINGS',
                },
            )


class PlatformFeeBoundaryTests(SimpleTestCase):
    def test_payment_account_models_do_not_store_platform_fee(self):
        self.assertNotIn(
            'confio_fee', {field.name for field in MoneyFlow._meta.get_fields()}
        )
        self.assertNotIn(
            'confio_fee',
            {field.name for field in MoneyOperation._meta.get_fields()},
        )

    def test_payment_account_graphql_does_not_expose_platform_fee(self):
        self.assertNotIn('confio_fee', MoneyFlowType._meta.fields)
        self.assertNotIn('confio_fee', MoneyOperationType._meta.fields)


@override_settings(INFINIA_PAYMENT_ACCOUNTS_ENABLED=True)
class PayoutFaceBindingTests(TestCase):
    @mock.patch('payment_accounts.services.submit_money_operation')
    @mock.patch('payment_accounts.services.require_outgoing_face', return_value='out:' + ('a' * 64))
    @mock.patch('payment_accounts.services.create_money_operation')
    @mock.patch('payment_accounts.services.provision_payout_destination')
    @mock.patch('payment_accounts.services.enforce_and_record')
    @mock.patch('payment_accounts.services.context_from_identity', return_value={})
    @mock.patch('payment_accounts.services.ProviderProfile.objects.get')
    def test_payout_claims_once_with_persisted_full_terms_before_submit(
        self, profile_get, _context, _policy, _provision, create_operation, claim, submit
    ):
        owner = SimpleNamespace(
            id=7, user_id=9, account_type='personal', user=SimpleNamespace()
        )
        source = SimpleNamespace(
            internal_id='source-id', provider='infinia', asset='PEN', country='PER'
        )
        destination = SimpleNamespace(
            internal_id='destination-id', confio_account_id=7, provider='infinia',
            asset='PEN', country='PER', kind='bank_account', holder_name='Ana',
            holder_id_type='DNI', holder_id_number='123', details={'account': '456'},
            provider_destination_id='provider-destination',
        )
        profile_get.return_value.identity_verification = SimpleNamespace(status='verified')
        flow = SimpleNamespace(metadata={}, save=mock.Mock())
        operation = SimpleNamespace(
            idempotency_key='durable-operation-key', provider='infinia',
            operation_type='payout', source_asset='PEN', source_amount='10.000000000000000000',
            external_destination={
                'destination_internal_id': 'destination-id',
                'kind': 'bank_account', 'country': 'PER', 'holder_name': 'Ana',
                'holder_id_type': 'DNI', 'holder_id_number': '123',
                'details': {'account': '456'}, 'destination_account': {'account': '456'},
            },
            money_flow=flow,
        )
        create_operation.return_value = operation
        submit.return_value = operation

        result = create_and_submit_payout(
            confio_account=owner, source_account=source, destination=destination,
            amount='10', client_request_id='request-id',
        )

        self.assertIs(result, operation)
        claim.assert_called_once_with(
            owner, 'payment_accounts.payout', 'durable-operation-key',
            {
                'confio_account_id': '7', 'user_id': '9', 'provider': 'infinia',
                'operation_type': 'payout',
                'source_account_id': 'source-id', 'source_asset': 'PEN',
                'source_amount': '10',
                'external_destination': operation.external_destination,
            },
        )
        self.assertEqual(flow.metadata['face_action_key'], 'out:' + ('a' * 64))
        flow.save.assert_called_once_with(update_fields=['metadata', 'updated_at'])
        submit.assert_called_once_with(operation)

    @mock.patch('payment_accounts.services.submit_money_operation')
    @mock.patch(
        'payment_accounts.services.require_outgoing_face',
        side_effect=PaymentAccountError('face required'),
    )
    @mock.patch('payment_accounts.activation.require_usable')
    @mock.patch('payment_accounts.services.provision_payout_destination')
    @mock.patch('payment_accounts.services.enforce_and_record')
    @mock.patch('payment_accounts.services.context_from_identity', return_value={})
    def test_face_rejection_rolls_back_created_operation_flow(
        self, _context, _policy, _provision, _usable, _claim, submit,
    ):
        user = User.objects.create_user(username='payout-face', firebase_uid='payout-face')
        owner = Account.objects.create(user=user, account_type='personal')
        identity = IdentityVerification.objects.create(
            user=user, status='verified', verified_date_of_birth='1990-01-01'
        )
        profile = ProviderProfile.objects.create(
            confio_account=owner, provider='infinia', owner_type='individual',
            status='active', identity_verification=identity,
        )
        source = FinancialAccount.objects.create(
            provider_profile=profile, provider_account_id='source', country='PER',
            asset='PEN', status='active', ownership_structure='provider_named',
        )
        destination = PayoutDestination.objects.create(
            confio_account=owner, provider='infinia', asset='PEN', country='PER',
            kind='bank_account', holder_name='Ana', holder_id_type='DNI',
            holder_id_number='123', details={'account': '456'}, status='active',
            provider_destination_id='provider-destination',
        )

        with self.assertRaisesRegex(PaymentAccountError, 'face required'):
            create_and_submit_payout(
                confio_account=owner, source_account=source, destination=destination,
                amount='10', client_request_id=uuid.uuid4(),
            )

        self.assertFalse(MoneyFlow.objects.filter(confio_account=owner).exists())
        self.assertFalse(MoneyOperation.objects.filter(money_flow__confio_account=owner).exists())
        submit.assert_not_called()

    @override_settings(FACE_STEP_UP_ENABLED=True)
    @mock.patch('payment_accounts.services.submit_money_operation', side_effect=lambda op: op)
    @mock.patch('payment_accounts.activation.require_usable')
    @mock.patch('payment_accounts.services.provision_payout_destination')
    @mock.patch('payment_accounts.services.enforce_and_record')
    @mock.patch('payment_accounts.services.context_from_identity', return_value={})
    def test_exact_payout_retry_reuses_face_but_new_amount_needs_new_grant(
        self, _context, _policy, _provision, _usable, submit,
    ):
        user = User.objects.create_user(username='payout-retry', firebase_uid='payout-retry')
        owner = Account.objects.create(user=user, account_type='personal')
        identity = IdentityVerification.objects.create(
            user=user, status='verified', verified_date_of_birth='1990-01-01'
        )
        profile = ProviderProfile.objects.create(
            confio_account=owner, provider='infinia', owner_type='individual',
            status='active', identity_verification=identity,
        )
        source = FinancialAccount.objects.create(
            provider_profile=profile, provider_account_id='source', country='PER',
            asset='PEN', status='active', ownership_structure='provider_named',
        )
        destination = PayoutDestination.objects.create(
            confio_account=owner, provider='infinia', asset='PEN', country='PER',
            kind='bank_account', holder_name='Ana', holder_id_type='DNI',
            holder_id_number='123', details={'account': '456'}, status='active',
            provider_destination_id='provider-destination',
        )
        first_face = FaceCheck.objects.create(
            user=user, purpose='withdrawal', liveness_session_id='payout-first',
            status='passed', completed_at=timezone.now(),
        )
        request_id = uuid.uuid4()

        first = create_and_submit_payout(
            confio_account=owner, source_account=source, destination=destination,
            amount='10', client_request_id=request_id,
        )
        retry = create_and_submit_payout(
            confio_account=owner, source_account=source, destination=destination,
            amount='10.0', client_request_id=request_id,
        )

        first_face.refresh_from_db()
        self.assertEqual(retry.pk, first.pk)
        self.assertEqual(MoneyOperation.objects.count(), 1)
        second_face = FaceCheck.objects.create(
            user=user, purpose='withdrawal', liveness_session_id='payout-second',
            status='passed', completed_at=timezone.now(),
        )
        with self.assertRaisesRegex(PaymentAccountError, 'different payment details'):
            create_and_submit_payout(
                confio_account=owner, source_account=source, destination=destination,
                amount='11', client_request_id=request_id,
            )
        second_face.refresh_from_db()
        self.assertIsNone(second_face.consumed_at)
        second = create_and_submit_payout(
            confio_account=owner, source_account=source, destination=destination,
            amount='11', client_request_id=uuid.uuid4(),
        )
        second_face.refresh_from_db()
        self.assertNotEqual(second.pk, first.pk)
        self.assertNotEqual(second_face.consumed_by, first_face.consumed_by)
        self.assertEqual(MoneyOperation.objects.count(), 2)
        self.assertEqual(submit.call_count, 3)


@override_settings(COBRE_PAYMENT_ACCOUNTS_ENABLED=True)
class ProviderShapeTests(SimpleTestCase):
    def test_cobre_rejects_non_cop_account_before_provider_or_db_access(self):
        with self.assertRaises(PaymentAccountError):
            provision_payment_account(
                confio_account=SimpleNamespace(),
                provider='cobre',
                identity=SimpleNamespace(),
                country='COL',
                asset='USD',
                ownership_structure='omnibus_subledger',
            )

    def test_provider_ownership_structure_cannot_be_misrepresented(self):
        with self.assertRaises(PaymentAccountError):
            provision_payment_account(
                confio_account=SimpleNamespace(),
                provider='cobre',
                identity=SimpleNamespace(),
                country='COL',
                asset='COP',
                ownership_structure='provider_named',
            )
