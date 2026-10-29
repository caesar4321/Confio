"""User.onboarded_at: the end of signup, whichever build the user came through."""
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase

from users.analytics import get_real_users_queryset
from users.models import Account

User = get_user_model()


class MarkOnboardedTests(TestCase):
    def mark(self, user):
        from users.schema import MarkOnboarded
        return MarkOnboarded.mutate(None, SimpleNamespace(context=SimpleNamespace(user=user)))

    def test_counts_only_once_the_wallet_exists_and_keeps_the_first_time(self):
        # protects=a phone-less signup counts as a real user exactly when it reaches Home with a wallet; fails_when=a walletless login is counted or a repeat moves the date; no_claim=the app's retry timing
        user = User.objects.create_user(username='new-signup', firebase_uid='new-signup')
        self.assertEqual(self.mark(user).error, 'wallet_not_ready')
        self.assertFalse(get_real_users_queryset().filter(pk=user.pk).exists())
        Account.objects.create(user=user, account_type='personal', account_index=0, bsc_address='0x' + '3' * 40)
        self.assertTrue(self.mark(user).success)
        first = User.objects.get(pk=user.pk).onboarded_at
        self.assertTrue(self.mark(user).success)
        self.assertEqual(User.objects.get(pk=user.pk).onboarded_at, first)
        self.assertTrue(get_real_users_queryset().filter(pk=user.pk).exists())

    def test_a_login_that_never_finished_is_not_a_user(self):
        # protects=OTP dropouts and walletless logins stay out of total users; fails_when=every account counts; no_claim=the backfill (migration 0058)
        User.objects.create_user(username='dropout', firebase_uid='dropout')
        self.assertFalse(get_real_users_queryset().filter(username='dropout').exists())


class OnboardedDurabilityTests(TestCase):
    def test_a_stale_full_save_keeps_onboarded_at(self):
        # protects=a profile edit loaded before onboarding cannot un-count the user; fails_when=user.save() writes NULL back; no_claim=explicit update_fields writes
        user = User.objects.create_user(username='stale-save', firebase_uid='stale-save')
        stale = User.objects.get(pk=user.pk)
        Account.objects.create(user=user, account_type='personal', account_index=0, bsc_address='0x' + '4' * 40)
        MarkOnboardedTests.mark(None, user)
        stale.first_name = 'Ana'
        stale.save()
        fresh = User.objects.get(pk=user.pk)
        self.assertEqual(fresh.first_name, 'Ana')
        self.assertIsNotNone(fresh.onboarded_at)

    def test_phones_linked_by_old_workers_are_counted_within_the_hour(self):
        # protects=OTPs finished on pre-deploy workers still end signup; fails_when=a phone holder stays uncounted; no_claim=beat scheduling
        from users.tasks import backfill_phone_onboarded
        user = User.objects.create_user(username='old-worker', firebase_uid='old-worker',
                                        phone_number='3001234567', phone_country='CO')
        self.assertFalse(get_real_users_queryset().filter(pk=user.pk).exists())
        backfill_phone_onboarded.run.__wrapped__()
        self.assertTrue(get_real_users_queryset().filter(pk=user.pk).exists())


class NameVisibilityTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.viewer = User.objects.create_user(username='nv-viewer', firebase_uid='nv-viewer')
        self.stranger = User.objects.create_user(username='nv-stranger', firebase_uid='nv-stranger',
                                                 first_name='Rosa', last_name='Díaz')

    def test_batch_username_lookup_hides_names_of_strangers_and_is_capped(self):
        # protects=checkUsersByUsernames is not a username->full-name oracle; fails_when=a stranger's first/last name returns, or unlimited batches pass; no_claim=cache durability
        from graphql import GraphQLError
        from users.schema import Query
        info = SimpleNamespace(context=SimpleNamespace(user=self.viewer))
        row = Query.resolve_check_users_by_usernames(None, info, ['@nv-stranger'])[0]
        self.assertTrue(row.is_on_confio)
        self.assertIsNone(row.first_name)
        self.assertIsNone(row.last_name)
        with self.assertRaises(GraphQLError):
            Query.resolve_check_users_by_usernames(None, info, ['x'] * 60)

    def test_a_claimed_link_counts_as_having_paid_each_other(self):
        # protects=the sender confirming who opened their link sees that person's name; fails_when=CLAIMED shows only the handle; no_claim=send confirmation states
        from send.models import PhoneInvite
        from users.name_visibility import display_name_for
        self.assertEqual(display_name_for(self.viewer, self.stranger), '@nv-stranger')
        PhoneInvite.objects.create(rail='bsc', invitation_id='ab' * 32, phone_key='57:3001234567',
                                   phone_number='3001234567', inviter_user=self.viewer, amount=1,
                                   token_type='CUSD', status='claimed', claimed_by=self.stranger, kind='link')
        self.assertEqual(display_name_for(self.viewer, self.stranger), 'Rosa D.')

    def test_naming_someone_your_referrer_does_not_reveal_their_name(self):
        # protects=setReferrer on a public @usuario cannot be used to read a stranger's name; fails_when=the referee's view carries the referrer's first/last name; no_claim=referral rewards
        from users.schema import _referrer_for_viewer
        info = SimpleNamespace(context=SimpleNamespace(user=self.viewer))
        masked = _referrer_for_viewer(self.stranger, info)
        self.assertEqual((masked.first_name, masked.last_name, masked.username), ('', '', 'nv-stranger'))
        self.assertEqual(User.objects.get(pk=self.stranger.pk).first_name, 'Rosa')
        own = _referrer_for_viewer(self.stranger, SimpleNamespace(context=SimpleNamespace(user=self.stranger)))
        self.assertEqual(own.first_name, 'Rosa')

    def test_phone_lookup_hides_names_of_strangers(self):
        # protects=a guessed number does not return its holder's name; fails_when=checkUsersByPhones returns first/last for a stranger; no_claim=match ambiguity rules
        from users.schema import Query
        User.objects.filter(pk=self.stranger.pk).update(phone_number='3001234567', phone_country='CO',
                                                        phone_key='57:3001234567')
        info = SimpleNamespace(context=SimpleNamespace(user=self.viewer))
        row = Query.resolve_check_users_by_phones(None, info, ['+573001234567'])[0]
        self.assertTrue(row.is_on_confio)
        self.assertIsNone(row.first_name)

    def test_quota_holds_across_a_burst(self):
        # protects=the counter is the running total, so the call over the limit is refused; fails_when=calls past the limit pass; no_claim=cross-process atomicity (Redis)
        from users.name_visibility import take_lookup_quota
        self.assertTrue(take_lookup_quota(self.viewer, 't', 2000, 2000, 60))
        self.assertFalse(take_lookup_quota(self.viewer, 't', 1, 2000, 60))
