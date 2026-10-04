import base64
import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings
from django.utils import timezone

from inbox.models import SupportConversation, SupportMessage
from users.models import Account, User

from . import service
from .engine import AssistantUnavailable, Toolbelt, TurnResult, Viewer, history_items, human_mode_active
from .models import AssistantThreadState, AssistantTurn


def text_response(text, usage=None):
    return {
        'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}],
        'usage': usage or {'input_tokens': 1000, 'output_tokens': 100,
                           'input_tokens_details': {'cached_tokens': 400}},
    }


def call_response(name, arguments, call_id='call_1'):
    return {
        'output': [{'type': 'function_call', 'name': name, 'arguments': arguments, 'call_id': call_id}],
        'usage': {'input_tokens': 900, 'output_tokens': 20},
    }


@override_settings(OPENAI_API_KEY='test-key')
class AskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='ana', email='ana@example.com', password='x', firebase_uid='fb-ana', first_name='Ana',
        )
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0)
        self.jwt = {'account_type': 'personal', 'account_index': 0, 'business_id': None}
        push = patch('assistant.service.send_support_staff_push')
        self.staff_push = push.start()
        self.addCleanup(push.stop)

    def ask(self, body, **kwargs):
        return service.ask(self.user, self.account, None, self.jwt, body, **kwargs)

    @patch('assistant.engine._openai_post')
    def test_navigation_turn_returns_action_and_meters_cost(self, post):
        post.side_effect = [
            call_response('navigate', '{"destination": "pay_qr"}'),
            text_response('Te abrí Pagar. Apunta la cámara al QR.'),
        ]
        outcome = self.ask('abre QR para pagar', screen='Home')

        self.assertEqual(outcome.actions, [{'type': 'navigate', 'destination': 'pay_qr'}])
        self.assertEqual(outcome.reply_message.sender_type, 'AGENT')
        self.assertTrue(outcome.reply_message.metadata['ai'])
        self.assertEqual(outcome.reply_message.metadata['actions'], outcome.actions)
        self.staff_push.assert_not_called()
        turn = AssistantTurn.objects.get()
        self.assertEqual(turn.input_tokens, 1900)
        self.assertEqual(turn.cached_input_tokens, 400)
        self.assertEqual(turn.output_tokens, 120)
        # Luna: 1500 fresh * 0.10 + 400 cached * 0.01 + 120 out * 0.50 per 1M
        self.assertEqual(turn.cost_usd, Decimal('0.000214'))
        self.assertEqual(turn.tools[0]['name'], 'navigate')
        # The tool output went back to the model in the second request.
        second_input = post.call_args_list[1].args[0]['input']
        self.assertEqual(second_input[-1]['type'], 'function_call_output')

    @patch('assistant.engine._openai_post')
    def test_unknown_destination_is_refused(self, post):
        post.side_effect = [
            call_response('navigate', '{"destination": "admin_panel"}'),
            text_response('No puedo abrir eso.'),
        ]
        outcome = self.ask('abre el panel de admin')
        self.assertEqual(outcome.actions, [])

    @patch('assistant.engine._openai_post')
    def test_asking_for_a_person_hands_off_without_a_model_call(self, post):
        with self.captureOnCommitCallbacks(execute=True):
            outcome = self.ask('Quiero hablar con una persona')

        post.assert_not_called()
        self.assertEqual(outcome.mode, 'HUMAN')
        self.assertTrue(outcome.reply_message.metadata.get('handoff'))
        self.staff_push.assert_called_once_with(outcome.user_message.id)

        with self.captureOnCommitCallbacks(execute=True):
            follow_up = self.ask('Mi retiro no llegó')
        post.assert_not_called()
        self.assertEqual(follow_up.mode, 'HUMAN')
        self.assertIsNone(follow_up.reply_message)
        self.assertEqual(self.staff_push.call_count, 2)

    @patch('assistant.engine._openai_post')
    def test_model_escalation_keeps_its_reply_and_pushes_staff(self, post):
        post.side_effect = [
            call_response('escalate_to_human', '{"reason": "Retiro pendiente 3 días"}'),
            text_response('Te paso con el equipo, lo revisan hoy.'),
        ]
        with self.captureOnCommitCallbacks(execute=True):
            outcome = self.ask('mi retiro lleva 3 días pendiente')
        self.assertEqual(outcome.mode, 'HUMAN')
        self.assertEqual(outcome.reply_message.body, 'Te paso con el equipo, lo revisan hoy.')
        state = AssistantThreadState.objects.get()
        self.assertEqual(state.handoff_reason, 'Retiro pendiente 3 días')
        self.staff_push.assert_called_once()

    @patch('assistant.engine._openai_post')
    def test_staff_reply_puts_thread_in_human_mode_until_user_returns(self, post):
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        staff = User.objects.create_user(username='susy', email='s@example.com', password='x',
                                         firebase_uid='fb-susy', is_staff=True)
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', sender_user=staff, body='Hola')

        self.assertEqual(self.ask('gracias').mode, 'HUMAN')
        post.assert_not_called()

        service.return_to_ai(self.user, self.account, None)
        post.side_effect = [text_response('¡De nada!')]
        self.assertEqual(self.ask('¿cómo pago con QR?').mode, 'AI')

    def test_human_mode_lapses_on_its_own(self):
        now = timezone.now()
        state = SimpleNamespace(handoff_at=now - timedelta(hours=25), returned_to_ai_at=None)
        self.assertFalse(human_mode_active(state, None, now=now))
        state.handoff_at = now - timedelta(hours=2)
        self.assertTrue(human_mode_active(state, None, now=now))
        self.assertFalse(human_mode_active(SimpleNamespace(handoff_at=None, returned_to_ai_at=None), None, now=now))

    @override_settings(CONFIO_ASSISTANT_DAILY_TURNS=1)
    @patch('assistant.engine._openai_post')
    def test_daily_limit(self, post):
        post.side_effect = [text_response('Hola')]
        self.ask('hola')
        outcome = self.ask('otra pregunta')
        self.assertEqual(post.call_count, 1)
        self.assertEqual(outcome.remaining_turns, 0)
        self.assertTrue(outcome.reply_message.metadata.get('limit'))

    @patch('assistant.engine._openai_post', side_effect=AssistantUnavailable('boom'))
    def test_outage_tells_the_user_and_is_recorded(self, post):
        outcome = self.ask('hola')
        self.assertEqual(outcome.reply_message.body, service.UNAVAILABLE_REPLY)
        self.assertEqual(AssistantTurn.objects.get().error, 'boom')

    @patch('assistant.engine._openai_post')
    def test_a_failing_tool_is_reported_as_failure_not_empty_data(self, post):
        post.side_effect = [
            call_response('get_month_summary', '{"months_back": 0}'),
            text_response('No pude consultarlo ahora.'),
        ]
        with patch('assistant.engine.month_summary_data', side_effect=RuntimeError('db down')):
            self.ask('¿cuánto gasté este mes?')
        tool_output = post.call_args_list[1].args[0]['input'][-1]['output']
        self.assertIn('error', tool_output)
        self.assertFalse(AssistantTurn.objects.get().tools[0]['ok'])

    @patch('assistant.engine._openai_post')
    def test_older_builds_get_no_navigate_tool(self, post):
        post.side_effect = [text_response('Pagar está en la pestaña del centro.')]
        outcome = self.ask('abre QR', can_navigate=False)
        tools = {t['name'] for t in post.call_args.args[0]['tools']}
        self.assertNotIn('navigate', tools)
        self.assertIn('nunca digas que abriste algo', post.call_args.args[0]['instructions'])
        self.assertEqual(outcome.actions, [])

    @patch('assistant.engine._openai_post')
    def test_portal_waits_only_on_messages_routed_to_the_team(self, post):
        post.side_effect = [text_response('Hola, ¿en qué te ayudo?')]
        self.ask('hola')
        conversation = SupportConversation.objects.get()
        recent = lambda: list(conversation.messages.order_by('-created_at'))  # noqa: E731
        self.assertFalse(service.awaiting_team(conversation, recent()))

        # The handoff reply comes from the AI, yet the thread now waits on people.
        self.ask('quiero hablar con una persona')
        self.assertTrue(service.awaiting_team(conversation, recent()))

        # Even after human mode lapses, an unanswered message stays visible.
        AssistantThreadState.objects.update(handoff_at=timezone.now() - timedelta(days=3))
        self.assertTrue(service.awaiting_team(conversation, recent()))

        staff = User.objects.create_user(username='s3', email='s3@example.com', password='x', firebase_uid='fb-s3')
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', sender_user=staff, body='Listo')
        self.assertFalse(service.awaiting_team(conversation, recent()))

    def test_pre_ia_threads_keep_the_old_rule(self):
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        SupportMessage.objects.create(conversation=conversation, sender_type='USER', sender_user=self.user, body='hola')
        self.assertTrue(service.awaiting_team(conversation, list(conversation.messages.order_by('-created_at'))))

    def test_history_attributes_people_and_ai(self):
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        staff = User.objects.create_user(username='s2', email='s2@example.com', password='x', firebase_uid='fb-s2')
        messages = [
            SupportMessage(conversation=conversation, sender_type='USER', body='hola'),
            SupportMessage(conversation=conversation, sender_type='AGENT', body='soy IA', metadata={'ai': True}),
            SupportMessage(conversation=conversation, sender_type='AGENT', sender_user=staff, body='soy Susy'),
        ]
        items = history_items(messages)
        self.assertEqual([i['role'] for i in items], ['user', 'assistant', 'assistant'])
        self.assertEqual(items[1]['content'], 'soy IA')
        self.assertTrue(items[2]['content'].startswith('[Equipo Confío, persona]'))


class EmployeeScopeTests(TestCase):
    def test_employee_gets_no_money_views_and_no_owner_screens(self):
        viewer = Viewer(user=None, account=None, account_type='business', business_id=7,
                        is_business_owner=False, tz=ZoneInfo('UTC'))
        belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=5)
        names = {spec['name'] for spec in belt.specs()}
        self.assertEqual(names, {'navigate', 'escalate_to_human'})
        self.assertNotIn('withdraw', belt.destinations)
        self.assertFalse(belt.navigate('withdraw')['ok'])
        self.assertFalse(belt.get_month_summary(0)['disponible'])
        self.assertFalse(belt.analyze_finances('¿cómo vamos?')['disponible'])

    def test_owner_gets_money_views(self):
        viewer = Viewer(user=None, account=None, account_type='business', business_id=7,
                        is_business_owner=True, tz=ZoneInfo('UTC'))
        names = {spec['name'] for spec in Toolbelt(viewer, TurnResult(reply=''), analyses_left=5).specs()}
        self.assertIn('get_month_summary', names)


class TranscribeValidationTests(TestCase):
    def test_rejects_bad_input_before_calling_out(self):
        with patch('assistant.service.requests.post') as post:
            with self.assertRaises(ValueError):
                service.transcribe('aGVsbG8=', 'video/mp4', 1000)
            with self.assertRaises(ValueError):
                service.transcribe('aGVsbG8=', 'audio/mp4', 10 * 60 * 1000)
            with self.assertRaises(ValueError):
                service.transcribe('not base64!!', 'audio/mp4', 1000)
            post.assert_not_called()


class DestinationContractTests(TestCase):
    def test_app_knows_every_destination_the_server_offers(self):
        import re
        from pathlib import Path

        from django.conf import settings as django_settings

        from .destinations import DESTINATIONS

        source = (Path(django_settings.BASE_DIR) / 'apps/src/assistant/destinations.ts').read_text()
        block = source[source.index('DESTINATION_TARGETS'):source.index('};', source.index('DESTINATION_TARGETS'))]
        app_keys = set(re.findall(r'^\s+(\w+): \{', block, re.MULTILINE))
        self.assertEqual(app_keys, set(DESTINATIONS))


# --------------------------------------------------------------------------- #
# Assistant+ billing
# --------------------------------------------------------------------------- #

from datetime import datetime, timezone as dt_timezone  # noqa: E402

from . import billing, voice  # noqa: E402
from .models import AssistantSubscription, VoiceSession  # noqa: E402


def _ms(dt):
    return int(dt.timestamp() * 1000)


_SIGNED = [1_000_000]


def apple_tx(user_token, *, expires_in=timedelta(days=30), product='confio_ia_plus_monthly', revoked=False,
             original='1000', tx='2000', signed_ms=None):
    now = timezone.now()
    _SIGNED[0] += 1000
    return SimpleNamespace(
        signedDate=signed_ms if signed_ms is not None else _SIGNED[0],
        productId=product, appAccountToken=str(user_token) if user_token else None,
        originalTransactionId=original, transactionId=tx, expiresDate=_ms(now + expires_in),
        revocationDate=_ms(now) if revoked else None, rawEnvironment='Sandbox', rawType='Auto-Renewable Subscription',
    )


class BillingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u1', email='u1@example.com', password='x', firebase_uid='fb-u1')
        self.other = User.objects.create_user(username='u2', email='u2@example.com', password='x', firebase_uid='fb-u2')
        self.token = billing.billing_token_for(self.user)

    def verify(self, tx, user=None):
        with patch('assistant.billing._apple_decode', return_value=tx):
            return billing.verify_apple_purchase(user or self.user, 'jws')

    def test_apple_purchase_unlocks_plus(self):
        self.assertFalse(billing.has_plus(self.user))
        sub = self.verify(apple_tx(self.token))
        self.assertEqual(sub.status, 'ACTIVE')
        self.assertTrue(billing.has_plus(self.user))
        self.assertEqual(service.daily_turn_cap(self.user), 300)

    def test_purchase_bound_to_another_user_is_refused(self):
        with self.assertRaises(billing.BillingError):
            self.verify(apple_tx(self.token), user=self.other)
        self.assertFalse(billing.has_plus(self.other))

    def test_purchase_without_our_token_is_refused(self):
        with self.assertRaises(billing.BillingError):
            self.verify(apple_tx(None))

    def test_other_products_are_refused(self):
        with self.assertRaises(billing.BillingError):
            self.verify(apple_tx(self.token, product='something_else'))

    def test_expired_and_refunded_lose_access(self):
        self.verify(apple_tx(self.token, expires_in=-timedelta(minutes=1)))
        self.assertFalse(billing.has_plus(self.user))
        self.verify(apple_tx(self.token, tx='2001'))
        self.assertTrue(billing.has_plus(self.user))
        self.verify(apple_tx(self.token, revoked=True, tx='2002'))
        self.assertFalse(billing.has_plus(self.user))
        self.assertEqual(AssistantSubscription.objects.count(), 1)

    def test_notification_renews_and_is_idempotent(self):
        self.verify(apple_tx(self.token, expires_in=timedelta(days=1)))
        note = SimpleNamespace(
            notificationUUID='n-1', rawNotificationType='DID_RENEW', rawSubtype=None,
            data=SimpleNamespace(signedTransactionInfo='tx', signedRenewalInfo=None),
        )
        renewed = apple_tx(self.token, expires_in=timedelta(days=31), tx='2003')

        def decode(method, signed):
            return note if method == 'verify_and_decode_notification' else renewed

        with patch('assistant.billing._apple_decode', side_effect=decode):
            billing.handle_apple_notification('payload')
            billing.handle_apple_notification('payload')
        sub = AssistantSubscription.objects.get()
        self.assertEqual(sub.latest_transaction_id, '2003')
        self.assertGreater(sub.expires_at, timezone.now() + timedelta(days=30))

    def test_google_purchase_is_read_from_play_and_acknowledged(self):
        expiry = (timezone.now() + timedelta(days=30)).astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        purchase = {
            'subscriptionState': 'SUBSCRIPTION_STATE_ACTIVE',
            'lineItems': [{'productId': 'confio_ia_plus_monthly', 'expiryTime': expiry,
                           'autoRenewingPlan': {'autoRenewEnabled': True}}],
            'externalAccountIdentifiers': {'obfuscatedExternalAccountId': str(self.token)},
            'acknowledgementState': 'ACKNOWLEDGEMENT_STATE_PENDING',
            'latestOrderId': 'GPA.1',
        }
        service_mock = unittest_mock_play(purchase)
        with patch('assistant.billing._play_service', return_value=service_mock):
            sub = billing.verify_google_purchase(self.user, 'tok-1')
        self.assertTrue(sub.acknowledged)
        self.assertTrue(billing.has_plus(self.user))
        service_mock.purchases().subscriptions().acknowledge.assert_called_once()

        with patch('assistant.billing._play_service', return_value=unittest_mock_play(purchase)):
            with self.assertRaises(billing.BillingError):
                billing.verify_google_purchase(self.other, 'tok-1')

    def test_purchases_are_refused_while_sales_are_dark(self):
        from .schema import VerifyAssistantPurchase
        info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        with patch('assistant.billing.verify_apple_purchase') as verify:
            result = VerifyAssistantPurchase.mutate.__wrapped__(VerifyAssistantPurchase, None, info,
                                                               platform='ios', signed_transaction='jws')
        verify.assert_not_called()
        self.assertFalse(result.success)
        self.assertFalse(result.plan.plus_sales_enabled)
        self.assertFalse(result.plan.voice_calls_enabled)

    def test_rtdn_requires_a_verified_pubsub_token(self):
        from django.test import RequestFactory

        from .views import google_play_notifications
        request = RequestFactory().post('/webhooks/google-play/', data='{}', content_type='application/json')
        self.assertEqual(google_play_notifications(request).status_code, 403)
        request = RequestFactory().post('/webhooks/google-play/', data='{}', content_type='application/json',
                                        HTTP_AUTHORIZATION='Bearer forged')
        with override_settings(CONFIO_ASSISTANT_RTDN_AUDIENCE='https://confio.lat/webhooks/google-play/',
                               CONFIO_ASSISTANT_RTDN_SERVICE_ACCOUNT='rtdn@confio.iam.gserviceaccount.com'):
            self.assertEqual(google_play_notifications(request).status_code, 403)


def unittest_mock_play(purchase):
    from unittest.mock import MagicMock
    service_mock = MagicMock()
    service_mock.purchases().subscriptionsv2().get().execute.return_value = purchase
    return service_mock


class VoiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='v1', email='v1@example.com', password='x', firebase_uid='fb-v1')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0)
        self.conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        self.viewer = Viewer(user=self.user, account=self.account, account_type='personal', business_id=None,
                             is_business_owner=False, tz=ZoneInfo('UTC'))

    def start(self):
        return voice.start_session(self.viewer, self.conversation, first_name='V', account_label='personal', country='BO')

    @override_settings(CONFIO_ASSISTANT_REALTIME_ENABLED=True)
    def test_voice_needs_ia_plus(self):
        with self.assertRaises(voice.VoiceUnavailable):
            self.start()

    def test_voice_is_off_at_launch_even_for_plus(self):
        with patch('assistant.billing.has_plus', return_value=True):
            with self.assertRaises(voice.VoiceUnavailable):
                self.start()

    @override_settings(OPENAI_API_KEY='k', CONFIO_ASSISTANT_PLUS_VOICE_MINUTES=10, CONFIO_ASSISTANT_REALTIME_ENABLED=True)
    def test_minutes_come_from_server_clock_and_cap_calls(self):
        with patch('assistant.billing.has_plus', return_value=True), \
                patch('assistant.voice.requests.post') as post:
            post.return_value = SimpleNamespace(status_code=200, json=lambda: {'value': 'ek_test'})
            session, left = self.start()
            self.assertEqual(left, 10)
            # The client secret stays on the server (connect() uses it).
            from django.core.cache import cache
            self.assertEqual(cache.get(voice._secret_key(session.id)), 'ek_test')
            sent = post.call_args.kwargs['json']['session']
            self.assertIn('get_transactions', {t['name'] for t in sent['tools']})
            # Nine minutes later, the cap is nearly spent no matter what the app claims.
            VoiceSession.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(minutes=9.8))
            session.refresh_from_db()
            self.assertTrue(voice.heartbeat(session))
            VoiceSession.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(minutes=11))
            session.refresh_from_db()
            self.assertFalse(voice.heartbeat(session))
            with self.assertRaises(voice.VoiceUnavailable):
                self.start()

    def test_navigate_is_never_a_server_tool(self):
        session = VoiceSession.objects.create(user=self.user, conversation=self.conversation, model='m')
        output, _ = voice.run_tool(session, self.viewer, 'navigate', '{"destination": "home"}', 5)
        self.assertIn('error', output)

    def test_usage_is_priced(self):
        session = VoiceSession.objects.create(user=self.user, conversation=self.conversation, model='gpt-realtime-2.1-mini')
        voice.record_usage(session, {'input_token_details': {'audio_tokens': 1_000_000},
                                     'output_token_details': {'audio_tokens': 500_000}})
        self.assertEqual(session.cost_usd, Decimal('20'))


class TransactionToolTests(TestCase):
    def setUp(self):
        self.viewer = Viewer(user=SimpleNamespace(id=1), account=SimpleNamespace(id=1), account_type='personal',
                             business_id=None, is_business_owner=False, tz=ZoneInfo('America/La_Paz'))

    def test_lists_own_movements_with_search(self):
        when = datetime(2026, 10, 2, 15, 0, tzinfo=dt_timezone.utc)
        movements = {
            'income': [SimpleNamespace(row_id=1, kind='income_person', direction='received', amount=Decimal('50'),
                                       counterparty_name='María', when=when, category=None)],
            'spending': [SimpleNamespace(row_id=2, kind='merchant', direction='sent', amount=Decimal('2.10'),
                                         counterparty_name='Yango', when=when, category=None)],
            'own_money': [],
        }
        from .engine import movements_data
        with patch('users.cashflow.month_movements', side_effect=lambda *a: movements[a[-1]]):
            data = movements_data(self.viewer, 0, 'all', 'yan', 10)
        self.assertEqual(data['total_encontrados'], 1)
        row = data['movimientos'][0]
        self.assertEqual((row['id'], row['monto_usd'], row['sentido'], row['categoria']), (2, '2.10', 'salió', 'sin categoría'))
        self.assertTrue(row['fecha'].startswith('2026-10-02 11:00'))

    def test_categorize_only_touches_this_accounts_spending(self):
        from .engine import categorize_movements
        spend = SimpleNamespace(kind='merchant', counterparty_key='business:9')
        with patch('users.cashflow.resolve_movement', side_effect=lambda *a, **k: (
                (SimpleNamespace(id=k['movement_id']), spend) if k['movement_id'] == 2 else (None, None))), \
                patch('users.models_cashflow.CounterpartyRule.objects.update_or_create') as rule:
            result = categorize_movements(self.viewer, [2, 999], 'transport', 'counterparty')
        self.assertEqual(result['clasificados'], 1)
        self.assertEqual(result['omitidos'], [999])
        rule.assert_called_once()
        self.assertEqual(rule.call_args.kwargs['defaults']['category'], 'transport')


class PetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='p1', email='p1@example.com', password='x', firebase_uid='fb-p1')
        self.other = User.objects.create_user(username='p2', email='p2@example.com', password='x', firebase_uid='fb-p2')

    def _response(self, payload, status=200):
        return SimpleNamespace(status_code=status, json=lambda: payload, text=json.dumps(payload),
                               raise_for_status=lambda: None)

    @override_settings(OPENAI_API_KEY='k', CONFIO_ASSISTANT_PET_FREE_PER_WEEK=1)
    def test_idea_creates_a_private_pet_within_the_weekly_limit(self):
        from . import pets
        image = base64.b64encode(b'png').decode()

        def post(url, **kwargs):
            if url.endswith('/moderations'):
                return self._response({'results': [{'flagged': False}]})
            return self._response({'data': [{'b64_json': image}], 'usage': {'output_tokens': 200}})

        with patch('assistant.pets.requests.post', side_effect=post), \
                patch('security.s3_utils.upload_object') as upload:
            pet = pets.create_pet(self.user, idea='una llama con poncho')
            self.assertEqual(pet.source, 'idea')
            self.assertTrue(pet.image_key.startswith(f'assistant/pets/{self.user.id}/'))
            upload.assert_called_once()
            with self.assertRaises(pets.PetError):
                pets.create_pet(self.user, idea='otra')

        with self.assertRaises(pets.PetError):
            pets.use_pet(self.other, pet.id)
        profile = pets.use_pet(self.user, pet.id)
        self.assertEqual(profile.mascot, 'CUSTOM')
        pets.delete_pet(self.user, pet.id)
        profile.refresh_from_db()
        self.assertEqual(profile.mascot, 'CONFI')

    @override_settings(OPENAI_API_KEY='k')
    def test_flagged_ideas_and_people_photos_are_refused(self):
        from . import pets
        with patch('assistant.pets.requests.post',
                   return_value=self._response({'results': [{'flagged': True}]})):
            with self.assertRaises(pets.PetError):
                pets.create_pet(self.user, idea='algo prohibido')

        def post(url, **kwargs):
            if url.endswith('/moderations'):
                return self._response({'results': [{'flagged': False}]})
            return self._response({'output_text': '{"persona": true, "animal_o_objeto": false}'})

        photo = base64.b64encode(b'jpeg').decode()
        with patch('assistant.pets.requests.post', side_effect=post) as mocked:
            with self.assertRaises(pets.PetError) as ctx:
                pets.create_pet(self.user, photo_base64=photo, photo_mime='image/jpeg')
        self.assertIn('sin personas', str(ctx.exception))
        self.assertFalse(any('/images/' in c.args[0] for c in mocked.call_args_list))

    @override_settings(OPENAI_API_KEY='k')
    def test_moderation_outage_fails_closed(self):
        import requests as _requests

        from . import pets
        with patch('assistant.pets.requests.post', side_effect=_requests.ConnectionError('down')):
            with self.assertRaises(pets.PetError):
                pets.create_pet(self.user, idea='una llama')




class AuditFixTests(TestCase):
    """Regressions for the 2026-10-04 Codex audit."""

    def setUp(self):
        self.user = User.objects.create_user(username='a1', email='a1@example.com', password='x', firebase_uid='fb-a1')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0)
        self.jwt = {'account_type': 'personal', 'account_index': 0, 'business_id': None}

    @override_settings(CONFIO_ASSISTANT_DAILY_TURNS=0, OPENAI_API_KEY='k')
    def test_voice_notes_over_quota_are_not_transcribed(self):
        with patch('assistant.service.requests.post') as post:
            outcome = service.ask(self.user, self.account, None, self.jwt, audio=('aGVsbG8=', 'audio/mp4', 3000))
        post.assert_not_called()
        self.assertEqual(outcome.remaining_turns, 0)

    @override_settings(OPENAI_API_KEY='k')
    def test_human_mode_voice_notes_are_metered(self):
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        AssistantThreadState.objects.create(conversation=conversation, handoff_at=timezone.now())
        with patch('assistant.service.transcribe', return_value=('no llegó mi retiro', 30.0)), \
                patch('assistant.service.send_support_staff_push'):
            outcome = service.ask(self.user, self.account, None, self.jwt, audio=('x', 'audio/mp4', 30000))
        self.assertEqual(outcome.mode, 'HUMAN')
        turn = AssistantTurn.objects.get()
        self.assertEqual(turn.modality, 'VOICE_NOTE')
        self.assertGreater(turn.cost_usd, 0)

    def test_an_unanswered_handoff_stays_visible_after_later_ai_messages(self):
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        SupportMessage.objects.create(conversation=conversation, sender_type='USER', sender_user=self.user,
                                      body='retiro atascado', metadata={'to_team': True})
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', body='Te paso con el equipo',
                                      metadata={'ai': True})
        SupportMessage.objects.create(conversation=conversation, sender_type='USER', sender_user=self.user,
                                      body='¿cómo pago con QR?')
        SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', body='Así…',
                                      metadata={'ai': True})
        recent = list(conversation.messages.order_by('-created_at'))
        self.assertTrue(service.awaiting_team(conversation, recent))

    def test_billing_token_is_set_once(self):
        first = billing.billing_token_for(self.user)
        self.assertEqual(billing.billing_token_for(self.user), first)

    def test_older_apple_payload_cannot_undo_a_refund(self):
        token = billing.billing_token_for(self.user)
        with patch('assistant.billing._apple_decode', return_value=apple_tx(token, signed_ms=5_000)):
            billing.verify_apple_purchase(self.user, 'jws')
        with patch('assistant.billing._apple_decode', return_value=apple_tx(token, revoked=True, signed_ms=9_000)):
            billing.verify_apple_purchase(self.user, 'jws')
        self.assertFalse(billing.has_plus(self.user))
        # The original purchase JWS, replayed after the refund.
        with patch('assistant.billing._apple_decode', return_value=apple_tx(token, signed_ms=5_000)):
            billing.verify_apple_purchase(self.user, 'jws')
        self.assertFalse(billing.has_plus(self.user))

    @override_settings(OPENAI_API_KEY='k')
    def test_malformed_moderation_verdicts_are_not_clean(self):
        from . import pets
        for payload in ({}, {'results': []}, {'results': [{}]}):
            with patch('assistant.pets.requests.post', return_value=SimpleNamespace(
                    status_code=200, json=lambda p=payload: p, raise_for_status=lambda: None)):
                with self.assertRaises(pets.PetError):
                    pets._moderate(text='una llama')

    def test_transient_play_failures_are_not_acknowledged(self):
        from django.test import RequestFactory

        from .views import google_play_notifications
        envelope = {'message': {'messageId': 'm1', 'data': base64.b64encode(json.dumps({
            'packageName': 'com.Confio.Confio',
            'subscriptionNotification': {'purchaseToken': 't', 'notificationType': 2}}).encode()).decode()}}
        request = RequestFactory().post('/webhooks/google-play/', data=json.dumps(envelope),
                                        content_type='application/json')
        with patch('assistant.billing.verify_rtdn_push', return_value=True), \
                patch('assistant.billing._play_apply', side_effect=billing.BillingTransient('down')):
            self.assertEqual(google_play_notifications(request).status_code, 503)

    @override_settings(CONFIO_ASSISTANT_REALTIME_ENABLED=True)
    def test_voice_tools_stay_on_the_account_the_call_started_on(self):
        other = Account.objects.create(user=self.user, account_type='personal', account_index=1)
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        session = VoiceSession.objects.create(user=self.user, conversation=conversation, model='m',
                                              account_id=self.account.id)
        with patch('assistant.billing.has_plus', return_value=True):
            self.assertTrue(voice.session_allowed(session, self.account, None))
            self.assertFalse(voice.session_allowed(session, other, None))
            voice.hang_up(session)
            self.assertFalse(voice.session_allowed(session, self.account, None))

    @override_settings(CONFIO_ASSISTANT_REALTIME_ENABLED=True, OPENAI_API_KEY='k')
    def test_server_hangs_up_silent_calls(self):
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        session = VoiceSession.objects.create(user=self.user, conversation=conversation, model='m',
                                              account_id=self.account.id, call_id='rtc_123')
        VoiceSession.objects.filter(pk=session.pk).update(last_seen_at=timezone.now() - timedelta(minutes=5))
        failing = SimpleNamespace(status_code=500)
        ok = SimpleNamespace(status_code=200)
        with patch('assistant.billing.has_plus', return_value=True), \
                patch('assistant.voice.requests.post', return_value=failing) as post:
            self.assertEqual(voice.enforce_sessions(), 1)
        self.assertIn('/realtime/calls/rtc_123/hangup', post.call_args.args[0])
        session.refresh_from_db()
        self.assertIsNotNone(session.ended_at)
        self.assertFalse(session.remote_ended)  # OpenAI didn't confirm: retried
        with patch('assistant.voice.requests.post', return_value=ok) as post:
            voice.enforce_sessions()
        post.assert_called_once()
        session.refresh_from_db()
        self.assertTrue(session.remote_ended)



def _box(kind, payload):
    import struct
    return struct.pack('>I', len(payload) + 8) + kind + payload


def fake_m4a(seconds, timescale=1000, decoy_seconds=None, fragmented=False):
    """Minimal MPEG-4: moov/trak/mdia/{mdhd, minf/stbl/stts} with `seconds` of
    samples. decoy_seconds puts a fake mvhd inside a free box up front."""
    import struct
    stts = _box(b'stts', bytes(4) + struct.pack('>III', 1, max(int(seconds * timescale), 0), 1)) if seconds else \
        _box(b'stts', bytes(4) + struct.pack('>I', 0))
    mdhd = _box(b'mdhd', bytes(4) + struct.pack('>IIII', 0, 0, timescale, int(seconds * timescale)) + bytes(4))
    trak = _box(b'trak', _box(b'mdia', mdhd + _box(b'minf', _box(b'stbl', stts))))
    head = b''
    if decoy_seconds is not None:
        head = _box(b'free', b'mvhd' + bytes(4) + struct.pack('>IIII', 0, 0, 1000, int(decoy_seconds * 1000)))
    tail = _box(b'moof', bytes(8)) if fragmented else b''
    return _box(b'ftyp', b'M4A ' + bytes(4)) + head + _box(b'moov', trak) + tail + _box(b'mdat', bytes(64))


class SecondPassTests(TestCase):
    """Regressions for the second Codex pass."""

    def setUp(self):
        self.user = User.objects.create_user(username='s1', email='s1@example.com', password='x', firebase_uid='fb-s1')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0)
        self.jwt = {'account_type': 'personal', 'account_index': 0, 'business_id': None}

    @override_settings(OPENAI_API_KEY='k')
    def test_voice_notes_without_a_duration_are_still_metered(self):
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        AssistantThreadState.objects.create(conversation=conversation, handoff_at=timezone.now())
        audio = base64.b64encode(fake_m4a(20)).decode()
        response = SimpleNamespace(status_code=200, json=lambda: {'text': 'mi retiro'})
        with patch('assistant.service.requests.post', return_value=response), \
                patch('assistant.service.send_support_staff_push'):
            service.ask(self.user, self.account, None, self.jwt, audio=(audio, 'audio/mp4', None))
        turn = AssistantTurn.objects.get()
        self.assertGreaterEqual(float(turn.audio_seconds), 19)
        self.assertGreater(turn.cost_usd, 0)

    @override_settings(OPENAI_API_KEY='k', CONFIO_ASSISTANT_DAILY_ANALYSES=1)
    def test_analysis_slots_are_reserved(self):
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        turn = AssistantTurn.objects.create(user=self.user, conversation=conversation, error='pending')
        reserve = service._analysis_reserver(self.user, turn)
        self.assertTrue(reserve())
        self.assertFalse(reserve())  # the second concurrent analysis sees the first

    @override_settings(OPENAI_API_KEY='k')
    def test_an_escalation_survives_a_failed_follow_up(self):
        from .engine import AssistantUnavailable
        calls = [call_response('escalate_to_human', '{"reason": "retiro atascado"}'), AssistantUnavailable('down')]
        with patch('assistant.engine._openai_post', side_effect=calls), \
                patch('assistant.service.send_support_staff_push'):
            outcome = service.ask(self.user, self.account, None, self.jwt, 'mi retiro no llega')
        self.assertEqual(outcome.mode, 'HUMAN')
        self.assertTrue(AssistantThreadState.objects.get().handoff_at)

    @override_settings(OPENAI_API_KEY='k', CONFIO_ASSISTANT_PET_FREE_PER_WEEK=1)
    def test_failed_pet_creation_gives_the_slot_back(self):
        from . import pets
        with patch('assistant.pets._create_pet', side_effect=pets.PetError('boom')):
            with self.assertRaises(pets.PetError):
                pets.create_pet(self.user, idea='una llama')
        self.assertEqual(pets.creations_left(self.user)[0], 1)

    @override_settings(CONFIO_ASSISTANT_REALTIME_ENABLED=True, OPENAI_API_KEY='k')
    def test_connect_records_the_call_and_never_reuses_the_secret(self):
        from django.core.cache import cache
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        session = VoiceSession.objects.create(user=self.user, conversation=conversation, model='m',
                                              account_id=self.account.id)
        cache.set(voice._secret_key(session.id), 'ek_1', 120)
        answer = SimpleNamespace(status_code=201, text='v=0 answer', headers={'Location': '/v1/realtime/calls/rtc_9'})
        with patch('assistant.voice.requests.post', return_value=answer):
            self.assertEqual(voice.connect(session, 'v=0 offer'), 'v=0 answer')
        session.refresh_from_db()
        self.assertEqual(session.call_id, 'rtc_9')
        with self.assertRaises(voice.VoiceUnavailable):
            voice.connect(session, 'v=0 offer')

    @override_settings(CONFIO_ASSISTANT_REALTIME_ENABLED=True)
    def test_ended_calls_accept_no_more_transcripts(self):
        from .schema import LogAssistantVoice
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        session = VoiceSession.objects.create(user=self.user, conversation=conversation, model='m',
                                              account_id=self.account.id, ended_at=timezone.now(), remote_ended=True)
        info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        with patch('assistant.schema.get_context_models', return_value=(self.user, self.account, None, self.jwt)):
            result = LogAssistantVoice.mutate.__wrapped__(
                LogAssistantVoice, None, info, session_id=str(session.id),
                transcript=[SimpleNamespace(role='user', text='replay')], ended=True)
        self.assertFalse(result.keep_going)
        self.assertFalse(conversation.messages.filter(body='replay').exists())



class ThirdPassTests(TestCase):
    """Regressions for the third Codex pass."""

    def setUp(self):
        self.user = User.objects.create_user(username='t1', email='t1@example.com', password='x', firebase_uid='fb-t1')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0)

    @override_settings(OPENAI_API_KEY='k')
    def test_media_duration_comes_from_the_file(self):
        self.assertAlmostEqual(service.mp4_duration_seconds(fake_m4a(37)), 37)
        long_note = base64.b64encode(fake_m4a(8 * 60)).decode()
        with patch('assistant.service.requests.post') as post:
            with self.assertRaises(ValueError):
                service.transcribe(long_note, 'audio/mp4', 5000)  # reports 5 s, file says 8 min
            with self.assertRaises(ValueError):
                service.transcribe(base64.b64encode(b'no header').decode(), 'audio/mp4', 5000)
            with self.assertRaises(ValueError):
                service.transcribe(long_note, 'audio/mpeg', 5000)  # only what the app records
        post.assert_not_called()

    def test_heartbeat_cannot_reopen_an_ended_call(self):
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        session = VoiceSession.objects.create(user=self.user, conversation=conversation, model='m',
                                              account_id=self.account.id)
        stale = VoiceSession.objects.get(pk=session.pk)
        VoiceSession.objects.filter(pk=session.pk).update(ended_at=timezone.now())
        self.assertFalse(voice.heartbeat(stale))
        self.assertIsNotNone(VoiceSession.objects.get(pk=session.pk).ended_at)

    @override_settings(OPENAI_API_KEY='k')
    def test_a_hangup_during_the_handshake_cuts_the_new_call(self):
        from django.core.cache import cache
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        session = VoiceSession.objects.create(user=self.user, conversation=conversation, model='m',
                                              account_id=self.account.id)
        cache.set(voice._secret_key(session.id), 'ek', 120)

        def provider(url, **kwargs):
            if url.endswith('/realtime/calls'):
                # The user hangs up while OpenAI is answering.
                VoiceSession.objects.filter(pk=session.pk).update(ended_at=timezone.now(), remote_ended=True)
                return SimpleNamespace(status_code=201, text='answer', headers={'Location': '/v1/realtime/calls/rtc_7'})
            return SimpleNamespace(status_code=200)

        with patch('assistant.voice.requests.post', side_effect=provider) as post:
            with self.assertRaises(voice.VoiceUnavailable):
                voice.connect(session, 'offer')
        self.assertTrue(any('/rtc_7/hangup' in c.args[0] for c in post.call_args_list))
        self.assertTrue(VoiceSession.objects.get(pk=session.pk).remote_ended)

    @override_settings(OPENAI_API_KEY='k', CONFIO_ASSISTANT_PET_FREE_PER_WEEK=1)
    def test_rejected_pets_use_the_slot_but_outages_do_not(self):
        from . import pets
        with patch('assistant.pets._create_pet', side_effect=pets.PetError('outage')):
            with self.assertRaises(pets.PetError):
                pets.create_pet(self.user, idea='una llama')
        self.assertEqual(pets.creations_left(self.user)[0], 1)
        with patch('assistant.pets._create_pet', side_effect=pets.PetRejected('persona')):
            with self.assertRaises(pets.PetRejected):
                pets.create_pet(self.user, idea='una llama')
        self.assertEqual(pets.creations_left(self.user)[0], 0)

    def test_replaying_the_same_apple_transaction_keeps_renewal_state(self):
        token = billing.billing_token_for(self.user)
        tx = apple_tx(token, signed_ms=7_000)
        renewal = SimpleNamespace(gracePeriodExpiresDate=None, autoRenewStatus=0, isInBillingRetryPeriod=False)
        with patch('assistant.billing._apple_decode', return_value=tx):
            billing._apple_apply(tx, renewal=renewal)
            billing.verify_apple_purchase(self.user, 'jws')  # same transaction, no renewal info
        sub = AssistantSubscription.objects.get()
        self.assertFalse(sub.auto_renew)



class FourthPassTests(TestCase):
    """Regressions for the fourth Codex pass."""

    def setUp(self):
        self.user = User.objects.create_user(username='f1', email='f1@example.com', password='x', firebase_uid='fb-f1')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0)

    def test_zero_duration_headers_are_refused(self):
        with patch('assistant.service.requests.post') as post:
            with self.assertRaises(ValueError):
                service.transcribe(base64.b64encode(fake_m4a(0)).decode(), 'audio/mp4', None)
        post.assert_not_called()

    @override_settings(OPENAI_API_KEY='k')
    def test_provider_reported_duration_is_metered(self):
        response = SimpleNamespace(status_code=200, json=lambda: {
            'text': 'hola', 'usage': {'type': 'duration', 'seconds': 95}})
        with patch('assistant.service.requests.post', return_value=response):
            text, seconds = service.transcribe(base64.b64encode(fake_m4a(5)).decode(), 'audio/mp4', 5000)
        self.assertEqual(text, 'hola')
        self.assertEqual(seconds, 95)

    @override_settings(OPENAI_API_KEY='k')
    def test_hangup_reads_the_latest_call_id(self):
        conversation = SupportConversation.objects.create(user=self.user, account=self.account, status='OPEN')
        session = VoiceSession.objects.create(user=self.user, conversation=conversation, model='m',
                                              account_id=self.account.id)
        stale = VoiceSession.objects.get(pk=session.pk)  # loaded before connect() recorded the call
        VoiceSession.objects.filter(pk=session.pk).update(call_id='rtc_5')
        with patch('assistant.voice.requests.post', return_value=SimpleNamespace(status_code=200)) as post:
            voice.hang_up(stale)
        self.assertIn('/rtc_5/hangup', post.call_args.args[0])
        self.assertTrue(VoiceSession.objects.get(pk=session.pk).remote_ended)

    def test_bare_apple_verification_keeps_a_granted_grace_period(self):
        token = billing.billing_token_for(self.user)
        expired = apple_tx(token, expires_in=-timedelta(hours=1), signed_ms=1_000)
        renewal = SimpleNamespace(gracePeriodExpiresDate=int((timezone.now() + timedelta(days=3)).timestamp() * 1000),
                                  autoRenewStatus=1, isInBillingRetryPeriod=True)
        billing._apple_apply(expired, renewal=renewal)
        self.assertTrue(billing.has_plus(self.user))
        newer = apple_tx(token, expires_in=-timedelta(hours=1), signed_ms=2_000)
        with patch('assistant.billing._apple_decode', return_value=newer):
            billing.verify_apple_purchase(self.user, 'jws')
        self.assertTrue(billing.has_plus(self.user))



class FifthPassTests(TestCase):
    def test_real_sample_duration_beats_a_decoy_header(self):
        data = fake_m4a(30 * 60, decoy_seconds=5)
        self.assertAlmostEqual(service.mp4_duration_seconds(data), 30 * 60)
        with patch('assistant.service.requests.post') as post:
            with self.assertRaises(ValueError):
                service.transcribe(base64.b64encode(data).decode(), 'audio/mp4', 5000)
        post.assert_not_called()

    def test_fragmented_files_are_refused(self):
        self.assertIsNone(service.mp4_duration_seconds(fake_m4a(10, fragmented=True)))

    @override_settings(OPENAI_API_KEY='k')
    def test_a_full_two_minute_note_is_accepted(self):
        response = SimpleNamespace(status_code=200, json=lambda: {'text': 'ok'})
        with patch('assistant.service.requests.post', return_value=response):
            _, seconds = service.transcribe(base64.b64encode(fake_m4a(120)).decode(), 'audio/mp4', 120000)
        self.assertEqual(seconds, 120)



class ThirteenthPassTests(TestCase):
    @override_settings(OPENAI_API_KEY='k')
    def test_saved_categories_survive_a_failed_follow_up(self):
        from .engine import AssistantUnavailable
        user = User.objects.create_user(username='w1', email='w1@example.com', password='x', firebase_uid='fb-w1')
        account = Account.objects.create(user=user, account_type='personal', account_index=0)
        calls = [call_response('categorize_transactions', '{"ids": [5], "category": "food", "apply_to": "movement"}'),
                 AssistantUnavailable('down')]
        with patch('assistant.engine._openai_post', side_effect=calls), \
                patch('assistant.engine.categorize_movements',
                      return_value={'ok': True, 'clasificados': 1, 'omitidos': [], 'categoria': 'Comida',
                                    'alcance': 'solo esos movimientos'}):
            outcome = service.ask(user, account, None, {'account_type': 'personal', 'account_index': 0},
                                  'esos pagos eran comida')
        self.assertTrue(outcome.data_changed)



class SeventeenthPassTests(TestCase):
    @override_settings(OPENAI_API_KEY='k')
    def test_a_staff_takeover_during_generation_silences_the_ai(self):
        user = User.objects.create_user(username='h1', email='h1@example.com', password='x', firebase_uid='fb-h1')
        account = Account.objects.create(user=user, account_type='personal', account_index=0)
        staff = User.objects.create_user(username='h2', email='h2@example.com', password='x', firebase_uid='fb-h2')

        def model(payload):
            # Susy answers while the model is thinking.
            conversation = SupportConversation.objects.get(user=user)
            SupportMessage.objects.create(conversation=conversation, sender_type='AGENT', sender_user=staff,
                                          body='Hola, te ayudo yo')
            return call_response('navigate', '{"destination": "pay_qr"}') if False else text_response('Abre Pagar')

        with patch('assistant.engine._openai_post', side_effect=model), \
                patch('assistant.service.send_support_staff_push'):
            outcome = service.ask(user, account, None, {'account_type': 'personal', 'account_index': 0}, 'hola')
        self.assertEqual(outcome.mode, 'HUMAN')
        self.assertIsNone(outcome.reply_message)
        self.assertFalse(SupportMessage.objects.filter(body='Abre Pagar').exists())
