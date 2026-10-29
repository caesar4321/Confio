"""Direct personal receiving: nudge, block, enforcement (users/direct_receive.py)."""
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from send.models import SendTransaction
from users import direct_receive

User = get_user_model()


def paid(recipient, sender):
    return SendTransaction.objects.create(
        sender_user=sender, recipient_user=recipient, sender_type='user', recipient_type='user',
        amount=Decimal('5'), token_type='CUSD', status='CONFIRMED',
        sender_address='0x' + '1' * 40, recipient_address='0x' + '2' * 40,
    )


@override_settings(DIRECT_RECEIVE_NUDGE_PAYERS=2, DIRECT_RECEIVE_BLOCK_PAYERS=3)
class DirectReceiveFlagTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(username='seller', firebase_uid='seller')
        self.buyers = [User.objects.create_user(username=f'buyer{i}', firebase_uid=f'buyer{i}') for i in range(3)]

    def test_nudge_then_block_by_distinct_payers(self):
        # protects=a seller paid by many people loses direct receiving; fails_when=repeat payments from one friend count as many; no_claim=the threshold values
        paid(self.seller, self.buyers[0])
        paid(self.seller, self.buyers[0])
        direct_receive.refresh_flags()
        self.seller.refresh_from_db()
        self.assertEqual(direct_receive.status(self.seller), 'ok')
        paid(self.seller, self.buyers[1])
        direct_receive.refresh_flags()
        self.seller.refresh_from_db()
        self.assertEqual(direct_receive.status(self.seller), 'nudge')
        paid(self.seller, self.buyers[2])
        direct_receive.refresh_flags()
        self.seller.refresh_from_db()
        self.assertEqual(direct_receive.status(self.seller), 'blocked')
        self.assertEqual(self.seller.direct_receive_block_reason, 'auto')

    def test_exempt_accounts_are_never_auto_blocked(self):
        # protects=an admin exemption (family remittances) holds; fails_when=the daily scan blocks it; no_claim=none beyond protects
        User.objects.filter(pk=self.seller.pk).update(direct_receive_exempt=True)
        for buyer in self.buyers:
            paid(self.seller, buyer)
        direct_receive.refresh_flags()
        self.seller.refresh_from_db()
        self.assertFalse(direct_receive.is_blocked(self.seller))


class DirectReceiveEnforcementTests(TestCase):
    def test_a_blocked_account_cannot_be_sent_to_directly(self):
        # protects=buyers cannot pay a blocked seller by id/phone/address; fails_when=prepare_bsc_send lets it through; no_claim=the BSC batch itself
        from unittest import mock
        from send.bsc_flow import prepare_bsc_send
        sender = User.objects.create_user(username='payer', firebase_uid='payer')
        seller = User.objects.create_user(username='blocked-seller', firebase_uid='blocked-seller')
        User.objects.filter(pk=seller.pk).update(direct_receive_blocked_at=timezone.now(), direct_receive_block_reason='admin')
        seller.refresh_from_db()
        from users.models import Account
        Account.objects.create(user=sender, account_type='personal', account_index=0, bsc_address='0x' + '4' * 40)
        with override_settings(BSC_SEND_ENABLED=True), \
             mock.patch('send.bsc_flow._vault_address', return_value='0x' + '5' * 40), \
             mock.patch('send.bsc_flow._cusd_address', return_value='0x' + '6' * 40), \
             mock.patch('send.bsc_flow._resolve_recipient', return_value=(seller, None, '0x' + '3' * 40, None)):
            try:
                result = prepare_bsc_send(sender, {'account_type': 'personal', 'account_index': 0}, '5',
                                          recipient_user_id=seller.pk)
            except Exception as exc:  # an earlier gate (no account, flags) must not mask the check under test
                self.fail(f'prepare_bsc_send raised before the block check: {exc}')
        self.assertFalse(result['success'])
        self.assertIn(result['error'], (direct_receive.BLOCKED_ERROR,))


class SendRecipientLookupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.viewer = User.objects.create_user(username='viewer', firebase_uid='viewer')
        self.friend = User.objects.create_user(username='AnaP', firebase_uid='ana', first_name='Ana', last_name='Pérez')

    def lookup(self, username):
        from users.schema import Query
        info = SimpleNamespace(context=SimpleNamespace(user=self.viewer))
        return Query.resolve_send_recipient_by_username(None, info, username)

    def test_finds_a_friend_by_username_case_insensitively(self):
        # protects=@usuario resolves to the right account; fails_when=case or @ break it; no_claim=KYC name rendering
        found = self.lookup('@anap')
        self.assertEqual(str(found.user_id), str(self.friend.pk))
        self.assertFalse(found.receives_by_qr_only)
        self.assertIsNone(self.lookup('nobody-here'))

    def test_the_name_shows_only_after_money_moved_between_them(self):
        # protects=a public @usuario (investor profile) never reveals a stranger's real name; fails_when=a lookup with no payment history returns "Ana P."; no_claim=other lookups (see name_visibility tests)
        self.assertEqual(self.lookup('anap').display_name, '@AnaP')
        paid(self.viewer, self.friend)
        self.assertEqual(self.lookup('anap').display_name, 'Ana P.')

    def test_lookups_are_rate_limited(self):
        # protects=usernames cannot be enumerated; fails_when=unlimited lookups; no_claim=cache durability
        from graphql import GraphQLError
        for _ in range(30):
            self.lookup('anap')
        with self.assertRaises(GraphQLError):
            self.lookup('anap')


class SubmitRecheckTests(TestCase):
    def test_a_send_prepared_before_the_block_is_refused_at_submit(self):
        # protects=preparing early cannot outlast a block; fails_when=submit broadcasts to a now-blocked seller; no_claim=the batch broadcast itself
        from send.bsc_flow import submit_bsc_send
        buyer = User.objects.create_user(username='early-buyer', firebase_uid='early-buyer')
        seller = User.objects.create_user(username='late-blocked', firebase_uid='late-blocked')
        tx = SendTransaction.objects.create(
            sender_user=buyer, recipient_user=seller, sender_type='user', recipient_type='user',
            amount=Decimal('5'), token_type='CUSD', status='PENDING', bsc_calls_json='{"calls": []}',
            sender_address='0x' + '1' * 40, recipient_address='0x' + '2' * 40,
        )
        User.objects.filter(pk=seller.pk).update(direct_receive_blocked_at=timezone.now())
        result = submit_bsc_send(buyer, tx, '0', '9999999999', '0x00')
        self.assertEqual(result, {'success': False, 'error': direct_receive.BLOCKED_ERROR})
