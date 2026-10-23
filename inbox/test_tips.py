from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from . import community, direct_messages as dm, tips
from .models import CommunityBlock, CommunityFollow, DirectConversation, DirectMessage, Tip
from .test_community import APPROVE, REJECT, make_user


class PrepareTipTests(TestCase):
    def setUp(self):
        self.alice, self.bob = make_user(), make_user()

    def prepare(self, amount='5', note='', to=None, key='', verdict=APPROVE):
        with patch('inbox.tips._wallet', return_value='0xabc'), \
                patch('inbox.dm_gate.community._call_reviewer', return_value=verdict):
            return tips.prepare_tip(self.alice, None, (to or self.bob).id, amount, note, key)

    def test_a_tip_is_prepared_without_moving_money(self):
        tip = self.prepare('5', 'Gracias por el consejo de NVDA')
        self.assertEqual((tip.amount, tip.status, tip.note), (Decimal('5.00'), 'prepared', 'Gracias por el consejo de NVDA'))
        self.assertTrue(tip.send_key.startswith(tips.KEY_PREFIX))
        self.assertIsNone(tip.send_transaction)

    def test_a_rejected_note_moves_no_money(self):
        with self.assertRaises(community.CommunityPostError):
            self.prepare('5', 'Escríbeme por el app verde', verdict=REJECT)
        with self.assertRaises(community.CommunityPostError):
            self.prepare('5', 'mi wsp 04145551234')
        self.assertFalse(Tip.objects.exists())

    def test_amount_limits(self):
        for amount in ('0.49', '200.01', 'abc', '-1'):
            with self.assertRaises(community.CommunityPostError, msg=amount):
                self.prepare(amount)
        self.assertEqual(self.prepare('0.50').amount, Decimal('0.50'))

    def test_daily_limit(self):
        self.prepare('200', key='a')
        self.prepare('200', key='b')
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.prepare('101', key='c')
        self.assertEqual(ctx.exception.code, 'tip_daily_limit')

    def test_same_key_same_tip(self):
        self.assertEqual(self.prepare(key='k').id, self.prepare(key='k').id)

    def test_a_key_reused_for_a_different_tip_is_refused(self):
        self.prepare('200', key='k')
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.prepare('5', key='k')
        self.assertEqual(ctx.exception.code, 'tip_key_conflict')

    def test_a_recent_confirmed_tip_asks_before_another(self):
        tip = self.prepare(key='a')
        Tip.objects.filter(id=tip.id).update(status='confirmed')
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.prepare(key='b')
        self.assertEqual(ctx.exception.code, 'tip_recent')
        with patch('inbox.tips._wallet', return_value='0xabc'), \
                patch('inbox.dm_gate.community._call_reviewer', return_value=APPROVE):
            again = tips.prepare_tip(self.alice, None, self.bob.id, '5', '', 'b', allow_repeat=True)
        self.assertEqual(again.status, 'prepared')

    def test_a_tip_still_confirming_blocks_another_to_the_same_person(self):
        tip = self.prepare(key='a')
        Tip.objects.filter(id=tip.id).update(status='sent')
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.prepare(key='b')
        self.assertEqual(ctx.exception.code, 'tip_in_flight')
        self.prepare(key='c', to=make_user())          # someone else: fine

    def test_who_can_be_tipped(self):
        with self.assertRaises(community.CommunityPostError):
            self.prepare(to=self.alice)                               # self
        with self.assertRaises(community.CommunityPostError) as ctx:
            self.prepare(to=make_user(verified=False))
        self.assertEqual(ctx.exception.code, 'tip_recipient_unverified')
        CommunityBlock.objects.create(blocker=self.bob, blocked=self.alice)
        with self.assertRaises(community.CommunityPostError):
            self.prepare()

    def test_hidden_profiles_and_dms_off_dont_matter(self):
        from .schema import SetCommunityPortfolioHidden
        from .test_community import MockInfo

        SetCommunityPortfolioHidden.mutate(None, MockInfo(self.alice), hidden=True)
        dm.set_dms_enabled(self.bob, False)
        self.assertEqual(self.prepare().status, 'prepared')


class SendHookTests(TestCase):
    def setUp(self):
        self.alice, self.bob = make_user(), make_user()
        with patch('inbox.tips._wallet', return_value='0xabc'):
            self.tip = tips.prepare_tip(self.alice, None, self.bob.id, '5', '', 'k1')

    def check(self, **over):
        args = dict(user=self.alice, idempotency_key=self.tip.send_key, recipient_user=self.bob,
                    recipient_business=None, amount_usd=Decimal('5'), token_request='', sender_business=None)
        args.update(over)
        with patch('inbox.tips._wallet', return_value='0xabc'):
            return tips.tip_for_send(**args)

    def test_only_the_exact_tip_passes(self):
        self.assertEqual(self.check(), (self.tip, None))
        self.assertEqual(self.check(amount_usd=Decimal('6'))[1], 'tip_mismatch')
        self.assertEqual(self.check(recipient_user=make_user())[1], 'tip_mismatch')
        self.assertEqual(self.check(token_request='CONFIO')[1], 'tip_mismatch')
        self.assertEqual(self.check(user=self.bob)[1], 'tip_not_found')
        self.assertEqual(self.check(idempotency_key='tip-nope')[1], 'tip_not_found')

    def deliver(self, status='CONFIRMED'):
        from send.models import SendTransaction

        send = SendTransaction.objects.create(
            sender_user=self.alice, recipient_user=self.bob, sender_type='user', recipient_type='user',
            sender_address='0x1', recipient_address='0x2', amount=Decimal('5'), token_type='CUSD_PLUS',
            status='SUBMITTED', idempotency_key=self.tip.send_key)
        tips.link_send(self.tip, send)
        send.status = status
        tips.on_send_resolved(send)
        self.tip.refresh_from_db()
        return send

    def test_a_confirmed_tip_shows_as_a_gift_without_touching_the_request(self):
        self.deliver()
        self.assertEqual(self.tip.status, 'confirmed')
        message = self.tip.message
        self.assertEqual((message.kind, message.tip_amount, message.review_status), ('tip', Decimal('5'), 'approved'))
        self.assertEqual(message.conversation.status, 'request')
        self.assertEqual(tips.received_total(self.bob), Decimal('5'))

    def test_a_tip_doesnt_use_up_the_request_cap(self):
        self.deliver()
        with patch('inbox.direct_messages.enqueue_review'):
            for _ in range(dm.REQUEST_CAP):
                dm.send_message(self.alice, None, 'hola', recipient_id=self.bob.id)

    def test_dms_off_gets_no_conversation(self):
        dm.set_dms_enabled(self.bob, False)
        self.deliver()
        self.assertEqual(self.tip.status, 'confirmed')
        self.assertIsNone(self.tip.message)
        self.assertFalse(DirectConversation.objects.exists())

    def test_a_failed_send_fails_the_tip(self):
        self.deliver('FAILED')
        self.assertEqual(self.tip.status, 'failed')
        self.assertEqual(tips.received_total(self.bob), Decimal('0'))

    def test_a_key_binds_once(self):
        send = self.deliver()
        self.assertEqual(tips.link_send(self.tip, send), 'tip_not_found')

    def test_binding_rechecks_the_daily_limit_and_expiry(self):
        from datetime import timedelta

        from django.utils import timezone

        from send.models import SendTransaction

        earlier = SendTransaction.objects.create(
            sender_user=self.alice, recipient_user=self.bob, sender_type='user', recipient_type='user',
            sender_address='0x1', recipient_address='0x2', amount=Decimal('498'), token_type='CUSD_PLUS',
            status='CONFIRMED', idempotency_key='tip-x')
        Tip.objects.create(sender=self.alice, recipient=self.bob, amount=Decimal('498'), client_key='x',
                           send_key='tip-x', status='confirmed', send_transaction=earlier)
        self.assertEqual(tips.link_send(self.tip, None), 'tip_daily_limit')
        Tip.objects.filter(send_key='tip-x').delete()
        Tip.objects.filter(id=self.tip.id).update(created_at=timezone.now() - tips.PREPARED_TTL - timedelta(minutes=1))
        self.assertEqual(self.check()[1], 'tip_expired')

    def test_the_sweeper_finishes_a_settled_tip(self):
        from send.models import SendTransaction

        send = SendTransaction.objects.create(
            sender_user=self.alice, recipient_user=self.bob, sender_type='user', recipient_type='user',
            sender_address='0x1', recipient_address='0x2', amount=Decimal('5'), token_type='CUSD_PLUS',
            status='SUBMITTED', idempotency_key=self.tip.send_key)
        tips.link_send(self.tip, send)
        SendTransaction.objects.filter(id=send.id).update(status='CONFIRMED')
        self.assertEqual(tips.unresolved_sent_ids(), [self.tip.id])
        tips.resolve(self.tip.id)
        self.tip.refresh_from_db()
        self.assertEqual(self.tip.status, 'confirmed')


class ProfileTipTests(TestCase):
    def test_can_tip_and_own_total(self):
        from .schema import Query
        from .test_community import MockInfo

        alice, bob = make_user(), make_user()
        with patch('inbox.community.has_visible_content', return_value=True), \
                patch('inbox.tips._wallet', return_value='0xabc'):
            other = Query().resolve_investor_profile(MockInfo(alice), str(bob.id))
            own = Query().resolve_investor_profile(MockInfo(bob), str(bob.id))
        self.assertTrue(other.can_tip)
        self.assertIsNone(other.tips_received_usd)
        self.assertFalse(own.can_tip)
        self.assertEqual(own.tips_received_usd, '0.00')


class SubmitWindowTests(TestCase):
    def test_a_bound_tip_send_must_be_signed_within_the_hour(self):
        from datetime import timedelta

        from django.utils import timezone

        from send.models import SendTransaction

        alice, bob = make_user(), make_user()
        with patch('inbox.tips._wallet', return_value='0xabc'):
            tip = tips.prepare_tip(alice, None, bob.id, '5', '', 'k')
        send = SendTransaction.objects.create(
            sender_user=alice, recipient_user=bob, sender_type='user', recipient_type='user',
            sender_address='0x1', recipient_address='0x2', amount=Decimal('5'), token_type='CUSD_PLUS',
            status='PENDING', idempotency_key=tip.send_key)
        self.assertIsNone(tips.link_send(tip, send))
        with patch('inbox.tips._wallet', return_value='0xabc'):
            self.assertIsNone(tips.tip_submit_error(send))
        SendTransaction.objects.filter(id=send.id).update(created_at=timezone.now() - tips.SUBMIT_TTL - timedelta(minutes=1))
        send.refresh_from_db()
        self.assertEqual(tips.tip_submit_error(send), 'tip_expired')

    def test_two_prepared_tips_to_the_same_person_cant_both_bind(self):
        from send.models import SendTransaction

        alice, bob = make_user(), make_user()
        with patch('inbox.tips._wallet', return_value='0xabc'):
            first = tips.prepare_tip(alice, None, bob.id, '5', '', 'a')
            second = tips.prepare_tip(alice, None, bob.id, '5', '', 'b')

        def send_for(tip):
            return SendTransaction.objects.create(
                sender_user=alice, recipient_user=bob, sender_type='user', recipient_type='user',
                sender_address='0x1', recipient_address='0x2', amount=Decimal('5'), token_type='CUSD_PLUS',
                status='PENDING', idempotency_key=tip.send_key)

        self.assertIsNone(tips.link_send(first, send_for(first)))
        self.assertEqual(tips.link_send(second, send_for(second)), 'tip_in_flight')


class LateChecksTests(TestCase):
    def setUp(self):
        from send.models import SendTransaction

        self.alice, self.bob = make_user(), make_user()
        with patch('inbox.tips._wallet', return_value='0xabc'):
            self.tip = tips.prepare_tip(self.alice, None, self.bob.id, '5', 'gracias', 'k')
        self.send = SendTransaction.objects.create(
            sender_user=self.alice, recipient_user=self.bob, sender_type='user', recipient_type='user',
            sender_address='0x1', recipient_address='0x2', amount=Decimal('5'), token_type='CUSD_PLUS',
            status='PENDING', idempotency_key=self.tip.send_key)
        with patch('inbox.tips._wallet', return_value='0xabc'):
            self.assertIsNone(tips.link_send(self.tip, self.send))

    def test_a_block_after_preparing_stops_the_submit(self):
        CommunityBlock.objects.create(blocker=self.bob, blocked=self.alice)
        with patch('inbox.tips._wallet', return_value='0xabc'):
            self.assertEqual(tips.tip_submit_error(self.send), 'tip_not_available')

    def test_a_suspended_sender_gets_no_note_bubble(self):
        self.send.status = 'CONFIRMED'
        with patch('inbox.direct_messages.is_suspended', return_value=True):
            tips.on_send_resolved(self.send)
        self.tip.refresh_from_db()
        self.assertEqual((self.tip.status, self.tip.message), ('confirmed', None))

    def test_an_expired_unsigned_tip_frees_the_limit(self):
        from datetime import timedelta

        from django.utils import timezone

        from send.models import SendTransaction

        SendTransaction.objects.filter(id=self.send.id).update(created_at=timezone.now() - tips.SUBMIT_TTL - timedelta(minutes=1))
        self.assertEqual(tips._sent_today(self.alice, committed_only=True), Decimal('5'))   # still in grace
        SendTransaction.objects.filter(id=self.send.id).update(
            created_at=timezone.now() - tips.SUBMIT_TTL - tips.EXPIRY_GRACE - timedelta(minutes=1))
        self.assertEqual(tips._sent_today(self.alice, committed_only=True), Decimal('0'))
        tips.unresolved_sent_ids()
        self.tip.refresh_from_db()
        self.assertEqual(self.tip.status, 'failed')


    def test_a_send_with_a_batch_on_record_never_expires(self):
        from datetime import timedelta

        from django.utils import timezone

        from blockchain.models import SponsoredBatch
        from send.models import SendTransaction

        SendTransaction.objects.filter(id=self.send.id).update(
            created_at=timezone.now() - tips.SUBMIT_TTL - tips.EXPIRY_GRACE - timedelta(minutes=1))
        values = {'user': self.alice, 'user_bsc_address': '0x1', 'kind': 'send_cusd_plus',
                  'source_id': self.send.id, 'num_calls': 1, 'calls_json': '[]', 'gas_limit': 1,
                  'max_fee_wei': '1'}
        SponsoredBatch.objects.create(**values)
        tips.unresolved_sent_ids()
        self.tip.refresh_from_db()
        self.assertEqual(self.tip.status, 'sent')


class TipPrivacyTests(TestCase):
    def test_the_other_party_account_is_never_exposed_through_a_tip(self):
        from send.models import SendTransaction
        from send.schema import SendTransactionType

        from .test_community import MockInfo

        alice, bob = make_user(), make_user()
        send = SendTransaction.objects.create(
            sender_user=alice, recipient_user=bob, sender_type='user', recipient_type='user',
            sender_address='0x1', recipient_address='0x2', amount=Decimal('5'), token_type='CUSD_PLUS',
            status='CONFIRMED', idempotency_key='tip-zz')
        self.assertIsNone(SendTransactionType.resolve_recipient_user(send, MockInfo(alice)))
        self.assertEqual(SendTransactionType.resolve_sender_user(send, MockInfo(alice)), alice)
        self.assertIsNone(SendTransactionType.resolve_sender_user(send, MockInfo(bob)))
        send.idempotency_key = 'send_123'
        self.assertEqual(SendTransactionType.resolve_recipient_user(send, MockInfo(alice)), bob)   # ordinary sends unchanged


class ParallelRepeatTests(TestCase):
    def test_a_parallel_second_tip_still_needs_the_repeat_confirmation(self):
        from send.models import SendTransaction

        alice, bob = make_user(), make_user()
        with patch('inbox.tips._wallet', return_value='0xabc'):
            first = tips.prepare_tip(alice, None, bob.id, '5', '', 'a')
            second = tips.prepare_tip(alice, None, bob.id, '5', '', 'b')

        def send_for(tip):
            return SendTransaction.objects.create(
                sender_user=alice, recipient_user=bob, sender_type='user', recipient_type='user',
                sender_address='0x1', recipient_address='0x2', amount=Decimal('5'), token_type='CUSD_PLUS',
                status='PENDING', idempotency_key=tip.send_key)

        self.assertIsNone(tips.link_send(first, send_for(first)))
        Tip.objects.filter(id=first.id).update(status='confirmed')
        self.assertEqual(tips.link_send(second, send_for(second)), 'tip_recent')


    def test_submit_rechecks_a_replacement_that_already_went_out(self):
        from send.models import SendTransaction

        alice, bob = make_user(), make_user()
        with patch('inbox.tips._wallet', return_value='0xabc'):
            first = tips.prepare_tip(alice, None, bob.id, '5', '', 'a')
        first_send = SendTransaction.objects.create(
            sender_user=alice, recipient_user=bob, sender_type='user', recipient_type='user',
            sender_address='0x1', recipient_address='0x2', amount=Decimal('5'), token_type='CUSD_PLUS',
            status='PENDING', idempotency_key=first.send_key)
        self.assertIsNone(tips.link_send(first, first_send))
        other = Tip.objects.create(sender=alice, recipient=bob, amount=Decimal('5'), client_key='z',
                                   send_key='tip-other', status='confirmed')
        with patch('inbox.tips._wallet', return_value='0xabc'):
            self.assertEqual(tips.tip_submit_error(first_send), 'tip_recent')
        other.delete()
        with patch('inbox.tips._wallet', return_value='0xabc'):
            self.assertIsNone(tips.tip_submit_error(first_send))
