import asyncio
import json
from types import SimpleNamespace
from unittest import mock

import graphene
from django.test import RequestFactory, SimpleTestCase, override_settings

from security.face_client import (
    FaceClientCompatibilityMiddleware, FaceClientWebSocketMiddleware,
    TRANSACTION_FIELDS, UPDATE_CODE, UPDATE_MESSAGE, update_required,
)


def headers(platform='android', version='5.1.5', build='157'):
    return {'X-Confio-Platform': platform, 'X-Confio-Version': version,
            'X-Confio-Build': build, 'X-Confio-Face-Capable': '1'}


@override_settings(FACE_STEP_UP_ENABLED=True, FACE_MIN_APP_VERSION='5.1.5',
                   FACE_MIN_ANDROID_BUILD=157, FACE_MIN_IOS_BUILD=1)
class FaceClientTests(SimpleTestCase):
    @override_settings(FACE_STEP_UP_ENABLED=False, FACE_STEP_UP_AVAILABLE=False)
    def test_supported_http_client_enforces_face_and_resets_context(self):
        from security.face_client import FaceClientRequestMiddleware
        from security.face_step_up import face_enforced, step_up_applies, checks_available
        user = SimpleNamespace(has_verified_identity_document=True)
        def response(request):
            self.assertTrue(face_enforced())
            self.assertTrue(checks_available())
            self.assertTrue(step_up_applies(user))
            self.assertFalse(step_up_applies(SimpleNamespace(has_verified_identity_document=False)))
            self.assertFalse(update_required(headers()))
            return 'ok'
        self.assertEqual(FaceClientRequestMiddleware(response)(SimpleNamespace(headers=headers())), 'ok')
        self.assertFalse(face_enforced())
        self.assertFalse(step_up_applies(user))

    @override_settings(FACE_STEP_UP_ENABLED=False)
    def test_supported_websocket_context_is_isolated(self):
        from security.face_step_up import face_enforced
        async def run():
            async def app(scope, receive, send):
                self.assertTrue(face_enforced())
                raise RuntimeError('disconnect')
            with self.assertRaises(RuntimeError):
                await FaceClientWebSocketMiddleware(app)({'path': '/ws/send_session',
                    'headers': [(k.encode(), v.encode()) for k, v in headers().items()]}, None, None)
            self.assertFalse(face_enforced())
        asyncio.run(run())

    def test_current_android_and_ios_pass(self):
        self.assertFalse(update_required(headers()))
        self.assertFalse(update_required(headers('ios', build='1')))

    def test_old_missing_and_malformed_clients_need_update(self):
        bad = [{}, headers(version='5.1.4'), headers(build='156'),
               headers('ios', version='5.1.4', build='999'), headers('web'),
               headers(version='5.1'), headers(version='5.1.5-beta'), headers(build='1e6'),
               headers(version='5.1.6', build='0')]
        for key in headers():
            bad.append({k: v for k, v in headers().items() if k != key})
        for case in bad:
            with self.subTest(headers=case):
                self.assertTrue(update_required(case))

    def test_future_ios_release_can_reset_build_number(self):
        self.assertFalse(update_required(headers('ios', '5.1.6', '1')))
        self.assertFalse(update_required(headers(version='5.1.10', build='200')))

    def test_headers_case_insensitive(self):
        self.assertFalse(update_required({k.lower(): v for k, v in headers().items()}))

    @override_settings(FACE_STEP_UP_ENABLED=False, FACE_STEP_UP_AVAILABLE=True)
    def test_disabled_switch_never_forces_update_even_when_face_available(self):
        self.assertFalse(update_required({}))
        self.assertFalse(update_required(headers(version='1.0.0')))

    def test_gate_before_resolver_with_alias_and_misleading_operation_name(self):
        calls = []
        class Send(graphene.Mutation):
            ok = graphene.Boolean()
            def mutate(root, info):
                calls.append('sent')
                return Send(ok=True)
        class Mutation(graphene.ObjectType):
            submit_bsc_send = Send.Field()
            send_support_message = Send.Field()
        class Query(graphene.ObjectType):
            balance = graphene.Int(default_value=1)
        schema = graphene.Schema(query=Query, mutation=Mutation)
        context = SimpleNamespace(user=SimpleNamespace(is_authenticated=True), headers={})
        middleware = [FaceClientCompatibilityMiddleware()]
        result = schema.execute('mutation LegalDocument { harmless: submitBscSend { ok } }',
                                context_value=context, middleware=middleware)
        self.assertEqual(result.errors[0].extensions['code'], UPDATE_CODE)
        self.assertEqual(result.errors[0].message, UPDATE_MESSAGE)
        self.assertEqual(calls, [])
        result = schema.execute('mutation { sendSupportMessage { ok } }', context_value=context, middleware=middleware)
        self.assertIsNone(result.errors)
        result = schema.execute('{ balance }', context_value=context, middleware=middleware)
        self.assertIsNone(result.errors)
        context.headers = headers()
        result = schema.execute('mutation { submitBscSend { ok } }', context_value=context, middleware=middleware)
        self.assertIsNone(result.errors)

    def test_production_schema_field_names_exist(self):
        from config.schema import schema
        actual = set(schema.graphql_schema.mutation_type.fields)
        self.assertEqual(TRANSACTION_FIELDS - actual, set())

    def test_recovery_and_support_are_not_guarded_fields(self):
        self.assertTrue(TRANSACTION_FIELDS.isdisjoint({
            'submitBscReclaimInvite', 'submitReclaimInvite', 'claimInviteForPhone',
            'sendP2pMessage', 'submitPayrollVaultWithdrawal', 'web3AuthLogin',
        }))

    @override_settings(GUARDARIAN_API_KEY='test')
    def test_rest_order_denied_before_provider_call(self):
        from config.views import guardarian_transaction_proxy
        request = RequestFactory().post('/api/guardarian/transaction/', data='{}',
                                        content_type='application/json', HTTP_AUTHORIZATION='JWT test')
        with mock.patch('config.views.jwt_decode', return_value={'user_id': 1}), \
             mock.patch('users.models.User.objects.get', return_value=SimpleNamespace(pk=1)), \
             mock.patch('security.integrity_service.app_check_service.verify_request_header', return_value={'success': True}), \
             mock.patch('config.views.requests.post') as provider:
            response = guardarian_transaction_proxy(request)
        self.assertEqual(response.status_code, 426)
        self.assertEqual(json.loads(response.content)['code'], UPDATE_CODE)
        provider.assert_not_called()

    @override_settings(GUARDARIAN_API_KEY='test')
    def test_rest_compatible_headers_do_not_replace_face_and_claim_is_required(self):
        from config.views import guardarian_transaction_proxy
        from security.face_step_up import FACE_STEP_UP_MESSAGE
        user = mock.Mock(pk=1, email='test@example.com', phone_country='BR')
        user.accounts.filter.return_value.first.return_value = SimpleNamespace(algorand_address='TEST')
        for preflight, claimed in ((FACE_STEP_UP_MESSAGE, False), ('', False), ('', True)):
            with self.subTest(preflight=preflight, claimed=claimed):
                request = RequestFactory().post('/api/guardarian/transaction/',
                    data=json.dumps({'amount': 10, 'from_currency': 'EUR', 'to_currency': 'USDC'}),
                    content_type='application/json', HTTP_AUTHORIZATION='JWT test',
                    **{'HTTP_' + k.upper().replace('-', '_'): v for k, v in headers().items()})
                with mock.patch('config.views.jwt_decode', return_value={'user_id': 1}), \
                     mock.patch('users.models.User.objects.get', return_value=user), \
                     mock.patch('security.integrity_service.app_check_service.verify_request_header', return_value={'success': True}), \
                     mock.patch('security.face_step_up.missing_face_step_up', return_value=preflight), \
                     mock.patch('security.face_step_up.claim_on_ramp_check', return_value=(claimed, None)) as claim, \
                     mock.patch('config.views.requests.post', side_effect=__import__('requests').RequestException) as provider:
                    response = guardarian_transaction_proxy(request)
                if preflight or not claimed:
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(json.loads(response.content)['face_purpose'], 'on_ramp')
                    provider.assert_not_called()
                else:
                    self.assertEqual(response.status_code, 502)
                    claim.assert_called_once()
                    provider.assert_called_once()

    @override_settings(GUARDARIAN_API_KEY='test')
    def test_rest_sell_checkout_does_not_spend_the_funding_face(self):
        from config.views import guardarian_transaction_proxy
        user = mock.Mock(pk=1, email='test@example.com', phone_country='BR')
        user.accounts.filter.return_value.first.return_value = SimpleNamespace(algorand_address='TEST')
        request = RequestFactory().post('/api/guardarian/transaction/',
            data=json.dumps({'amount': 10, 'from_currency': 'USDC', 'to_currency': 'EUR'}),
            content_type='application/json', HTTP_AUTHORIZATION='JWT test',
            **{'HTTP_' + k.upper().replace('-', '_'): v for k, v in headers().items()})
        with mock.patch('config.views.jwt_decode', return_value={'user_id': 1}), \
             mock.patch('users.models.User.objects.get', return_value=user), \
             mock.patch('security.integrity_service.app_check_service.verify_request_header', return_value={'success': True}), \
             mock.patch('security.identity_reuse.outgoing_identity_restriction', return_value=''), \
             mock.patch('security.face_step_up.missing_face_step_up') as preflight, \
             mock.patch('security.face_step_up.require_face_step_up') as withdrawal, \
             mock.patch('security.face_step_up.claim_on_ramp_check') as claim, \
             mock.patch('config.views.requests.post', side_effect=__import__('requests').RequestException) as provider:
            response = guardarian_transaction_proxy(request)
        self.assertEqual(response.status_code, 502)
        provider.assert_called_once()
        preflight.assert_not_called()
        withdrawal.assert_not_called()
        claim.assert_not_called()

    def test_websocket_old_money_frames_denied_but_recovery_and_chat_work(self):
        async def run(path, payloads, client_headers=None):
            frames = iter([{'type': 'websocket.receive', 'text': json.dumps(p)} for p in payloads]
                          + [{'type': 'websocket.disconnect'}])
            delivered, sent = [], []
            async def receive():
                return next(frames)
            async def send(frame):
                sent.append(frame)
            async def app(scope, receive, send):
                while True:
                    frame = await receive()
                    if frame['type'] == 'websocket.disconnect':
                        break
                    delivered.append(json.loads(frame['text'])['type'])
            await FaceClientWebSocketMiddleware(app)({
                'path': path, 'headers': [(k.encode(), v.encode()) for k, v in (client_headers or {}).items()],
            }, receive, send)
            return delivered, sent
        delivered, sent = asyncio.run(run('/ws/presale_session', [
            {'type': 'prepare_request'}, {'type': 'submit_request'}, {'type': 'claim_submit'}, {'type': 'ping'}]))
        self.assertEqual(delivered, ['claim_submit', 'ping'])
        self.assertEqual(len(sent), 2)
        self.assertEqual(json.loads(sent[0]['text'])['code'], UPDATE_CODE)
        delivered, sent = asyncio.run(run('/ws/send_session', [{'type': 'submit_request'}], headers()))
        self.assertEqual(delivered, ['submit_request'])
        self.assertEqual(sent, [])

        for action in ('cancel', 'open_dispute'):
            delivered, sent = asyncio.run(run('/ws/p2p_session', [
                {'type': 'prepare', 'action': action}, {'type': 'submit', 'action': action}]))
            self.assertEqual(delivered, ['prepare', 'submit'])
            self.assertEqual(sent, [])
        for action in ('create', 'accept', 'confirm_received', None):
            delivered, sent = asyncio.run(run('/ws/p2p_session', [
                {'type': 'prepare', 'action': action}, {'type': 'submit', 'action': action}]))
            self.assertEqual(delivered, [])
            self.assertEqual(len(sent), 2)
        delivered, sent = asyncio.run(run('/ws/trade/123', [{'type': 'submit'}]))
        self.assertEqual(delivered, ['submit'])
        self.assertEqual(sent, [])

    def test_open_websocket_rechecks_switch_for_each_frame(self):
        async def run():
            frames = iter([{'type': 'websocket.receive', 'text': '{"type":"submit"}'},
                           {'type': 'websocket.receive', 'text': '{"type":"submit"}'},
                           {'type': 'websocket.disconnect'}])
            delivered, denied = [], []
            async def receive():
                return next(frames)
            async def send(frame):
                denied.append(frame)
            async def app(scope, receive, send):
                delivered.append(await receive())
                delivered.append(await receive())
            with mock.patch('security.face_client.step_up_enabled', side_effect=[False, True]):
                await FaceClientWebSocketMiddleware(app)({'path': '/ws/withdraw_session'}, receive, send)
            return delivered, denied
        delivered, denied = asyncio.run(run())
        self.assertEqual(delivered[-1]['type'], 'websocket.disconnect')
        self.assertEqual(len(denied), 1)
