from datetime import timedelta
from unittest import mock
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from django.test import TransactionTestCase, override_settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from billing.api.authentication import create_business_api_key
from billing.models import (
    BillingEvent, BusinessApiKey, IdempotencyRecord, ObligationSubject,
    WebhookDelivery, WebhookEndpoint,
)
from billing.webhooks import enqueue_event_deliveries
from users.models import Business


@override_settings(BILLING_API_KEY_PEPPER='test-only-independent-pepper')
class BillingApiTests(TransactionTestCase):
    def assert_contract(self, schema_name, body):
        document = yaml.safe_load((Path(__file__).resolve().parents[2]
                                   / 'docs/payments/openapi-v1.yaml').read_text())
        Draft202012Validator({
            '$ref': f'#/components/schemas/{schema_name}',
            'components': document['components'],
        }).validate(body)

    def setUp(self):
        self.business = Business.objects.create(name='CIP', category='services')
        self.other_business = Business.objects.create(
            name='Other institution', category='services')
        scopes = (
            'subjects:read', 'subjects:write',
            'obligations:read', 'obligations:write',
            'payments:read', 'settlements:read', 'applications:read',
            'events:read', 'webhook_endpoints:read', 'webhook_endpoints:write',
        )
        self.key, self.token = create_business_api_key(
            business=self.business, name='CIP sandbox', scopes=scopes)
        _, self.other_token = create_business_api_key(
            business=self.other_business, name='Other sandbox', scopes=scopes)
        _, self.read_token = create_business_api_key(
            business=self.business, name='Read only', scopes=('subjects:read',))
        self.client = APIClient()
        # The API contract tests are not IP-reputation tests. Avoid creating
        # security telemetry (and any external reputation lookup) here.
        self.client.defaults['REMOTE_ADDR'] = ''
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')
        cache.clear()

    def _create_subject(self, *, key='subject-create-1', external_id='cip:member:42'):
        return self.client.post(
            '/v1/subjects',
            {
                'external_id': external_id,
                'subject_type': 'membership',
                'masked_reference': 'CIP ••••0042',
            },
            format='json', HTTP_IDEMPOTENCY_KEY=key,
        )

    def test_api_key_plaintext_is_not_stored(self):
        self.assertTrue(self.token.startswith('sk_test_'))
        self.assertNotEqual(self.key.secret_hmac, self.token)
        self.assertEqual(len(self.key.secret_hmac), 64)

    @override_settings(BILLING_LIVE_API_KEYS_ENABLED=True)
    def test_test_key_cannot_read_or_mutate_live_subject_and_events(self):
        subject = ObligationSubject.objects.create(
            business=self.business, mode='live', external_id='cip:member:42')
        event = BillingEvent.objects.create(
            business=self.business, mode='live', event_type='payment.confirmed',
            aggregate_type='payment', aggregate_id='pay_live', aggregate_version=1,
            transition_key='live:payment:1', payload={})
        self.assertEqual(self.client.get('/v1/subjects').json()['data'], [])
        self.assertEqual(self.client.get(f'/v1/subjects/{subject.public_id}').status_code, 404)
        self.assertEqual(self.client.get('/v1/events').json()['data'], [])
        self.assertEqual(self.client.get(f'/v1/events/{event.public_id}').status_code, 404)
        response = self.client.patch(
            f'/v1/subjects/{subject.public_id}', {'status': 'blocked'}, format='json',
            HTTP_IDEMPOTENCY_KEY='cross-mode', HTTP_IF_MATCH='1')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._create_subject().status_code, 201)
        self.assertEqual(ObligationSubject.objects.count(), 2)

    def test_malformed_timestamp_filter_returns_validation_error(self):
        for path in ('subjects', 'obligations', 'payments', 'applications'):
            response = self.client.get(f'/v1/{path}?updated_after=not-a-date')
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/v1/events?created_after=bad').status_code, 400)

    def test_live_api_key_provisioning_is_gated(self):
        with self.assertRaisesRegex(ValueError, 'not enabled'):
            create_business_api_key(
                business=self.business, name='CIP live', mode='live',
                scopes=('subjects:read',))

    def test_live_api_key_kill_switch_blocks_an_existing_key(self):
        with override_settings(BILLING_LIVE_API_KEYS_ENABLED=True):
            _, live_token = create_business_api_key(
                business=self.business, name='CIP live', mode='live',
                scopes=('subjects:read',))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {live_token}')
        response = self.client.get('/v1/subjects')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'invalid_api_key')

    def test_subject_creation_is_idempotent_and_explicitly_private(self):
        first = self._create_subject()
        replay = self._create_subject()

        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay['Idempotent-Replayed'], 'true')
        self.assertEqual(ObligationSubject.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.filter(
            status='completed').count(), 1)
        self.assertTrue(first['Confio-Request-Id'].startswith('req_'))
        self.assert_contract('Subject', first.json())
        forbidden_fields = {
            'dni', 'email', 'phone', 'confio_user', 'metadata', 'display_label'
        }
        self.assertTrue(forbidden_fields.isdisjoint(first.json()))

    def test_same_idempotency_key_with_different_body_is_rejected(self):
        self.assertEqual(self._create_subject(key='same-key').status_code, 201)
        response = self._create_subject(
            key='same-key', external_id='cip:member:different')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'idempotency_key_reused')
        self.assert_contract('Error', response.json())
        self.assertEqual(ObligationSubject.objects.count(), 1)

    def test_mutation_requires_key_and_rejects_unknown_identity_fields(self):
        missing = self.client.post(
            '/v1/subjects', {'external_id': 'cip:1'}, format='json')
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()['error']['code'], 'idempotency_key_required')

        unknown = self.client.post(
            '/v1/subjects',
            {'external_id': 'cip:1', 'email': 'person@example.com'},
            format='json', HTTP_IDEMPOTENCY_KEY='unknown-field')
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(unknown.json()['error']['code'], 'validation_error')
        self.assertFalse(ObligationSubject.objects.exists())

    def test_scope_and_revocation_fail_closed(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.read_token}')
        denied = self._create_subject(key='read-cannot-write')
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()['error']['code'], 'missing_scope')

        BusinessApiKey.objects.filter(id=self.key.id).update(
            revoked_at=timezone.now())
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')
        revoked = self.client.get('/v1/subjects')
        self.assertEqual(revoked.status_code, 401)
        self.assertEqual(revoked.json()['error']['code'], 'invalid_api_key')

    def test_deleted_business_api_key_is_rejected(self):
        Business.objects.filter(pk=self.business.pk).update(deleted_at=timezone.now())
        self.assertEqual(self.client.get('/v1/subjects').status_code, 401)

    def test_subject_object_lookup_is_tenant_safe(self):
        created = self._create_subject().json()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.other_token}')
        response = self.client.get(f"/v1/subjects/{created['id']}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'resource_not_found')

    def test_subject_patch_requires_version_and_is_idempotent(self):
        subject = self._create_subject().json()
        path = f"/v1/subjects/{subject['id']}"
        missing = self.client.patch(
            path, {'status': 'blocked'}, format='json',
            HTTP_IDEMPOTENCY_KEY='patch-missing-version')
        self.assertEqual(missing.status_code, 409)
        self.assertEqual(missing.json()['error']['code'], 'if_match_required')

        first = self.client.patch(
            path, {'status': 'blocked'}, format='json',
            HTTP_IDEMPOTENCY_KEY='patch-1', HTTP_IF_MATCH='1')
        replay = self.client.patch(
            path, {'status': 'blocked'}, format='json',
            HTTP_IDEMPOTENCY_KEY='patch-1', HTTP_IF_MATCH='1')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['version'], 2)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay['Idempotent-Replayed'], 'true')

    def test_obligation_creation_uses_minor_units_and_tenant_subject(self):
        subject = self._create_subject().json()
        due_at = timezone.now() + timedelta(days=10)
        response = self.client.post(
            '/v1/obligations',
            {
                'external_id': 'cip:42:2026-09',
                'subject': subject['id'],
                'commercial_amount': {'value': '50.00', 'currency': 'PEN'},
                'period': {'start': '2026-09-01', 'end': '2026-09-30'},
                'due_at': due_at.isoformat(),
                'description': 'Cuota CIP · septiembre 2026',
            }, format='json', HTTP_IDEMPOTENCY_KEY='obligation-create-1')

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body['id'].startswith('obl_'))
        self.assertEqual(body['commercial_amount'], {
            'value': '50.00', 'currency': 'PEN'})
        self.assert_contract('Obligation', body)
        self.assertEqual(body['amount_remaining']['value'], '50.00')
        self.assertNotIn('line_items_snapshot', body)

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.other_token}')
        hidden = self.client.get(f"/v1/obligations/{body['id']}")
        self.assertEqual(hidden.status_code, 404)

    @mock.patch('billing.api.views.validate_delivery_url')
    def test_webhook_secret_is_returned_once_and_replay_is_new_delivery(self, validate):
        created = self.client.post(
            '/v1/webhook_endpoints', {
                'url': 'https://cip.example.test/confio',
                'event_types': ['payment.confirmed'],
            }, format='json', HTTP_IDEMPOTENCY_KEY='endpoint-1')
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.json()['signing_secret'].startswith('whsec_'))
        self.assert_contract('EndpointWithSecret', created.json())
        stored = IdempotencyRecord.objects.get(key='endpoint-1')
        self.assertNotIn(created.json()['signing_secret'], str(stored.response_body))
        repeated = self.client.post(
            '/v1/webhook_endpoints', {
                'url': 'https://cip.example.test/confio',
                'event_types': ['payment.confirmed'],
            }, format='json', HTTP_IDEMPOTENCY_KEY='endpoint-1')
        self.assertEqual(repeated.json(), created.json())
        endpoint_id = created.json()['id']
        fetched = self.client.get(f'/v1/webhook_endpoints/{endpoint_id}')
        self.assertNotIn('signing_secret', fetched.json())

        event = BillingEvent.objects.create(
            business=self.business, event_type='payment.confirmed',
            mode='test',
            aggregate_type='payment', aggregate_id='pay_api', aggregate_version=1,
            transition_key='pay:api:confirmed', payload={
                'object': 'event', 'type': 'payment.confirmed', 'data': {'object': {}}})
        delivery = enqueue_event_deliveries(event)[0]
        replay = self.client.post(
            f'/v1/webhook_deliveries/{delivery.public_id}/replay', {}, format='json',
            HTTP_IDEMPOTENCY_KEY='replay-1')
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json()['replay_number'], 1)
        self.assert_contract('Delivery', replay.json())
        self.assertEqual(WebhookDelivery.objects.filter(event=event).count(), 2)

        for number in range(2):
            result = self.client.post(
                f'/v1/webhook_endpoints/{endpoint_id}/test', {}, format='json',
                HTTP_IDEMPOTENCY_KEY=f'endpoint-test-{number}')
            self.assertEqual(result.status_code, 201)
        self.assertEqual(list(BillingEvent.objects.filter(
            aggregate_id=endpoint_id).order_by('aggregate_version').values_list(
                'aggregate_version', flat=True)), [1, 2])

    def test_terminal_conflict_response_is_retained(self):
        self.assertEqual(self._create_subject(key='first').status_code, 201)
        first = self._create_subject(key='conflict')
        self.assertEqual(first.status_code, 409)
        ObligationSubject.objects.update(external_id='changed:external:id')
        replay = self._create_subject(key='conflict')
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay['Idempotent-Replayed'], 'true')
        self.assertEqual(replay.json(), first.json())

    @mock.patch('billing.api.views._subject_dto', side_effect=RuntimeError('private internal detail'))
    def test_unexpected_failure_rolls_back_and_returns_safe_retryable_error(self, dto):
        response = self._create_subject()
        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.json()['error']['retryable'])
        self.assertNotIn('private internal detail', str(response.json()))
        self.assertFalse(ObligationSubject.objects.exists())
        self.assertFalse(IdempotencyRecord.objects.exists())
        self.assert_contract('Error', response.json())

    @override_settings(BILLING_API_RATE_LIMIT_PER_MINUTE=1)
    def test_rate_limit_is_key_scoped_and_has_standard_headers(self):
        first = self.client.get('/v1/subjects')
        second = self.client.get('/v1/subjects')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first['RateLimit-Limit'], '1')
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()['error']['code'], 'rate_limit_exceeded')
