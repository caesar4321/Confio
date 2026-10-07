from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from users import paid_offers
from users.models import FunnelEvent
from users.models_product_waitlist import ProductWaitlistEntry
from users.product_waitlist_schema import AnswerPaidOffer, JoinPaidOfferWaitlist, PaidOfferQueries

NEW_BUILD = {'HTTP_X_CONFIO_VERSION': '5.1.10'}
OLD_BUILD = {'HTTP_X_CONFIO_VERSION': '5.1.9'}
PROBES_ON = dict(IA_PLUS_PROBE_ENABLED=True, SMART_ACCOUNT_PROBE_ENABLED=True,
                 PAID_OFFER_MIN_APP_VERSION='5.1.10', IA_PLUS_MONTHLY_PRICE_USD='9.99',
                 SMART_ACCOUNT_MONTHLY_PRICE_USD='9.99')


def _resolve(info):
    # The resolver unwrapped from @login_required (which needs a real GraphQL info).
    return PaidOfferQueries.resolve_paid_offers.__wrapped__(None, info)


def _info(user=None, meta=None):
    return SimpleNamespace(context=SimpleNamespace(user=user, META=meta if meta is not None else NEW_BUILD))


@override_settings(**PROBES_ON)
class PaidOfferRulesTests(TestCase):
    """Who sees each door: flag on, never employees, never old builds; the
    Billeteras row only for people who ever funded."""

    def test_each_door_needs_its_flag_a_new_build_and_not_an_employee(self):
        self.assertTrue(paid_offers.available('ia_plus', is_employee=False, meta=NEW_BUILD))
        self.assertFalse(paid_offers.available('ia_plus', is_employee=True, meta=NEW_BUILD))
        self.assertFalse(paid_offers.available('ia_plus', is_employee=False, meta=OLD_BUILD))
        self.assertFalse(paid_offers.available('ia_plus', is_employee=False, meta={}))
        with override_settings(IA_PLUS_PROBE_ENABLED=False):
            self.assertFalse(paid_offers.available('ia_plus', is_employee=False, meta=NEW_BUILD))
            # One flag off never turns the other offer off.
            self.assertTrue(paid_offers.available('smart_account', is_employee=False, meta=NEW_BUILD))
        self.assertFalse(paid_offers.available('loans', is_employee=False, meta=NEW_BUILD))

    def test_row_needs_ever_funded(self):
        self.assertTrue(paid_offers.billeteras_row_visible(is_employee=False, meta=NEW_BUILD, funded=True))
        self.assertFalse(paid_offers.billeteras_row_visible(is_employee=False, meta=NEW_BUILD, funded=False))

    def test_price_is_a_server_value_or_hidden(self):
        self.assertEqual(paid_offers.price('ia_plus'), '9.99')
        with override_settings(IA_PLUS_MONTHLY_PRICE_USD=''):
            self.assertIsNone(paid_offers.price('ia_plus'))
        with override_settings(IA_PLUS_MONTHLY_PRICE_USD='gratis'):
            self.assertIsNone(paid_offers.price('ia_plus'))

    def test_no_floor_configured_means_no_build_qualifies(self):
        with override_settings(PAID_OFFER_MIN_APP_VERSION=''):
            self.assertFalse(paid_offers.client_supports(NEW_BUILD))


@override_settings(**PROBES_ON)
class PaidOfferWaitlistTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.ana = User.objects.create_user(username='ana', firebase_uid='uid-ana', phone_country='PE')
        who = patch('users.product_waitlist_schema._who', side_effect=lambda info: (info.context.user, False, 'personal'))
        who.start()
        self.addCleanup(who.stop)

    def join(self, user=None, meta=None, **kwargs):
        args = {'product': 'smart_account', 'door': 'billeteras', **kwargs}
        return JoinPaidOfferWaitlist.mutate(None, _info(user or self.ana, meta), **args)

    def test_join_snapshots_the_person_and_is_idempotent(self):
        with patch('users.funding.has_funded', return_value=True), \
                self.captureOnCommitCallbacks(execute=True):
            first = self.join(trigger='')
            second = self.join(door='chip', trigger='asked')
        self.assertTrue(first.success and second.success)
        entry = ProductWaitlistEntry.objects.get()
        # Door and trigger of the FIRST join; the second tap moves nothing.
        self.assertEqual((entry.door, entry.trigger, entry.account_type, entry.funded, entry.country),
                         ('billeteras', '', 'personal', True, 'PE'))
        self.assertEqual(first.waitlisted_at, second.waitlisted_at)
        self.assertEqual(FunnelEvent.objects.filter(event_name='paid_offer_interest',
                                                    properties__stage='avisame_tapped').count(), 1)

    def test_join_refuses_unknown_values_old_builds_and_employees(self):
        self.assertFalse(self.join(product='loans').success)
        self.assertFalse(self.join(door='banner').success)
        self.assertFalse(self.join(trigger='push').success)
        self.assertFalse(self.join(meta=OLD_BUILD).success)
        with patch('users.product_waitlist_schema._who', return_value=(self.ana, True, 'business')):
            self.assertFalse(self.join().success)
        self.assertFalse(JoinPaidOfferWaitlist.mutate(None, _info(SimpleNamespace(is_authenticated=False)),
                                                      product='ia_plus', door='chip').success)
        self.assertEqual(ProductWaitlistEntry.objects.count(), 0)

    def test_answers_need_a_join_and_valid_values(self):
        answer = lambda **kw: AnswerPaidOffer.mutate(None, _info(self.ana), **kw)  # noqa: E731
        self.assertFalse(answer(product='smart_account', would_pay='yes').success)  # not joined yet
        with patch('users.funding.has_funded', return_value=False):
            self.join()
        self.assertFalse(answer(product='smart_account', would_pay='maybe').success)
        self.assertFalse(answer(product='smart_account', volume_range='a lot').success)
        self.assertFalse(answer(product='smart_account').success)
        self.assertTrue(answer(product='smart_account', would_pay='yes').success)
        self.assertTrue(answer(product='smart_account', volume_range='100_500').success)
        entry = ProductWaitlistEntry.objects.get()
        self.assertEqual((entry.would_pay, entry.volume_range), ('yes', '100_500'))
        # Confío IA+ has no volume question.
        with patch('users.funding.has_funded', return_value=False):
            self.join(product='ia_plus', door='assistant_header')
        self.assertFalse(answer(product='ia_plus', volume_range='100_500').success)

    def test_query_reports_doors_price_and_waitlist_state(self):
        with patch('users.funding.has_funded', return_value=False):
            self.join(product='ia_plus', door='chip', trigger='investing')
        with patch('users.funding.has_funded', return_value=True):
            offers = {o.product: o for o in _resolve(_info(self.ana))}
        self.assertTrue(offers['ia_plus'].on_waitlist)
        self.assertFalse(offers['ia_plus'].row_visible)  # the row is Cuenta inteligente's only
        self.assertTrue(offers['smart_account'].row_visible)
        self.assertFalse(offers['smart_account'].on_waitlist)
        self.assertEqual(offers['smart_account'].monthly_price_usd, '9.99')
        with patch('users.funding.has_funded', return_value=True):
            old = {o.product: o for o in _resolve(_info(self.ana, OLD_BUILD))}
        self.assertFalse(old['smart_account'].available or old['smart_account'].row_visible)


@override_settings(IA_PLUS_PROBE_ENABLED=False, SMART_ACCOUNT_PROBE_ENABLED=False,
                   PAID_OFFER_MIN_APP_VERSION='5.1.10', PAID_OFFER_PREVIEW_USER_IDS='5, 7')
class PaidOfferPreviewTests(TestCase):
    def test_listed_people_preview_while_the_flags_are_off(self):
        self.assertTrue(paid_offers.available('ia_plus', is_employee=False, meta=NEW_BUILD, user_id=5))
        self.assertTrue(paid_offers.available('smart_account', is_employee=False, meta=NEW_BUILD, user_id=7))
        self.assertFalse(paid_offers.available('ia_plus', is_employee=False, meta=NEW_BUILD, user_id=55))
        self.assertFalse(paid_offers.available('ia_plus', is_employee=False, meta=NEW_BUILD))
        # A preview never bypasses the employee rule; it does skip the build
        # floor (a pre-release test build), for listed ids only.
        self.assertFalse(paid_offers.available('ia_plus', is_employee=True, meta=NEW_BUILD, user_id=5))
        self.assertTrue(paid_offers.available('ia_plus', is_employee=False, meta=OLD_BUILD, user_id=5))
        self.assertFalse(paid_offers.available('ia_plus', is_employee=False, meta=OLD_BUILD, user_id=55))


@override_settings(**PROBES_ON)
class PaidOfferAuditFixTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.ana = User.objects.create_user(username='ana2', firebase_uid='uid-ana2', phone_country='CO')
        who = patch('users.product_waitlist_schema._who', side_effect=lambda info: (info.context.user, False, 'personal'))
        who.start()
        self.addCleanup(who.stop)

    def test_a_chip_join_gets_the_trigger_the_server_logged(self):
        FunnelEvent.objects.create(event_name='paid_offer_interest', user=self.ana, source_type='ia_plus',
                                   properties={'stage': 'door_shown', 'door': 'chip', 'trigger': 'investing'})
        with patch('users.funding.has_funded', return_value=True):
            first = JoinPaidOfferWaitlist.mutate(None, _info(self.ana), product='ia_plus', door='chip')
            again = JoinPaidOfferWaitlist.mutate(None, _info(self.ana), product='ia_plus', door='chip')
        self.assertEqual(ProductWaitlistEntry.objects.get().trigger, 'investing')
        self.assertFalse(first.already_listed)
        self.assertTrue(again.already_listed)

    def test_assistant_plus_subscribers_are_never_pitched_ia_plus(self):
        from datetime import timedelta

        from django.utils import timezone

        from assistant.models import AssistantSubscription
        AssistantSubscription.objects.create(user=self.ana, platform='android', store_key='k', product_id='p',
                                             status='ACTIVE', expires_at=timezone.now() + timedelta(days=30))
        self.assertFalse(paid_offers.available('ia_plus', is_employee=False, meta=NEW_BUILD, user_id=self.ana.pk))
        self.assertTrue(paid_offers.available('smart_account', is_employee=False, meta=NEW_BUILD, user_id=self.ana.pk))

    def test_clients_cannot_write_server_stages(self):
        from users.funnel_schema import _client_paid_offer_stage
        self.assertTrue(_client_paid_offer_stage({'stage': 'door_shown', 'door': 'billeteras'}))
        self.assertTrue(_client_paid_offer_stage({'stage': 'detail_opened'}))
        self.assertTrue(_client_paid_offer_stage({'stage': 'solo_miraba'}))
        for forged in ({'stage': 'door_shown', 'door': 'chip'}, {'stage': 'avisame_tapped'},
                       {'stage': 'would_pay_answered'}, {}):
            self.assertFalse(_client_paid_offer_stage(forged), forged)


class ChipEventTriggerTests(TestCase):
    def test_client_chip_events_get_the_server_trigger(self):
        from users.funnel_schema import TrackFunnelEvent
        ana = get_user_model().objects.create_user(username='ana3', firebase_uid='uid-ana3')
        FunnelEvent.objects.create(event_name='paid_offer_interest', user=ana, source_type='smart_account',
                                   properties={'stage': 'door_shown', 'door': 'chip', 'trigger': 'pain_point'})
        with self.captureOnCommitCallbacks(execute=True):
            TrackFunnelEvent.mutate(None, _info(ana), event_name='paid_offer_interest', source_type='smart_account',
                                    properties='{"stage": "detail_opened", "offer": "smart_account", "door": "chip"}')
        opened = FunnelEvent.objects.get(properties__stage='detail_opened')
        self.assertEqual(opened.properties['trigger'], 'pain_point')
