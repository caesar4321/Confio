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

    def test_user_names_follow_one_rule_everywhere(self):
        # protects=any UserType (referrer, leaderboard, P2P owner, nested account) hides a stranger's name and shows it after money moved or within a business; fails_when=a username in any list resolves a real name; no_claim=strings stored on transactions
        from users.schema import UserType
        info = SimpleNamespace(context=SimpleNamespace(user=self.viewer))
        self.assertEqual(UserType.resolve_first_name(self.stranger, info), '')
        own = SimpleNamespace(context=SimpleNamespace(user=self.stranger))
        self.assertEqual(UserType.resolve_first_name(self.stranger, own), 'Rosa')
        from send.models import SendTransaction
        SendTransaction.objects.create(
            sender_user=self.viewer, recipient_user=self.stranger, sender_type='user', recipient_type='user',
            amount=1, token_type='CUSD', status='CONFIRMED', sender_address='0x' + '1' * 40,
            recipient_address='0x' + '2' * 40)
        fresh = SimpleNamespace(context=SimpleNamespace(user=self.viewer))
        self.assertEqual(UserType.resolve_last_name(self.stranger, fresh), 'Díaz')

    def test_business_names_need_an_accepted_invitation(self):
        # protects=an owner sees an employee's name only after the employee accepted; fails_when=adding anyone by phone reveals their name; no_claim=permissions
        from users.models import Business
        from users.models_employee import BusinessEmployee, EmployeeInvitation
        from users.schema import UserType
        business = Business.objects.create(name='Tienda', category='retail')
        Account.objects.create(user=self.viewer, account_type='business', account_index=0, business=business)
        BusinessEmployee.objects.create(business=business, user=self.stranger, role='cashier')
        info = SimpleNamespace(context=SimpleNamespace(user=self.viewer))
        self.assertEqual(UserType.resolve_first_name(self.stranger, info), '')
        from datetime import timedelta
        from django.utils import timezone
        EmployeeInvitation.objects.create(business=business, invited_by=self.viewer, role='cashier',
                                          status='accepted', accepted_by=self.stranger,
                                          expires_at=timezone.now() + timedelta(days=7))
        fresh = SimpleNamespace(context=SimpleNamespace(user=self.viewer))
        self.assertEqual(UserType.resolve_first_name(self.stranger, fresh), 'Rosa')

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

    def test_an_unsigned_send_to_a_stranger_shows_only_the_handle(self):
        # protects=prepareBscSend cannot be used to read a stranger's name from the pending row; fails_when=recipientDisplayName returns the stored real name before money moved; no_claim=confirmed history
        from send.models import SendTransaction
        from send.schema import SendTransactionType
        tx = SendTransaction.objects.create(
            sender_user=self.viewer, recipient_user=self.stranger, sender_type='user', recipient_type='user',
            amount=1, token_type='CUSD', status='PENDING', sender_address='0x' + '1' * 40,
            recipient_address='0x' + '2' * 40, recipient_display_name='Rosa Díaz')
        info = SimpleNamespace(context=SimpleNamespace(user=self.viewer))
        self.assertEqual(SendTransactionType.resolve_recipient_display_name(tx, info), '@nv-stranger')
        tx.status = 'CONFIRMED'
        self.assertEqual(SendTransactionType.resolve_recipient_display_name(tx, info), 'Rosa Díaz')

    def test_a_tip_never_reveals_who_is_behind_a_pseudonym(self):
        # protects=Comunidad tips stay pseudonymous: no name, no handle, no Recientes entry; fails_when=a confirmed tip unlocks the real name or a pending tip shows @usuario; no_claim=tip settlement
        from send import link_invite
        from send.models import SendTransaction
        from send.schema import SendTransactionType
        from users.name_visibility import display_name_for
        tip = SendTransaction.objects.create(
            sender_user=self.viewer, recipient_user=self.stranger, sender_type='user', recipient_type='user',
            amount=1, token_type='CUSD', status='PENDING', sender_address='0x' + '1' * 40,
            recipient_address='0x' + '2' * 40, idempotency_key='tip-1', recipient_display_name='LunaInversora')
        info = SimpleNamespace(context=SimpleNamespace(user=self.viewer))
        self.assertEqual(SendTransactionType.resolve_recipient_display_name(tip, info), 'LunaInversora')
        SendTransaction.objects.filter(pk=tip.pk).update(status='CONFIRMED')
        self.assertEqual(display_name_for(self.viewer, self.stranger), '@nv-stranger')
        self.assertEqual(link_invite.recent_people(self.viewer), [])

    def test_donor_wall_and_volunteers_show_handles_to_strangers(self):
        # protects=the public campaign page never names a donor or volunteer to a stranger or anonymous reader; fails_when=donorDisplayName or volunteerName returns the stored full name; no_claim=external-wallet donor labels
        from humanitarian.schema import HumanitarianDonationType, HumanitarianReleaseType
        donation = SimpleNamespace(donor_user=self.stranger, donor_display_name='Rosa Díaz')
        anon = SimpleNamespace(context=SimpleNamespace(user=SimpleNamespace(is_authenticated=False)))
        self.assertEqual(HumanitarianDonationType.resolve_donor_display_name(donation, anon), '@nv-stranger')
        own = SimpleNamespace(context=SimpleNamespace(user=self.stranger))
        self.assertEqual(HumanitarianDonationType.resolve_donor_display_name(donation, own), 'Rosa Díaz')
        orphaned = SimpleNamespace(donor_user=None, donor_display_name='Rosa Díaz')
        self.assertEqual(HumanitarianDonationType.resolve_donor_display_name(orphaned, anon), 'Donante Confío')
        release = SimpleNamespace(volunteer_application=SimpleNamespace(user=self.stranger))
        info = SimpleNamespace(context=SimpleNamespace(user=self.viewer))
        self.assertEqual(HumanitarianReleaseType.resolve_volunteer_name(release, info), '@nv-stranger')


class CounterpartyNumberTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(username='num-sender', firebase_uid='num-sender')
        self.holder = User.objects.create_user(username='num-holder', firebase_uid='num-holder',
                                               phone_number='3132587634', phone_country='VE')

    def send(self, **fields):
        from send.models import SendTransaction
        return SendTransaction.objects.create(
            sender_user=self.sender, recipient_user=self.holder, sender_type='user', recipient_type='user',
            amount=1, token_type='CUSD', status='CONFIRMED', sender_address='0x' + '1' * 40,
            recipient_address='0x' + '2' * 40, **fields)

    def test_an_accounts_verified_number_is_never_shown(self):
        # protects=Confío's number graph never reaches a sender or recipient; fails_when=an old row's stored verified number is returned; no_claim=the app's own contact lookup
        from send.schema import SendTransactionType
        old = self.send(recipient_phone='+58 3132587634', sender_phone='+57 3000000000')
        as_sender = SimpleNamespace(context=SimpleNamespace(user=self.sender))
        as_holder = SimpleNamespace(context=SimpleNamespace(user=self.holder))
        self.assertEqual(SendTransactionType.resolve_recipient_phone(old, as_sender), '')
        self.assertEqual(SendTransactionType.resolve_sender_phone(old, as_holder), '')

    def test_the_senders_own_label_comes_back_to_them_alone(self):
        # protects=the sender sees the number from their own contact; fails_when=the recipient sees it or the sender loses it; no_claim=label correctness (it is whatever they picked)
        from send.schema import SendTransactionType
        mine = self.send(recipient_phone='+573001234567', recipient_phone_from_sender=True)
        self.assertEqual(SendTransactionType.resolve_recipient_phone(
            mine, SimpleNamespace(context=SimpleNamespace(user=self.sender))), '+573001234567')
        self.assertEqual(SendTransactionType.resolve_recipient_phone(
            mine, SimpleNamespace(context=SimpleNamespace(user=self.holder))), '')

    def test_notification_data_never_carries_numbers_except_the_senders_label(self):
        # protects=old notifications with both verified numbers stop showing them; the sender's own label survives on new ones; fails_when=sender_phone or an unflagged recipient_phone is returned; no_claim=already-delivered pushes
        from notifications.schema import NotificationType
        old = SimpleNamespace(data={'amount': '1', 'sender_phone': '+57300', 'recipient_phone': '+58313',
                                    'recipient_phone_country': 'VE'})
        self.assertEqual(NotificationType.resolve_data(old, None), {'amount': '1'})
        new = SimpleNamespace(data={'amount': '1', 'recipient_phone': '+573001234567', 'recipient_phone_from_sender': True})
        self.assertEqual(NotificationType.resolve_data(new, None)['recipient_phone'], '+573001234567')

    def test_phone_key_is_never_anyone_elses(self):
        # protects=a send's sender/recipient (resolved through Web3AuthUserType) never exposes their verified number; fails_when=phoneKey resolves for another viewer; no_claim=UserType fields
        from users.web3auth_schema import Web3AuthUserType
        self.holder.refresh_from_db()
        self.assertIsNone(Web3AuthUserType.resolve_phone_key(self.holder, SimpleNamespace(context=SimpleNamespace(user=self.sender))))
        self.assertEqual(Web3AuthUserType.resolve_phone_key(self.holder, SimpleNamespace(context=SimpleNamespace(user=self.holder))),
                         self.holder.phone_key)

    def test_a_payers_number_never_reaches_the_merchant(self):
        # protects=merchants and their employees never see a payer's verified number; fails_when=payerPhone returns a stored number; no_claim=payment flow
        from payments.schema import PaymentTransactionType
        self.assertEqual(PaymentTransactionType.resolve_payer_phone(SimpleNamespace(payer_phone='+58313'), None), '')
