from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from cusd_plus.stock_month import Trade
from users.models import Account
from users.models_unified import UnifiedTransactionTable
from . import activity_share, community
from .activity_share import STOCK_BUY, STOCK_SELL
from .models import (
    CommunityBlock,
    CommunityFollow,
    CommunityReviewStatus,
    ContentStatus,
)
from .schema import Query
from .test_community import APPROVE, MockInfo, REJECT, CommunityTestBase, make_user

NOW = timezone.now()


def trade(kind, units, usd, symbol='NVDAon', minutes=0):
    return Trade(symbol=symbol, kind=kind, units=Decimal(units), usd=None if usd is None else Decimal(usd),
                 when=NOW + timedelta(minutes=minutes))


class RealizedPnlTests(CommunityTestBase):
    def test_a_sale_is_measured_against_the_average_cost(self):
        trades = [(1, trade(STOCK_BUY, '1', '10')), (2, trade(STOCK_BUY, '1', '20')),
                  (3, trade(STOCK_SELL, '1', '18'))]
        basis, proceeds = activity_share._realized(trades, 3)
        self.assertEqual((basis, proceeds), (Decimal('15'), Decimal('18')))

    def test_a_partial_sale_keeps_the_average_for_the_rest(self):
        trades = [(1, trade(STOCK_BUY, '2', '20')), (2, trade(STOCK_SELL, '1', '12')),
                  (3, trade(STOCK_BUY, '1', '14')), (4, trade(STOCK_SELL, '2', '30'))]
        # After the first sale: 1 unit at 10; then +1 at 14 → 2 units costing 24.
        self.assertEqual(activity_share._realized(trades, 4), (Decimal('24'), Decimal('30')))

    def test_no_pnl_when_the_ledger_cannot_explain_the_position(self):
        from_outside = [(1, trade(STOCK_BUY, '1', '10')), (2, trade(STOCK_SELL, '3', '30'))]
        self.assertIsNone(activity_share._realized(from_outside, 2))
        unreadable = [(1, trade(STOCK_BUY, '1', '10')), (2, trade(STOCK_BUY, '1', '1', symbol='?2')),
                      (3, trade(STOCK_SELL, '1', '12'))]
        self.assertIsNone(activity_share._realized(unreadable, 3))
        unsettled = [(1, trade(STOCK_BUY, '1', None)), (2, trade(STOCK_SELL, '1', '12'))]
        self.assertIsNone(activity_share._realized(unsettled, 2))

    def test_an_earlier_oversell_poisons_every_later_basis(self):
        trades = [(1, trade(STOCK_BUY, '1', '10')), (2, trade(STOCK_SELL, '2', '30')),
                  (3, trade(STOCK_BUY, '2', '40')), (4, trade(STOCK_SELL, '1', '25'))]
        self.assertIsNone(activity_share._realized(trades, 4))

    def test_other_tickers_do_not_mix_into_the_cost(self):
        trades = [(1, trade(STOCK_BUY, '1', '10')), (2, trade(STOCK_BUY, '5', '500', symbol='TSLAon')),
                  (3, trade(STOCK_SELL, '1', '11'))]
        self.assertEqual(activity_share._realized(trades, 3), (Decimal('10'), Decimal('11')))


def buy_activity(**extra):
    return {'kind': STOCK_BUY, 'symbol': 'NVDAon', 'ticker': 'NVDA', 'name': 'NVIDIA', 'units': '0.05',
            'amount_usd': '5.00', 'price_usd': '100.0000', 'date': '2026-10-17', 'wallet': '0xabc',
            'batch_id': 1, 'show_amount': True, **extra}


def as_item(activity, item_id=1):
    return SimpleNamespace(id=item_id, metadata={'activity': activity})


class LivePnlTests(CommunityTestBase):
    def payload(self, activity, trades, prices):
        with patch.object(activity_share, '_wallet_trades', return_value=trades), \
                patch.object(activity_share, '_price_map', return_value=prices):
            return activity_share.activity_payloads([as_item(activity)])[1]

    def test_an_open_purchase_shows_the_live_gain(self):
        public = self.payload(buy_activity(), [(1, trade(STOCK_BUY, '0.05', '5'))], {'NVDAon': Decimal('120')})
        self.assertEqual((public['position'], public['pnl_pct'], public['pnl_usd']), ('open', '20.00', '1.00'))
        self.assertNotIn('wallet', public)
        self.assertNotIn('symbol', public)

    def test_a_sold_out_purchase_freezes_at_the_sale_price(self):
        trades = [(1, trade(STOCK_BUY, '0.05', '5')), (2, trade(STOCK_SELL, '0.05', '4.5', minutes=5))]
        public = self.payload(buy_activity(), trades, {'NVDAon': Decimal('300')})
        self.assertEqual((public['position'], public['pnl_pct'], public['pnl_usd']), ('closed', '-10.00', '-0.50'))

    def test_a_hidden_amount_hides_every_dollar_figure_but_not_the_percent(self):
        public = self.payload(buy_activity(show_amount=False), [(1, trade(STOCK_BUY, '0.05', '5'))],
                              {'NVDAon': Decimal('110')})
        self.assertEqual((public['amount_usd'], public['pnl_usd'], public['pnl_pct']), (None, None, '10.00'))
        sale = {'kind': STOCK_SELL, 'ticker': 'NVDA', 'amount_usd': '6.00', 'pnl_usd': '1.00', 'pnl_pct': '20.00',
                'show_amount': False}
        public = activity_share.activity_payloads([as_item(sale)])[1]
        self.assertEqual((public['amount_usd'], public['pnl_usd'], public['pnl_pct']), (None, None, '20.00'))

    def test_buying_again_after_selling_out_keeps_the_old_post_frozen(self):
        trades = [(1, trade(STOCK_BUY, '0.05', '5')), (2, trade(STOCK_SELL, '0.05', '4.5', minutes=5)),
                  (3, trade(STOCK_BUY, '0.01', '3', minutes=9))]
        public = self.payload(buy_activity(), trades, {'NVDAon': Decimal('300')})
        self.assertEqual((public['position'], public['pnl_pct']), ('closed', '-10.00'))

    def test_unreadable_history_shows_no_pnl(self):
        for trades in ([], [(9, trade(STOCK_BUY, '1', '1'))]):
            public = self.payload(buy_activity(), trades, {'NVDAon': Decimal('300')})
            self.assertEqual((public['position'], public['pnl_pct'], public['pnl_usd']), (None, None, None))
        with patch.object(activity_share, '_wallet_trades', side_effect=RuntimeError('rpc down')), \
                patch.object(activity_share, '_price_map', return_value={'NVDAon': Decimal('300')}):
            public = activity_share.activity_payloads([as_item(buy_activity())])[1]
        self.assertIsNone(public['pnl_pct'])

    def test_an_earlier_oversell_hides_a_later_purchases_state(self):
        trades = [(5, trade(STOCK_BUY, '1', '10')), (6, trade(STOCK_SELL, '2', '30')),
                  (1, trade(STOCK_BUY, '2', '40')), (7, trade(STOCK_SELL, '1', '25'))]
        public = self.payload(buy_activity(), trades, {'NVDAon': Decimal('300')})
        self.assertEqual((public['position'], public['pnl_pct']), (None, None))

    def test_no_live_price_means_no_pnl_never_a_guess(self):
        public = self.payload(buy_activity(), [(1, trade(STOCK_BUY, '0.05', '5'))], {})
        self.assertIsNone(public['pnl_pct'])


class SnapshotRuleTests(CommunityTestBase):
    def send_row(self, sender, recipient, **send):
        values = {'status': 'CONFIRMED', 'token_type': 'CUSD', 'sender_user_id': sender.id,
                  'recipient_user_id': recipient.id, 'sender_business_id': None, 'recipient_business_id': None,
                  'created_at': NOW, **send}
        return SimpleNamespace(amount='12.5', send_transaction=SimpleNamespace(**values))

    def test_sends_between_confio_people_are_shareable_from_either_side(self):
        a, b = make_user(), make_user()
        self.assertEqual(activity_share._send_snapshot(self.send_row(a, b), a).kind, activity_share.SEND)
        self.assertEqual(activity_share._send_snapshot(self.send_row(a, b), b).kind, activity_share.RECEIVE)
        self.assertEqual(activity_share._send_snapshot(self.send_row(a, b), a).data['amount_usd'], '12.50')
        self.assertIsNone(activity_share._send_snapshot(self.send_row(a, b), make_user()))

    def test_confio_tokens_businesses_and_outside_wallets_are_never_shareable(self):
        a, b = make_user(), make_user()
        self.assertIsNone(activity_share._send_snapshot(self.send_row(a, b, token_type='CONFIO'), a))
        self.assertIsNone(activity_share._send_snapshot(self.send_row(a, b, recipient_business_id=7), a))
        self.assertIsNone(activity_share._send_snapshot(self.send_row(a, b, recipient_user_id=None), a))
        self.assertIsNone(activity_share._send_snapshot(self.send_row(a, b, status='SUBMITTED'), a))

    def test_ramp_rail_is_qr_or_transfer(self):
        self.assertEqual(activity_share._ramp_rail('QRI-PE'), 'QR')
        self.assertEqual(activity_share._ramp_rail('WIREPE'), 'transferencia')

    def test_headlines(self):
        self.assertEqual(activity_share.activity_headline(buy_activity()), 'Compró NVDA · US$5.00')
        self.assertEqual(activity_share.activity_headline(
            {'kind': STOCK_SELL, 'ticker': 'NVDA', 'amount_usd': '6.00', 'pnl_pct': '-3.50', 'show_amount': True}),
            'Vendió NVDA · US$6.00 · -3.50%')
        self.assertEqual(activity_share.activity_headline(
            {'kind': 'withdraw', 'amount_usd': '20.00', 'rail': 'QR', 'minutes': 7, 'show_amount': True}),
            'Retiró US$20.00 · por QR · en 7 min')


@override_settings(COMMUNITY_DAILY_POST_LIMIT=1)
class ShareActivityTests(CommunityTestBase):
    def setUp(self):
        super().setUp()
        self.member = make_user()
        self.row = UnifiedTransactionTable.objects.create(
            transaction_type='send', amount='5', token_type='CUSD_PLUS', status='CONFIRMED',
            sender_user=self.member, transaction_date=NOW)
        snap = activity_share.Snapshot(STOCK_BUY, {k: v for k, v in buy_activity().items() if k != 'show_amount'})
        patcher = patch.object(activity_share, 'snapshot_for',
                               side_effect=lambda row, user: snap if user == self.member else None)
        patcher.start()
        self.addCleanup(patcher.stop)
        notify = patch('inbox.community.enqueue_follower_notifications')
        self.follower_notifications = notify.start()
        self.addCleanup(notify.stop)

    def share(self, note='', **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return activity_share.share_activity(self.member, None, self.row.id, note, **kwargs)

    def test_a_template_share_goes_up_at_once_and_tells_followers(self):
        item = self.share()
        item.refresh_from_db()
        self.assertEqual(item.status, ContentStatus.PUBLISHED)
        self.assertEqual(item.community_review.decided_by_model, 'activity-template')
        self.enqueue.assert_not_called()
        self.follower_notifications.assert_called_once_with(item.id)

    def test_a_note_is_reviewed_like_any_post(self):
        item = self.share('Creo en la IA a largo plazo')
        self.assertEqual(item.community_review.status, CommunityReviewStatus.PENDING)
        self.enqueue.assert_called_once()

    def test_links_in_the_note_are_refused(self):
        with self.assertRaises(activity_share.ActivityShareError) as ctx:
            self.share('mira t.me/estafa')
        self.assertEqual(ctx.exception.code, 'links')

    def test_one_activity_is_shared_once_while_its_post_stands(self):
        self.share()
        with self.assertRaises(activity_share.ActivityShareError) as ctx:
            self.share()
        self.assertEqual(ctx.exception.code, 'already_shared')

    def test_a_rejected_note_frees_the_activity_again(self):
        item = self.share('nota')
        self.run_review(item, REJECT)
        self.assertEqual(self.review_of(self.share()).status, CommunityReviewStatus.APPROVED)

    def test_each_side_of_a_send_shares_its_own_view_once(self):
        other = make_user()
        self.share()
        with patch.object(activity_share, 'snapshot_for',
                          return_value=activity_share.Snapshot(activity_share.RECEIVE, {'kind': 'receive'})), \
                patch.object(activity_share, '_member_rows', return_value=UnifiedTransactionTable.objects.all()):
            with self.captureOnCommitCallbacks(execute=True):
                item = activity_share.share_activity(other, None, self.row.id)
        self.assertEqual(item.activity_share.user, other)

    def test_a_takedown_erases_follower_alerts_that_quote_the_post(self):
        from notifications.models import Notification, NotificationType

        item = self.share()
        Notification.objects.create(user=make_user(), notification_type=NotificationType.COMMUNITY_FOLLOWED_POST,
                                    title='t', message='Compró NVDA · US$5.00',
                                    data={'content_item_id': item.id})
        with self.captureOnCommitCallbacks(execute=True):
            community.delete_own_post(self.member, item.id)
        self.assertFalse(Notification.objects.filter(data__content_item_id=item.id).exists())

    def test_staff_cannot_bring_back_a_second_copy_of_a_shared_activity(self):
        first = self.share('nota')
        self.run_review(first, REJECT)
        self.share()  # shared again; live now
        review = self.review_of(first)
        self.assertFalse(community.rereview(review.id))
        # Even a late approval of the first copy does not go up twice.
        review.status = CommunityReviewStatus.PENDING
        review.save()
        self.run_review(first, APPROVE)
        self.assertEqual(self.review_of(first).status, CommunityReviewStatus.REJECTED)

    def test_no_follower_push_once_the_post_is_down(self):
        item = self.share()
        CommunityFollow.objects.create(follower=make_user(), followed=self.member)
        with self.captureOnCommitCallbacks(execute=True):
            community.delete_own_post(self.member, item.id)
        with patch('inbox.community._notify') as notify:
            self.assertEqual(community.notify_followers(item.id), 0)
        notify.assert_not_called()

    def test_a_deleted_template_share_loses_its_snapshot(self):
        item = self.share()
        with self.captureOnCommitCallbacks(execute=True):
            community.delete_own_post(self.member, item.id)
        community.purge_removed_content()
        item.refresh_from_db()
        self.assertNotIn('activity', item.metadata)

    def test_someone_else_cannot_share_my_activity(self):
        with self.assertRaises(activity_share.ActivityShareError) as ctx:
            with self.captureOnCommitCallbacks(execute=True):
                activity_share.share_activity(make_user(), None, self.row.id)
        self.assertEqual(ctx.exception.code, 'not_shareable')

    def test_activity_shares_do_not_use_the_daily_post_limit(self):
        self.share()
        self.post(self.member)
        self.assertEqual(community.posting_block(self.member, None), community.BLOCK_DAILY_LIMIT)
        self.assertIsNone(community.posting_block(self.member, None, activity=True))

    def test_only_verified_members_share(self):
        unverified = make_user(verified=False)
        self.assertEqual(community.posting_block(unverified, None, activity=True), community.BLOCK_NOT_VERIFIED)

    def test_readers_never_get_the_exact_minute(self):
        item = self.share()
        viewer = make_user()
        context = (viewer, Account.objects.get(user=viewer), None, {})
        with patch.object(activity_share, '_wallet_trades', return_value=[]), \
                patch.object(activity_share, '_price_map', return_value={}), \
                patch('inbox.schema.get_context_models', return_value=context):
            [card] = Query().resolve_discover_feed(MockInfo(viewer), limit=20, section='community').items
            [extras] = Query().resolve_community_post_extras(MockInfo(viewer), [str(item.id)])
        self.assertEqual(card.time, 'Hoy')
        local = card.published_at.astimezone(activity_share.DISPLAY_TZ)
        self.assertEqual((local.hour, local.minute, local.second), (0, 0, 0))
        self.assertEqual(card.body, 'Compró NVDA · US$5.00')
        self.assertEqual((extras.activity.kind, extras.activity.amount_usd, extras.note),
                         (STOCK_BUY, '5.00', ''))
        self.assertEqual(extras.author_id, str(self.member.id))

    def test_coarse_labels(self):
        today = timezone.now().astimezone(activity_share.DISPLAY_TZ).date()
        label = activity_share.coarse_time_label
        self.assertEqual(label(today.isoformat()), 'Hoy')
        self.assertEqual(label((today - timedelta(days=1)).isoformat()), 'Ayer')
        self.assertEqual(label((today - timedelta(days=4)).isoformat()), 'Esta semana')
        self.assertEqual(label('2025-03-02'), '2 mar 2025')


class FollowTests(CommunityTestBase):
    def published_member(self):
        member = make_user()
        item = self.post(member)
        with patch('inbox.community.enqueue_follower_notifications'):
            self.run_review(item, APPROVE)
        return member, item

    def test_only_members_with_visible_content_can_be_followed(self):
        with self.assertRaises(community.FollowError):
            community.follow_member(make_user(), make_user().id)
        member, _ = self.published_member()
        fan = make_user()
        with patch('inbox.community._notify') as notify, self.captureOnCommitCallbacks(execute=True):
            community.follow_member(fan, member.id)
        self.assertTrue(CommunityFollow.objects.filter(follower=fan, followed=member, notify=True).exists())
        self.assertEqual(notify.call_args.args[0], member)
        self.assertIn('empezó a seguirte', notify.call_args.args[2])

    def test_you_cannot_follow_yourself(self):
        member, _ = self.published_member()
        with self.assertRaises(community.FollowError):
            community.follow_member(member, member.id)

    def test_followers_with_the_bell_on_hear_about_each_post(self):
        member, item = self.published_member()
        loud, quiet, blocked = make_user(), make_user(), make_user()
        CommunityFollow.objects.create(follower=loud, followed=member)
        CommunityFollow.objects.create(follower=quiet, followed=member, notify=False)
        CommunityFollow.objects.create(follower=blocked, followed=member)
        CommunityBlock.objects.create(blocker=member, blocked=blocked)
        with patch('inbox.community._notify') as notify:
            self.assertEqual(community.notify_followers(item.id), 1)
        self.assertEqual(notify.call_args.args[0], loud)
        self.assertEqual(notify.call_args.args[2], f'@{member.username} publicó')

    def test_followers_hear_about_a_post_once(self):
        member, item = self.published_member()
        CommunityFollow.objects.create(follower=make_user(), followed=member)
        with patch('inbox.community._notify') as notify:
            self.assertEqual(community.notify_followers(item.id), 1)
            self.assertEqual(community.notify_followers(item.id), 0)
        self.assertEqual(notify.call_count, 1)

    def test_a_new_follower_without_posts_opens_for_the_member_they_follow(self):
        member, _ = self.published_member()
        fan = make_user()
        community.follow_member(fan, member.id)
        self.assertIsNotNone(Query().resolve_community_member_profile(MockInfo(member), str(fan.id)))
        self.assertIsNone(Query().resolve_community_member_profile(MockInfo(make_user()), str(fan.id)))

    def test_a_follower_without_posts_can_be_blocked(self):
        member, _ = self.published_member()
        fan = make_user()
        community.follow_member(fan, member.id)
        community.block_member(member, fan.id)
        self.assertTrue(CommunityBlock.objects.filter(blocker=member, blocked=fan).exists())
        self.assertFalse(CommunityFollow.objects.filter(follower=fan).exists())

    def test_a_follower_without_a_username_is_announced_by_pseudonym(self):
        member, _ = self.published_member()
        fan = make_user()
        fan.username = community._generated_username_bases(fan)[0]
        fan.save(update_fields=['username'])
        with patch('inbox.community._notify') as notify, self.captureOnCommitCallbacks(execute=True):
            community.follow_member(fan, member.id)
        self.assertTrue(notify.call_args.args[2].startswith('@inversor_'))

    def test_a_follower_muted_midway_is_skipped(self):
        member, item = self.published_member()
        first, second = make_user(), make_user()
        CommunityFollow.objects.create(follower=first, followed=member)
        CommunityFollow.objects.create(follower=second, followed=member)

        def mute_second(user, *args, **kwargs):
            CommunityFollow.objects.filter(follower=second).update(notify=False)

        with patch('inbox.community._notify', side_effect=mute_second) as notify:
            community.notify_followers(item.id)
        self.assertEqual([c.args[0] for c in notify.call_args_list], [first])

    def test_a_block_ends_follows_both_ways(self):
        member, _ = self.published_member()
        fan, _ = self.published_member()
        CommunityFollow.objects.create(follower=fan, followed=member)
        CommunityFollow.objects.create(follower=member, followed=fan)
        community.block_member(member, fan.id)
        self.assertFalse(CommunityFollow.objects.filter(follower__in=[member, fan]).exists())

    def test_profile_and_bell(self):
        member, _ = self.published_member()
        fan = make_user()
        community.follow_member(fan, member.id)
        community.set_follow_notify(fan, member.id, False)
        profile = Query().resolve_community_member_profile(MockInfo(fan), str(member.id))
        self.assertEqual((profile.username, profile.follower_count, profile.is_following, profile.notify),
                         (member.username, 1, True, False))
        self.assertTrue(community.unfollow_member(fan, member.id))
        self.assertIsNone(Query().resolve_community_member_profile(MockInfo(fan), str(make_user().id)))


class ReferenceLookupTests(CommunityTestBase):
    def test_a_status_screen_reference_pins_its_own_activity(self):
        member = make_user()
        self.assertIsNone(activity_share._reference_filter(''))
        self.assertIsNotNone(activity_share._reference_filter('KOY-123'))
        with patch.object(activity_share, 'snapshot_for', return_value=None):
            self.assertIsNone(activity_share.find_activity(member, group='ramp', reference='KOY-123'))


class ShareIntentTests(CommunityTestBase):
    def setUp(self):
        super().setUp()
        self.member = make_user()
        self.snap = activity_share.Snapshot(STOCK_BUY, {k: v for k, v in buy_activity().items() if k != 'show_amount'})
        notify = patch('inbox.community.enqueue_follower_notifications')
        notify.start()
        self.addCleanup(notify.stop)

    def test_a_tap_before_settlement_is_scheduled_then_published(self):
        from .models import ActivityShareIntent

        with patch.object(activity_share, 'find_activity', return_value=None), \
                patch.dict(activity_share.PREVIEWERS, {'stock': lambda user, ref: self.snap}):
            outcome, intent = activity_share.share_or_schedule(self.member, None, 'stock', '0xabc', 'nota')
        self.assertEqual((outcome, intent.status, intent.note), ('scheduled', 'pending', 'nota'))
        row = UnifiedTransactionTable.objects.create(
            transaction_type='send', amount='5', token_type='CUSD_PLUS', status='CONFIRMED',
            sender_user=self.member, transaction_date=NOW)
        with patch.object(activity_share, 'find_activity', return_value=(row, self.snap)), \
                patch.object(activity_share, 'snapshot_for', return_value=self.snap), \
                self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(activity_share.resolve_share_intents()['published'], 1)
        intent = ActivityShareIntent.objects.get(id=intent.id)
        self.assertEqual(intent.status, 'published')
        self.assertEqual(intent.content_item.body, 'nota')

    def test_unsettled_intents_wait_and_expire(self):
        from .models import ActivityShareIntent

        intent = ActivityShareIntent.objects.create(user=self.member, group='stock', reference='0xabc',
                                                    expires_at=timezone.now() + timedelta(minutes=5))
        with patch.object(activity_share, 'find_activity', return_value=None), \
                patch.dict(activity_share.PREVIEWERS, {'stock': lambda user, ref: self.snap}):
            activity_share.resolve_share_intents()
        intent.refresh_from_db()
        self.assertEqual((intent.status, intent.attempts), ('pending', 1))
        ActivityShareIntent.objects.filter(id=intent.id).update(expires_at=timezone.now() - timedelta(seconds=1))
        activity_share.resolve_share_intents()
        intent.refresh_from_db()
        self.assertEqual(intent.status, 'expired')

    def test_an_activity_that_failed_drops_its_intent(self):
        from .models import ActivityShareIntent

        intent = ActivityShareIntent.objects.create(user=self.member, group='stock', reference='0xabc',
                                                    expires_at=timezone.now() + timedelta(minutes=5))
        with patch.object(activity_share, 'find_activity', return_value=None), \
                patch.dict(activity_share.PREVIEWERS, {'stock': lambda user, ref: None}):
            activity_share.resolve_share_intents()
        intent.refresh_from_db()
        self.assertEqual(intent.status, 'failed')

    def test_someone_elses_reference_is_not_shareable(self):
        with patch.object(activity_share, 'find_activity', return_value=None), \
                patch.dict(activity_share.PREVIEWERS, {'stock': lambda user, ref: None}):
            with self.assertRaises(activity_share.ActivityShareError) as ctx:
                activity_share.share_or_schedule(self.member, None, 'stock', '0xabc')
        self.assertEqual(ctx.exception.code, 'not_shareable')

    def test_the_preview_never_exposes_the_wallet(self):
        public = activity_share.public_activity({**self.snap.data, 'show_amount': True})
        self.assertNotIn('wallet', public)
        self.assertNotIn('batch_id', public)


class IntentConsumptionTests(ShareActivityTests):
    def test_a_direct_share_consumes_the_waiting_intent(self):
        from .models import ActivityShareIntent

        intent = ActivityShareIntent.objects.create(user=self.member, group='stock', reference='0xABC',
                                                    expires_at=timezone.now() + timedelta(minutes=5))
        with patch.object(activity_share, 'references_for_row', return_value={'0xabc'}):
            item = self.share()
        intent.refresh_from_db()
        self.assertEqual((intent.status, intent.content_item_id), ('published', item.id))

    def test_the_resolver_never_republishes_after_a_direct_share(self):
        from .models import ActivityShareIntent

        self.share()
        intent = ActivityShareIntent.objects.create(user=self.member, group='stock', reference='0xabc',
                                                    expires_at=timezone.now() + timedelta(minutes=5))
        with patch.object(activity_share, '_row_for_reference', return_value=self.row):
            activity_share.resolve_share_intents()
        intent.refresh_from_db()
        self.assertEqual((intent.status, intent.last_error), ('published', 'shared directly'))


class ScheduledNoteNotificationTests(CommunityTestBase):
    def test_a_scheduled_note_tells_its_author_the_review_outcome(self):
        from .models import ActivityShareIntent

        member = make_user()
        snap = activity_share.Snapshot(STOCK_BUY, {k: v for k, v in buy_activity().items() if k != 'show_amount'})
        row = UnifiedTransactionTable.objects.create(
            transaction_type='send', amount='5', token_type='CUSD_PLUS', status='CONFIRMED',
            sender_user=member, transaction_date=NOW)
        intent = ActivityShareIntent.objects.create(user=member, group='stock', reference='0xabc', note='nota',
                                                    expires_at=timezone.now() + timedelta(minutes=30))
        with patch.object(activity_share, 'find_activity', return_value=(row, snap)), \
                patch.object(activity_share, 'snapshot_for', return_value=snap), \
                patch.object(activity_share, '_row_for_reference', return_value=None), \
                patch('inbox.community.enqueue_follower_notifications'), \
                self.captureOnCommitCallbacks(execute=True):
            activity_share.resolve_share_intents()
        intent.refresh_from_db()
        with patch('inbox.community.notify_post_reviewed') as notify, \
                patch('inbox.community.enqueue_follower_notifications'), \
                self.captureOnCommitCallbacks(execute=True):
            self.run_review(intent.content_item, APPROVE)
        notify.assert_called_once()


class PaySnapshotTests(CommunityTestBase):
    def payment(self, payer, **extra):
        values = {'payer_user_id': payer.id, 'payer_business_id': None, 'status': 'CONFIRMED', 'token_type': 'CUSD',
                  'merchant_type': 'business', 'merchant_business_id': 9,
                  'merchant_business': SimpleNamespace(name='Café Luna'), 'created_at': NOW, **extra}
        return SimpleNamespace(**values)

    def test_a_business_merchant_is_named(self):
        payer = make_user()
        snap = activity_share._pay_snapshot(self.payment(payer), '4.5', payer)
        self.assertEqual((snap.kind, snap.data['merchant'], snap.data['amount_usd']), ('pay', 'Café Luna', '4.50'))
        self.assertEqual(activity_share.activity_headline({**snap.data, 'show_amount': True}),
                         'Pagó en Café Luna · US$4.50')

    def test_a_personal_merchant_is_never_named(self):
        payer = make_user()
        snap = activity_share._pay_snapshot(
            self.payment(payer, merchant_type='user', merchant_business_id=None, merchant_business=None), '3', payer)
        self.assertIsNone(snap.data['merchant'])
        self.assertEqual(activity_share.activity_headline({**snap.data, 'show_amount': True}), 'Pagó con QR · US$3.00')

    def test_not_shareable_cases(self):
        payer = make_user()
        self.assertIsNone(activity_share._pay_snapshot(self.payment(payer), '1', make_user()))  # not theirs
        self.assertIsNone(activity_share._pay_snapshot(self.payment(payer, payer_business_id=3), '1', payer))
        self.assertIsNone(activity_share._pay_snapshot(self.payment(payer, token_type='CONFIO'), '1', payer))
        self.assertIsNone(activity_share._pay_snapshot(self.payment(payer, status='SUBMITTED'), '1', payer))
        self.assertIsNotNone(activity_share._pay_snapshot(self.payment(payer, status='SUBMITTED'), '1', payer, final=False))
        self.assertIsNone(activity_share._pay_snapshot(self.payment(payer, status='FAILED'), '1', payer, final=False))


class LocalTransferClassificationTests(CommunityTestBase):
    def journey(self, direction, **extra):
        values = {'direction': direction, 'destination_snapshot': {'destination_internal_id': 'd1'},
                  'local_account': SimpleNamespace(payin_rail='BRE-B', country='COL'), 'funding_credit': None,
                  'confio_account': None, **extra}
        return SimpleNamespace(**values)

    def classify(self, journey, destination=None, own=False):
        from unittest.mock import MagicMock

        lookup = MagicMock()
        lookup.filter.return_value.first.return_value = destination
        with patch('payment_accounts.models.PayoutDestination.objects', lookup), \
                patch.object(activity_share, '_payout_is_own', return_value=own):
            return activity_share.classify_journey(journey)

    def test_paying_a_scanned_qr_is_a_payment(self):
        for method in ('co_qr', 'ar_qr', 'br_qr'):
            dest = SimpleNamespace(kind='breb_key', provider_data={'method_id': method}, details={})
            self.assertEqual(self.classify(self.journey('to_bank'), dest), ('pay', 'QR'))

    def test_older_qr_destinations_without_a_method_are_still_payments(self):
        for dest in (SimpleNamespace(kind='qr', provider_data={}, details={}),
                     SimpleNamespace(kind='bank_account', provider_data={}, details={'type': 'BR_CODE'})):
            self.assertEqual(self.classify(self.journey('to_bank'), dest), ('pay', 'QR'))

    def test_groups_only_draw_from_their_own_source(self):
        send_row = SimpleNamespace(send_transaction_id=1, ramp_transaction_id=None, local_money_flow_id=None)
        local_row = SimpleNamespace(send_transaction_id=None, ramp_transaction_id=None, local_money_flow_id=7)
        self.assertFalse(activity_share._in_group(send_row, 'ramp'))
        self.assertTrue(activity_share._in_group(local_row, 'ramp'))
        self.assertTrue(activity_share._in_group(send_row, 'send'))

    def test_a_bank_send_is_retiro_only_to_your_own_account(self):
        dest = SimpleNamespace(kind='breb_key', provider_data={'method_id': 'co_breb'}, details={'type': 'BREB_KEY'})
        self.assertEqual(self.classify(self.journey('to_bank'), dest, own=True), ('withdraw', 'Bre-B'))
        self.assertEqual(self.classify(self.journey('to_bank'), dest, own=False), ('send', 'Bre-B'))

    def test_incoming_from_yourself_is_a_top_up_otherwise_received(self):
        own = SimpleNamespace(payin_admission=SimpleNamespace(reason='same_owner'))
        other = SimpleNamespace(payin_admission=SimpleNamespace(reason='third_party_enabled'))
        self.assertEqual(self.classify(self.journey('to_wallet', funding_credit=own))[0], 'top_up')
        self.assertEqual(self.classify(self.journey('to_wallet', funding_credit=other))[0], 'receive')
        self.assertEqual(self.classify(self.journey('to_wallet'))[0], 'receive')

    def test_incoming_rails_read_as_people_know_them(self):
        for code, name in (('BREB', 'Bre-B'), ('PIX', 'Pix'), ('SPEI', 'SPEI')):
            journey = self.journey('to_wallet', local_account=SimpleNamespace(payin_rail=code, country='COL'))
            self.assertEqual(self.classify(journey)[1], name)

    def test_local_headlines_never_name_the_other_side(self):
        headline = activity_share.activity_headline
        self.assertEqual(headline({'kind': 'send', 'local': True, 'rail': 'Bre-B', 'amount_usd': '20.00',
                                   'show_amount': True}), 'Envió por Bre-B · US$20.00')
        self.assertEqual(headline({'kind': 'receive', 'local': True, 'amount_usd': '15.00', 'show_amount': True}),
                         'Recibió por su cuenta local · US$15.00')
        self.assertEqual(headline({'kind': 'pay', 'merchant': None, 'local': True, 'amount_usd': '3.00',
                                   'show_amount': True}), 'Pagó con QR · US$3.00')

    def test_own_account_needs_a_matching_kyc_document(self):
        dest = SimpleNamespace(holder_id_type='', holder_id_number='')
        self.assertFalse(activity_share._payout_is_own(SimpleNamespace(confio_account=None), dest))
