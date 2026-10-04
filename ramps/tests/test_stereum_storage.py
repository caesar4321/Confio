"""Real SQLite persistence checks; PostgreSQL locking needs deployment testing."""
import importlib
import unittest
import uuid
from unittest.mock import Mock, patch

from django.conf import settings
from django.db import connection, models
from django.db.migrations.state import ModelState, ProjectState
from django.test import override_settings

from ramps.models import StereumTestOperation, StereumTestWebhook, StereumCustomer
from ramps.stereum_client import StereumError
from ramps.stereum_service import execute, refresh
from users.models import User


@unittest.skipUnless(getattr(settings, 'STEREUM_ISOLATED_TESTS', False), 'Use the isolated Stereum runner')
class StereumStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        assert connection.vendor == 'sqlite' and connection.settings_dict['NAME'] == ':memory:'
        state = ProjectState()
        state.add_model(ModelState('users', 'User', [('id', models.BigAutoField(primary_key=True))]))
        migration = importlib.import_module('ramps.migrations.0022_stereum_test_integration').Migration('0022_stereum_test_integration', 'ramps')
        with connection.schema_editor() as editor:
            editor.create_model(state.apps.get_model('users', 'User'))
            cls.state = migration.apply(state, editor)
        cls.state.add_model(ModelState('security', 'IdentityVerification', [('id', models.BigAutoField(primary_key=True))]))
        customer_migration = importlib.import_module('ramps.migrations.0023_stereum_customer').Migration('0023_stereum_customer', 'ramps')
        with connection.schema_editor() as editor:
            editor.create_model(cls.state.apps.get_model('security', 'IdentityVerification'))
            cls.state = customer_migration.apply(cls.state, editor)
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO users_user (id) VALUES (1)')
            cursor.execute('INSERT INTO security_identityverification (id) VALUES (1)')

    def setUp(self):
        config = override_settings(STEREUM_TEST_ENABLED=True)
        config.enable()
        self.addCleanup(config.disable)
        StereumCustomer.objects.all().delete()
        StereumTestOperation.objects.all().delete()
        self.actor = User(pk=1, is_superuser=True, is_active=True)
        self.client = Mock(scope='test-scope')
        # Only the unrelated full User schema/lock is stubbed; operation storage,
        # transactions, uniqueness, rollback and refresh use the actual database.
        lock = patch.object(User.objects, 'select_for_update')
        lock.start().return_value.get.return_value = self.actor
        self.addCleanup(lock.stop)
        self.payload = {'amount': '1', 'name': 'Test', 'lastname': 'Person', 'document_number': '111', 'reason': 'Sandbox'}

    def test_uncertain_mutation_is_persisted_before_call_and_never_repeated(self):
        def timeout(payload):
            self.assertEqual(StereumTestOperation.objects.get().status, 'submitting')
            self.assertFalse(connection.in_atomic_block)
            raise StereumError('Timeout', ambiguous=True)
        self.client.create_charge.side_effect = timeout
        identifier = uuid.uuid4()
        first = execute(self.actor, 'charge', self.payload, identifier, client=self.client)
        second = execute(self.actor, 'charge', self.payload, identifier, client=self.client)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.status, 'unknown')
        self.assertEqual(self.client.create_charge.call_count, 1)

    def test_resource_reservation_blocks_second_uuid(self):
        charge = StereumTestOperation.objects.create(actor=self.actor, credential_scope=self.client.scope,
            action='charge', status='pending', provider_id='charge-id', request_data={'amount': '1'},
            response_data={'on_main_net': False})
        self.client.confirm_test_charge.return_value = {'ok': True}
        payload = {'charge_request_id': str(charge.request_id)}
        execute(self.actor, 'confirm_charge', payload, uuid.uuid4(), client=self.client)
        with self.assertRaises(StereumError):
            execute(self.actor, 'confirm_charge', payload, uuid.uuid4(), client=self.client)
        self.assertEqual(self.client.confirm_test_charge.call_count, 1)
        self.assertEqual(StereumTestOperation.objects.filter(action='confirm_charge').count(), 1)

    def test_conflicting_refresh_leaves_terminal_record_intact(self):
        op = StereumTestOperation.objects.create(actor=self.actor, credential_scope=self.client.scope,
            action='charge', status='succeeded', provider_status='PAGADO', provider_id='charge-id')
        self.client.get_charge.return_value = {'id': 'charge-id', 'status': 'PENDIENTE'}
        with self.assertRaises(StereumError):
            refresh(self.actor, op.request_id, client=self.client)
        op.refresh_from_db()
        self.assertEqual((op.status, op.provider_status), ('succeeded', 'PAGADO'))

    def test_migration_matches_models(self):
        for model in (StereumTestOperation, StereumTestWebhook, StereumCustomer):
            migrated = self.state.models[('ramps', model.__name__.lower())]
            current = ModelState.from_model(model)
            self.assertEqual(migrated.options, current.options)
            for key, field in current.fields.items():
                self.assertEqual(migrated.fields[key].deconstruct()[1:], field.deconstruct()[1:])

    def setup_customer(self, document_type='national_id'):
        from datetime import date
        from security.models import IdentityVerification
        config = override_settings(STEREUM_CUSTOMER_TEST_ENABLED=True, STEREUM_TEST_WRITES_ENABLED=True)
        config.enable()
        self.addCleanup(config.disable)
        self.identity = IdentityVerification(pk=1, user=self.actor, status='verified',
            verified_first_name='JUAN', verified_last_name='PEREZ MEDINA',
            verified_date_of_birth=date(1990, 1, 2), document_type=document_type,
            document_number='1234567', document_issuing_country='BOL', verified_country='BOL')
        identity_patch = patch('ramps.stereum_customers.current_identity', return_value=self.identity)
        identity_patch.start()
        self.addCleanup(identity_patch.stop)
        self.extra = {'surname1':'PEREZ', 'surname2':'MEDINA', 'state_of_residence':'BO_L',
            'economic_activity':'Tecnología y software', 'source_of_funds':'Trabajo',
            'destination_of_funds':'Servicios', 'income_level':'500 - 1000'}
        self.client.validate_identity.return_value = {'status':'VERIFIED', 'validationId':'validation-1'}
        self.client.create_customer.return_value = {'id':'provider-customer-1', 'document_number':'1234567',
            'document_type':'PASSPORT' if document_type == 'passport' else 'CI', 'country':'BO'}

    def test_customer_validation_registration_and_quote_identity(self):
        from ramps.stereum_customers import onboard, quote_customer
        self.setup_customer()
        result = onboard(self.actor, self.extra, consent=True, client=self.client)
        self.assertEqual(result.status, 'registered')
        payload = self.client.create_customer.call_args.args[0]
        self.assertEqual(payload['doc_provider_id'], 'validation-1')
        self.assertEqual(payload['name'], self.identity.verified_first_name)
        self.assertEqual(payload['idempotency_key'], str(result.external_user_id))
        self.assertEqual(quote_customer(self.actor, client=self.client), str(result.external_user_id))
        replay = onboard(self.actor, self.extra, consent=True, client=self.client)
        self.assertEqual(result.pk, replay.pk)
        self.assertEqual(self.client.validate_identity.call_count, 1)
        self.assertEqual(self.client.create_customer.call_count, 1)

    def test_passport_skips_segip(self):
        from ramps.stereum_customers import onboard
        self.setup_customer('passport')
        result = onboard(self.actor, self.extra, consent=True, client=self.client)
        self.assertEqual(result.status, 'registered')
        self.client.validate_identity.assert_not_called()
        self.assertNotIn('doc_provider_id', self.client.create_customer.call_args.args[0])

    def test_unverified_or_missing_segip_reference_blocks_registration(self):
        from ramps.stereum_customers import onboard
        for response, state in [({'status':'REJECTED'}, 'rejected'), ({'status':'VERIFIED', 'validationId':None}, 'unknown')]:
            self.setup_customer()
            self.client.validate_identity.return_value = response
            result = onboard(self.actor, self.extra, consent=True, client=self.client)
            self.assertEqual(result.status, state)
            self.client.create_customer.assert_not_called()
            StereumCustomer.objects.all().delete()

    def test_customer_timeout_is_reserved_and_not_replayed(self):
        from ramps.stereum_customers import onboard
        self.setup_customer()
        def timeout(payload):
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(StereumCustomer.objects.get().status, 'registering')
            raise StereumError('Uncertain submission', ambiguous=True)
        self.client.create_customer.side_effect = timeout
        first = onboard(self.actor, self.extra, consent=True, client=self.client)
        second = onboard(self.actor, self.extra, consent=True, client=self.client)
        self.assertEqual((first.pk, first.status), (second.pk, 'unknown'))
        self.assertEqual(self.client.create_customer.call_count, 1)

    def test_customer_consent_and_verified_surname_are_required(self):
        from ramps.stereum_customers import onboard
        self.setup_customer()
        with self.assertRaises(StereumError):
            onboard(self.actor, self.extra, consent=False, client=self.client)
        with self.assertRaises(StereumError):
            onboard(self.actor, {**self.extra, 'surname1':'OTHER'}, consent=True, client=self.client)
        self.assertEqual(StereumCustomer.objects.count(), 0)
        self.client.validate_identity.assert_not_called()

    def test_changed_identity_or_other_credential_cannot_quote(self):
        from ramps.stereum_customers import onboard, quote_customer
        self.setup_customer()
        onboard(self.actor, self.extra, consent=True, client=self.client)
        self.identity.document_number = 'different'
        with self.assertRaises(StereumError):
            quote_customer(self.actor, client=self.client)
        self.identity.document_number = '1234567'
        self.client.scope = 'different-key'
        with self.assertRaises(StereumError):
            quote_customer(self.actor, client=self.client)

    def test_provider_customer_identity_must_match(self):
        from ramps.stereum_customers import onboard
        self.setup_customer()
        self.client.create_customer.return_value['document_number'] = 'another-person'
        result = onboard(self.actor, self.extra, consent=True, client=self.client)
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(result.provider_customer_id, '')

    def test_regular_user_quote_uses_customer_mapping_never_self(self):
        from ramps.stereum_customers import onboard
        self.setup_customer()
        self.actor.is_superuser = False
        record = onboard(self.actor, self.extra, consent=True, client=self.client)
        self.client.create_quote.return_value = {'id': 'quote-customer'}
        result = execute(self.actor, 'customer_quote', {'side':'BUY', 'amount':'100'}, uuid.uuid4(), client=self.client)
        self.assertEqual(result.status, 'received')
        self.assertEqual(self.client.create_quote.call_args.kwargs['customer'], str(record.external_user_id))
        self.client.create_quote.reset_mock()
        record.status = 'unknown'
        record.save()
        with self.assertRaises(StereumError):
            execute(self.actor, 'customer_quote', {'side':'BUY', 'amount':'100'}, uuid.uuid4(), client=self.client)
        self.client.create_quote.assert_not_called()

    def test_provider_customer_cannot_be_bound_to_two_users(self):
        from ramps.stereum_customers import onboard
        from django.utils import timezone
        self.setup_customer()
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO users_user (id) VALUES (2)')
        StereumCustomer.objects.create(user_id=2, credential_scope=self.client.scope,
            source_verification_id=1, identity_fingerprint='other', request_snapshot={},
            status='registered', provider_customer_id='provider-customer-1', consent_at=timezone.now())
        result = onboard(self.actor, self.extra, consent=True, client=self.client)
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(result.provider_customer_id, '')
        self.assertEqual(StereumCustomer.objects.filter(provider_customer_id='provider-customer-1').count(), 1)
