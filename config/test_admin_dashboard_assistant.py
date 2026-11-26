"""The Confío IA dashboard tab (config/admin_dashboard_assistant.py)."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from config import admin_dashboard_assistant as ia
from config.admin_dashboard_sections import Window


class ToolCategoryTests(TestCase):
    def test_tools_and_their_outcomes_map_to_what_was_asked(self):
        for name, expected in (
                ('prepare_payment', 'payment'), ('propose_stock_trade:denied', 'trade'), ('trade:answered', 'trade'),
                ('start_store_task', 'shopping'), ('start_store_task:denied', 'shopping'),
                ('propose_comprar_purchase', 'comprar'), ('propose_smart_account_rule', 'cuenta'),
                ('navigate', 'guide'), ('show_steps', 'guide'), ('escalate_to_human:denied', 'human'),
                ('get_portfolio', 'info'), ('smart_account_rules', 'info'), ('', 'info')):
            self.assertEqual(ia.tool_category(name), expected, name)

    def test_a_tool_entry_is_a_name_or_a_dict(self):
        self.assertEqual(ia.tool_name({'name': 'navigate'}), 'navigate')
        self.assertEqual(ia.tool_name('get_portfolio'), 'get_portfolio')
        self.assertEqual(ia.tool_name(None), '')


class RepeatPayerTests(TestCase):
    def test_only_payers_whose_window_is_up_are_judged(self):
        now = timezone.now()
        d = lambda days: now - timedelta(days=days)  # noqa: E731
        actions = [
            (1, d(60), 'card', None), (1, d(50), 'card', None),     # paid again within 30 days
            (2, d(60), 'card', None), (2, d(20), 'card', None),     # again, but 40 days later: no
            (3, d(45), 'handsoff_trade', None),                     # once
            (4, d(5), 'store', None), (4, d(1), 'card', None),      # too new to judge, already repeated
            (5, d(3), 'card', None),                                # too new, once so far
        ]
        out = ia.repeat_payers(actions, now)
        self.assertEqual((out['payers'], out['mature'], out['repeated']), (5, 3, 1))
        self.assertAlmostEqual(out['pct'], 100 / 3)
        self.assertEqual((out['young'], out['young_repeated']), (2, 1))


class AssistantPivotTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.people = [self.member(f'ia{n}', country) for n, country in enumerate(('BO', 'BO', 'MX', 'VE'))]
        self.staff = self.member('ia-staff', 'BO', is_staff=True)

    def member(self, username, country, **extra):
        user = get_user_model().objects.create_user(username=username, email=f'{username}@example.test',
                                                    password='x', firebase_uid=f'fb-{username}', **extra)
        type(user).objects.filter(pk=user.pk).update(onboarded_at=self.now - timedelta(days=3), country=country)
        return type(user).objects.get(pk=user.pk)

    def turn(self, user, tools=(), modality='TEXT', actions=()):
        from assistant.models import AssistantTurn
        from inbox.models import SupportConversation
        from users.models import Account
        account, _ = Account.objects.get_or_create(user=user, account_type='personal', account_index=0)
        conversation, _ = SupportConversation.objects.get_or_create(user=user, account=account, status='OPEN')
        return AssistantTurn.objects.create(user=user, conversation=conversation, modality=modality,
                                            tools=list(tools), actions=list(actions), latency_ms=1200,
                                            cost_usd=Decimal('0.002'))

    def build(self, paid=()):
        with mock.patch.object(ia, 'paid_actions', return_value=list(paid)):
            return ia.assistant_pivot(Window.current())['ia']

    def test_the_funnel_counts_people_and_narrows(self):
        a, b, c, d = self.people
        self.turn(a, ['get_portfolio'])
        self.turn(b, ['navigate'], modality='VOICE_NOTE')
        self.turn(c, ['propose_stock_trade', 'trade:answered'], actions=[{'type': 'relay_trade'}])
        self.turn(d, ['start_store_task:denied'])
        self.turn(self.staff, ['prepare_payment'])              # staff: never counted
        out = self.build(paid=[(c.pk, self.now - timedelta(hours=1), 'handsoff_trade', Decimal('1.02'))])
        self.assertEqual([s['count'] for s in out['funnel']], [4, 2, 1, 1, 0])
        self.assertEqual(out['paid_people_30'], 1)
        self.assertEqual(out['paid_usd_30'], Decimal('1.02'))
        self.assertEqual(out['quality']['voice'], 1)
        self.assertEqual(dict(out['quality']['denied']), {'start_store_task': 1})
        self.assertEqual({r['country']: r['talked'] for r in out['countries']}, {'BO': 2, 'MX': 1, 'VE': 1})
        intents = {r['key']: r['people'] for r in out['intents']}
        self.assertEqual((intents['trade'], intents['shopping'], intents['payment']), (1, 1, 0))
        self.assertEqual(out['cohort']['signups'], 4)
        self.assertEqual(out['cohort']['talked'], 4)

    def test_banned_people_are_left_out(self):
        from security.models import UserBan
        a = self.people[0]
        self.turn(a, ['prepare_payment'])
        UserBan.objects.create(user=a, ban_type='permanent', reason='fraud')
        out = self.build()
        self.assertEqual(out['talked_30'], 0)

    def test_a_failed_build_renders_as_unavailable(self):
        with mock.patch.object(ia, '_build', side_effect=RuntimeError('boom')):
            self.assertEqual(ia.assistant_pivot(Window.current()), {'ia': {'unavailable': True}})


class WiderAssistantTests(AssistantPivotTests):
    def test_depth_buckets_people_by_messages(self):
        rows = [(1, None)] * 1 + [(2, None)] * 3 + [(3, None)] * 12
        self.assertEqual([b['people'] for b in ia.depth(rows)], [1, 1, 0, 1, 0])

    def test_retention_and_drilldowns_build(self):
        a, b, *_ = self.people
        self.turn(a, ['prepare_payment'])
        self.turn(b, ['get_portfolio'])
        out = self.build()
        self.assertEqual(len(out['retention']['cohorts']), ia.COHORT_WEEKS)
        self.assertEqual(out['retention']['cohorts'][-1]['people'], 2)     # this week's first messages
        self.assertEqual([r['user_id'] for r in out['recent']['asks']], [a.pk])
        self.assertIn('whatsapp', out['connections'])
        self.assertIn('gmail', out['connections'])


class CuentaPivotTests(TestCase):
    def test_builds_empty_and_fails_soft(self):
        from config import admin_dashboard_cuenta_pivot as cp
        out = cp.cuenta_pivot(Window.current())['sap']
        self.assertEqual(out['accounts'], [])
        self.assertEqual([s['all'] for s in out['funnel']], [0] * len(out['funnel']))
        self.assertIsNone(out['trade_paused'])
        with mock.patch.object(cp, '_build', side_effect=RuntimeError('boom')):
            self.assertEqual(cp.cuenta_pivot(Window.current()), {'sap': {'unavailable': True}})


class ConnectionSplitTests(AssistantPivotTests):
    def test_team_connections_show_apart_from_real_people(self):
        # Founder, 2026-11-25: "I connected both" while the tab said WhatsApp 0 (team left out, unsaid).
        from whatsapp_link.models import WhatsAppLink
        WhatsAppLink.objects.create(user=self.staff, provider='test', state='linked', linked_at=self.now)
        WhatsAppLink.objects.create(user=self.people[0], provider='test', state='linked', linked_at=self.now)
        WhatsAppLink.objects.create(user=self.people[1], provider='test', state='pairing')
        wa = self.build()['connections']['whatsapp']
        self.assertEqual(wa['linked'], {'real': 1, 'team': 1})
        self.assertEqual(wa['linked_30'], {'real': 1, 'team': 1})
