from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from achievements.models import UserReferral
from achievements.referral_conversion import sync_referral_conversions
from users.models import User


def make(name):
    return User.objects.create_user(username=name, email=f'{name}@x.test', password='x', firebase_uid=f'fb-{name}')


def deposit(user, at):
    from usdc_transactions.models import USDCDeposit
    USDCDeposit.objects.create(actor_user=user, actor_type='user', amount=Decimal('10'), source_address='0xabc',
                               status='COMPLETED', completed_at=at)


class ReferralConversionTests(TestCase):
    def setUp(self):
        self.referrer = make('referrer')

    def refer(self, name, **fields):
        user = make(name)
        return UserReferral.objects.create(referred_user=user, referrer_user=self.referrer,
                                           referrer_identifier='REFERRER', **fields)

    def test_funded_referral_converts_dated_by_its_first_deposit(self):
        ref = self.refer('funded')
        first = timezone.now() - timedelta(days=3)
        deposit(ref.referred_user, first + timedelta(days=1))
        deposit(ref.referred_user, first)

        self.assertEqual(sync_referral_conversions(), 1)
        ref.refresh_from_db()
        self.assertEqual(ref.status, 'converted')
        self.assertEqual(ref.first_transaction_at, first)

    def test_unfunded_stays_pending_and_rerun_changes_nothing(self):
        waiting = self.refer('waiting', status='pending')
        funded = self.refer('funded')
        deposit(funded.referred_user, timezone.now())

        self.assertEqual(sync_referral_conversions(), 1)
        self.assertEqual(sync_referral_conversions(), 0)
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, 'pending')

    def test_existing_first_transaction_and_inactive_are_kept(self):
        earlier = timezone.now() - timedelta(days=30)
        active = self.refer('active', status='active', first_transaction_at=earlier)
        closed = self.refer('closed', status='inactive')
        deposit(active.referred_user, timezone.now())
        deposit(closed.referred_user, timezone.now())

        self.assertEqual(sync_referral_conversions(), 1)
        active.refresh_from_db()
        closed.refresh_from_db()
        self.assertEqual((active.status, active.first_transaction_at), ('converted', earlier))
        self.assertEqual(closed.status, 'inactive')

    def test_deleted_referral_is_ignored(self):
        gone = self.refer('gone', deleted_at=timezone.now())
        deposit(gone.referred_user, timezone.now())

        self.assertEqual(sync_referral_conversions(), 0)

    def test_hand_converted_referral_without_a_date_gets_its_first_deposit(self):
        ref = self.refer('handmade', status='converted')
        first = timezone.now() - timedelta(days=2)
        deposit(ref.referred_user, first)

        self.assertEqual(sync_referral_conversions(), 1)
        ref.refresh_from_db()
        self.assertEqual((ref.status, ref.first_transaction_at), ('converted', first))
        self.assertEqual(sync_referral_conversions(), 0)
