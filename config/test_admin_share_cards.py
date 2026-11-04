"""Admin: the share-card funnel (taps -> clicks -> signups -> verified/funded/invested)."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from achievements.models import UserReferral
from config import admin_dashboard_growth as growth
from inbox.models import ExternalShareTap
from users.models import User
from users.models_analytics import FunnelEvent


def make(name):
    return User.objects.create_user(username=name, email=f'{name}@x.test', password='x', firebase_uid=f'fb-{name}')


class ShareCardFunnelTests(TestCase):
    def test_counts_each_stage_by_channel(self):
        sharer, newcomer, other = make('sharer'), make('newcomer'), make('other')
        ExternalShareTap.objects.create(user=sharer, surface='activity', product='stock', target='whatsapp')
        ExternalShareTap.objects.create(user=sharer, surface='holding', product='stock', target='whatsapp')
        ExternalShareTap.objects.create(user=sharer, surface='futures', product='perps', target='save')
        FunnelEvent.objects.create(event_name='referral_link_clicked', source_type='referral_link',
                                   properties={'utm_medium': 'share_card', 'utm_source': 'whatsapp'})
        FunnelEvent.objects.create(event_name='referral_link_clicked', source_type='referral_link',
                                   properties={'utm_medium': 'other', 'utm_source': 'whatsapp'})
        UserReferral.objects.create(referred_user=newcomer, referrer_user=sharer, referrer_identifier='SHARER',
                                    attribution_data={'utm_medium': 'share_card', 'utm_source': 'whatsapp'})
        UserReferral.objects.create(referred_user=other, referrer_user=sharer, referrer_identifier='SHARER',
                                    attribution_data={'utm_medium': 'referral'})
        with patch.object(growth, '_cohort_milestones', return_value=({newcomer.id}, {newcomer.id}, set())):
            data = growth.share_cards(None)['share_cards']
        rows = {r['label']: r for r in data['rows']}
        self.assertEqual(
            {k: rows['Whatsapp'][k] for k in ('sharers', 'taps', 'clicks', 'signups', 'verified', 'funded', 'invested')},
            {'sharers': 1, 'taps': 2, 'clicks': 1, 'signups': 1, 'verified': 1, 'funded': 1, 'invested': 0})
        self.assertEqual(rows['Image']['taps'], 1)
        self.assertEqual((rows['All']['taps'], rows['All']['signups']), (3, 1))
        self.assertEqual({p['label']: p['n'] for p in data['by_product']}, {'Acciones': 2, 'Futuros': 1})

    def test_older_taps_are_outside_the_window(self):
        u = make('old')
        tap = ExternalShareTap.objects.create(user=u, surface='activity', product='stock', target='instagram')
        ExternalShareTap.objects.filter(pk=tap.pk).update(created_at=timezone.now() - timedelta(days=40))
        with patch.object(growth, '_cohort_milestones', return_value=(set(), set(), set())):
            rows = growth.share_cards(None)['share_cards']['rows']
        self.assertEqual([r['label'] for r in rows], ['All'])


class ShareCardTemplateTests(TestCase):
    def test_section_renders(self):
        from django.template.loader import render_to_string
        with patch.object(growth, '_cohort_milestones', return_value=(set(), set(), set())):
            html = render_to_string('admin/dash/_share_cards.html', growth.share_cards(None))
        self.assertIn('Share cards', html)
        self.assertIn('utm_medium=share_card', html)


class CohortMilestoneTests(TestCase):
    def test_empty_cohort_queries_nothing(self):
        with patch('ramps.metrics.deposit_events') as events:
            self.assertEqual(growth._cohort_milestones(set()), (set(), set(), set()))
        events.assert_not_called()

    def test_filtered_deposit_events_match_the_unfiltered_ones(self):
        from ramps.metrics import deposit_events
        from usdc_transactions.models import USDCDeposit

        kept, dropped = make('kept'), make('dropped')
        for user in (kept, kept, dropped):
            USDCDeposit.objects.create(actor_user=user, actor_type='user', amount=Decimal('10'), source_address='0xabc',
                                       status='COMPLETED', completed_at=timezone.now())
        everyone = deposit_events()
        filtered = deposit_events(user_ids=[kept.id])
        self.assertEqual(sorted(filtered), sorted(e for e in everyone if e[0] == kept.id))
        self.assertEqual(len(filtered), 2)
        self.assertNotIn(dropped.id, {u for u, _ in filtered})
        self.assertEqual(deposit_events(user_ids=[]), [])



class ShareCardPlacementTests(TestCase):
    def test_the_funnel_sits_on_activation_next_to_the_referral_funnel(self):
        from config.admin_dashboard import ConfioAdminSite
        pages = {key: templates for key, _label, _builders, templates, *_ in ConfioAdminSite.DASH_PAGES}
        activation = pages['activation']
        self.assertIn('admin/dash/_share_cards.html', activation)
        self.assertEqual(activation.index('admin/dash/_share_cards.html'),
                         activation.index('admin/dash/_referral_funnel.html') + 1)
        self.assertNotIn('admin/dash/_share_cards.html', pages['community'])
