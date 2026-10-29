"""Link sends (send/link_invite.py) on the BSC invite flow."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from eth_account import Account as EthAccount
from eth_account.messages import encode_defunct

from send import link_invite
from send.models import PhoneInvite, RecipientRevocation, SavedRecipient, SendTransaction
from users.models import Account

User = get_user_model()
ESCROW = '0x' + 'e' * 40


def make_user(name, address=None, **fields):
    user = User.objects.create_user(username=name, firebase_uid=name, **fields)
    if address:
        Account.objects.create(user=user, account_type='personal', account_index=0, bsc_address=address)
    return user


def link_invite_row(inviter, key_address, *, status='pending', amount='5', created_at=None, phone_key='57:3001234567'):
    import uuid
    tx = SendTransaction.objects.create(
        sender_user=inviter, sender_type='user', recipient_type='external', amount=Decimal(amount),
        token_type='CUSD', status='PENDING', sender_address='0x' + '1' * 40, recipient_address=ESCROW,
        is_invitation=True)
    invite = PhoneInvite.objects.create(
        rail='bsc', invitation_id=uuid.uuid4().hex + uuid.uuid4().hex, phone_key=phone_key, phone_number='3001234567',
        inviter_user=inviter, inviter_address='0x' + '1' * 40, send_transaction=tx, amount=Decimal(amount),
        token_type='CUSD', status=status, kind='link', claim_key_address=key_address.lower(),
        public_ref=uuid.uuid4(), expires_at=timezone.now() + timedelta(days=7))
    if created_at:
        PhoneInvite.objects.filter(pk=invite.pk).update(created_at=created_at)
        invite.refresh_from_db()
    return invite


@override_settings(LINK_INVITE_ENABLED=True)
class PrepareLimitTests(TestCase):
    def setUp(self):
        self.sender = make_user('link-sender', '0x' + '1' * 40)
        self.key = EthAccount.create().address

    @mock.patch('send.invite_bsc_flow.prepare_create', return_value={'success': True})
    def test_ten_dollars_a_link(self, prepare):
        # protects=a link (bearer money) is small; fails_when=an $11 link is prepared; no_claim=escrow amounts
        out = link_invite.prepare_link(self.sender, {}, '+573001234567', '11', 'CUSD', self.key)
        self.assertEqual(out['error'], 'link_amount_over_limit')
        prepare.assert_not_called()
        link_invite.prepare_link(self.sender, {}, '+573001234567', '10', 'CUSD', self.key)
        self.assertEqual(prepare.call_args.kwargs['link_claim_address'], self.key)
        self.assertEqual(link_invite.prepare_link(self.sender, {}, '+573001234567', '5', 'CONFIO', self.key)['error'],
                         'link_token_not_supported')

    @mock.patch('send.invite_bsc_flow.prepare_create', return_value={'success': True})
    def test_a_hundred_dollars_a_day_and_stale_drafts_do_not_count(self, prepare):
        # protects=at most $100 of live links a day; fails_when=abandoned drafts lock the sender out, or funded ones are ignored; no_claim=none beyond protects
        for i in range(9):
            link_invite_row(self.sender, EthAccount.create().address, amount='10', phone_key=f'57:30000000{i}')
        link_invite_row(self.sender, EthAccount.create().address, status='draft', amount='10',
                        created_at=timezone.now() - timedelta(hours=1), phone_key='57:300000099')
        self.assertTrue(link_invite.prepare_link(self.sender, {}, '+573001234567', '10', 'CUSD', self.key)['success'])
        link_invite_row(self.sender, EthAccount.create().address, amount='10', phone_key='57:300000098')
        self.assertEqual(link_invite.prepare_link(self.sender, {}, '+573001234567', '1', 'CUSD', self.key)['error'],
                         'link_daily_limit')

    def test_stale_prepares_cannot_be_submitted(self):
        # protects=a draft that stopped counting cannot be funded later; fails_when=submit funds it; no_claim=the batch itself
        from send.invite_bsc_flow import submit_create
        invite = link_invite_row(self.sender, self.key, status='draft', created_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(submit_create(self.sender, invite, '0', '9999999999', '0x00')['error'], 'link_prepare_expired')
        invite.refresh_from_db()
        self.assertEqual(invite.status, 'failed')


@override_settings(BSC_INVITE_ENABLED=True, BSC_INVITE_ESCROW_ADDRESS=ESCROW)
class ClaimTests(TestCase):
    def setUp(self):
        self.sender = make_user('claim-sender', '0x' + '1' * 40)
        self.receiver = make_user('claim-receiver', '0x' + '2' * 40)
        self.key = EthAccount.create()
        self.invite = link_invite_row(self.sender, self.key.address)

    def sign(self, key, recipient='0x' + '2' * 40):
        message = link_invite.claim_message(self.invite, recipient)
        return EthAccount.sign_message(encode_defunct(text=message), key.key).signature.hex()

    @mock.patch('send.invite_bsc_flow.claim_for_recipient', return_value={'success': True, 'transaction_hash': '0xabc'})
    def test_the_link_key_signature_claims_to_the_callers_account(self, claim):
        # protects=whoever holds the link key receives, into their own account; fails_when=a valid signature is refused or the proof mode is phone; no_claim=on-chain release
        out = link_invite.claim_link(self.receiver, str(self.invite.public_ref), self.sign(self.key))
        self.assertTrue(out['success'])
        self.assertTrue(claim.call_args.kwargs['via_link'])

    @mock.patch('send.invite_bsc_flow.claim_for_recipient')
    def test_any_other_key_or_the_sender_is_refused(self, claim):
        # protects=only the link key opens the link and the sender cannot claim their own; fails_when=another key or the inviter gets the money; no_claim=none beyond protects
        other = EthAccount.create()
        self.assertEqual(link_invite.claim_link(self.receiver, str(self.invite.public_ref), self.sign(other))['error'],
                         'bad_signature')
        self.assertEqual(link_invite.claim_link(self.sender, str(self.invite.public_ref), self.sign(self.key))['error'],
                         'link_is_yours')
        claim.assert_not_called()

    def test_proof_modes_never_cross(self):
        # protects=a link invite is never released by owning the number, nor a phone invite by a link; fails_when=the auto-claim takes link money; no_claim=sponsor RPC
        from send.invite_bsc_flow import claim_for_recipient
        self.assertEqual(claim_for_recipient(self.invite, self.receiver, via_link=False)['error'], 'invite_wrong_proof')
        PhoneInvite.objects.filter(pk=self.invite.pk).update(kind='phone')
        self.invite.refresh_from_db()
        self.assertEqual(claim_for_recipient(self.invite, self.receiver, via_link=True)['error'], 'invite_wrong_proof')

    def test_release_goes_only_to_the_address_the_key_signed_for(self):
        # protects=a wallet change between signature check and release cannot redirect link money; fails_when=the sponsor releases to an address the key never signed; no_claim=sponsor RPC
        from send.invite_bsc_flow import claim_for_recipient
        out = claim_for_recipient(self.invite, self.receiver, via_link=True,
                                  expected_recipient_address='0x' + '9' * 40)
        self.assertEqual(out['error'], 'recipient_address_changed')

    def test_a_blocked_receiver_cannot_claim(self):
        # protects=a seller blocked from direct receiving cannot collect through links either; fails_when=the claim proceeds; no_claim=none beyond protects
        from send.invite_bsc_flow import claim_for_recipient
        from users.direct_receive import BLOCKED_ERROR
        User.objects.filter(pk=self.receiver.pk).update(direct_receive_blocked_at=timezone.now())
        self.receiver.refresh_from_db()
        self.assertEqual(claim_for_recipient(self.invite, self.receiver, via_link=True)['error'], BLOCKED_ERROR)


class ResolveAndSaveTests(TestCase):
    def setUp(self):
        self.sender = make_user('resolver')
        self.friend = make_user('friend', phone_number='3001234567', phone_country='CO')
        User.objects.filter(pk=self.friend.pk).update(last_activity_at=timezone.now())

    def test_saved_then_legacy_then_none(self):
        # protects=the documented order and the 180-day recycle rule; fails_when=an inactive or revoked number still sends direct; no_claim=send execution
        self.assertEqual(link_invite.resolve(self.sender, '+573001234567')['kind'], 'LEGACY')
        User.objects.filter(pk=self.friend.pk).update(last_activity_at=timezone.now() - timedelta(days=200))
        self.assertEqual(link_invite.resolve(self.sender, '+573001234567')['kind'], 'NONE')
        SavedRecipient.objects.create(sender_user=self.sender, phone_key='57:3001234567', recipient_user=self.friend,
                                      source='link_claim', basis_at=timezone.now())
        self.assertEqual(link_invite.resolve(self.sender, '+573001234567')['kind'], 'SAVED')

    def test_forget_sends_the_next_one_by_link_even_for_a_legacy_holder(self):
        # protects=forgetting really goes back to links; fails_when=the legacy holder still resolves; no_claim=none beyond protects
        link_invite.forget(self.sender, '+573001234567')
        self.assertTrue(RecipientRevocation.objects.filter(sender_user=self.sender).exists())
        self.assertEqual(link_invite.resolve(self.sender, '+573001234567')['kind'], 'NONE')

    def test_the_newest_claim_wins_whatever_order_saves_arrive_in(self):
        # protects=an older claim cannot overwrite a newer saved recipient; fails_when=save order decides; no_claim=none beyond protects
        newer_owner = make_user('newer-owner')
        old = link_invite_row(self.sender, EthAccount.create().address, status='claimed')
        new = link_invite_row(self.sender, EthAccount.create().address, status='claimed')
        PhoneInvite.objects.filter(pk=old.pk).update(claimed_by=self.friend, claimed_at=timezone.now() - timedelta(days=2))
        PhoneInvite.objects.filter(pk=new.pk).update(claimed_by=newer_owner, claimed_at=timezone.now() - timedelta(days=1))
        self.assertTrue(link_invite.save_from_link(self.sender, str(new.public_ref))['success'])
        self.assertEqual(link_invite.save_from_link(self.sender, str(old.public_ref))['error'], 'stale')
        self.assertEqual(SavedRecipient.objects.get(sender_user=self.sender, deleted_at__isnull=True).recipient_user,
                         newer_owner)


@override_settings(BSC_INVITE_ESCROW_ADDRESS=ESCROW)
class SummaryTests(TestCase):
    def test_the_message_to_sign_names_the_viewers_own_account(self):
        # protects=the link page signs for the viewer's own account and never for the sender's; fails_when=the sender gets a claim message or the recipient line is someone else; no_claim=signature verification (ClaimTests)
        sender = make_user('summary-sender', '0x' + '1' * 40)
        viewer = make_user('summary-viewer', '0x' + 'A' * 40)
        invite = link_invite_row(sender, EthAccount.create().address)
        mine = link_invite.link_summary(str(invite.public_ref), viewer=sender)
        theirs = link_invite.link_summary(str(invite.public_ref), viewer=viewer)
        self.assertTrue(mine['is_mine'])
        self.assertEqual(mine['claim_message'], '')
        self.assertTrue(theirs['claim_message'].endswith('recipient:0x' + 'a' * 40))
        self.assertIn(f'invite:0x{invite.invitation_id}', theirs['claim_message'])


class ClaimedLinkTests(TestCase):
    def test_a_claimed_link_asks_the_sender_to_confirm_until_forgotten(self):
        # protects=the sender confirms who opened their link before later money goes direct, and "forget" sticks; fails_when=a claim goes straight to SAVED, or a forgotten claim keeps resolving; no_claim=the confirm UI
        sender = make_user('claimed-sender')
        opener = make_user('claimed-opener')
        invite = link_invite_row(sender, EthAccount.create().address, status='claimed')
        PhoneInvite.objects.filter(pk=invite.pk).update(claimed_by=opener, claimed_at=timezone.now() - timedelta(hours=1))
        out = link_invite.resolve(sender, '+573001234567')
        self.assertEqual((out['kind'], out['user'], out['public_ref']), ('CLAIMED', opener, str(invite.public_ref)))
        link_invite.forget(sender, '+573001234567')
        self.assertEqual(link_invite.resolve(sender, '+573001234567')['kind'], 'NONE')
        # A late save for the forgotten claim cannot undo the forget.
        self.assertEqual(link_invite.save_from_link(sender, str(invite.public_ref))['error'], 'forgotten')
        self.assertEqual(link_invite.resolve(sender, '+573001234567')['kind'], 'NONE')


@override_settings(LINK_INVITE_ENABLED=True)
class AuditFollowUpTests(TestCase):
    def setUp(self):
        self.sender = make_user('audit-sender', '0x' + '1' * 40)

    @mock.patch('send.invite_bsc_flow.prepare_create', return_value={'success': True})
    def test_a_retry_after_a_lost_answer_reshares_the_open_link(self, prepare):
        # protects=a lost submit answer never leads to a second escrow for the same contact; fails_when=prepare escrows again while one is creating/pending; no_claim=the client re-share
        open_link = link_invite_row(self.sender, EthAccount.create().address, status='creating')
        out = link_invite.prepare_link(self.sender, {}, '+573001234567', '5', 'CUSD', EthAccount.create().address)
        self.assertEqual((out['error'], out['public_ref']), ('link_already_pending', str(open_link.public_ref)))
        prepare.assert_not_called()

    def test_a_link_funded_late_still_counts_for_a_full_day(self):
        # protects=the 24h limit runs from funding, not prepare; fails_when=a link prepared 24h50m ago (submitted at +29m, mined at +59m) drops out early; no_claim=none beyond protects
        link_invite_row(self.sender, EthAccount.create().address, amount='10',
                        created_at=timezone.now() - timedelta(hours=24, minutes=50))
        self.assertEqual(link_invite.links_today_usd(self.sender), Decimal('10'))

    def test_legacy_save_refuses_an_account_other_than_the_one_paid(self):
        # protects=saving after a legacy send keeps the paid account, never a new holder of the number; fails_when=the number moved and the new holder is saved; no_claim=none beyond protects
        holder = make_user('legacy-holder', phone_number='3001234567', phone_country='CO')
        User.objects.filter(pk=holder.pk).update(last_activity_at=timezone.now())
        self.assertEqual(link_invite.save_legacy(self.sender, '+573001234567', recipient_user_id=999999)['error'],
                         'recipient_changed')
        self.assertTrue(link_invite.save_legacy(self.sender, '+573001234567', recipient_user_id=holder.pk)['success'])
        # A second (late) legacy save never replaces the one already saved.
        self.assertEqual(link_invite.save_legacy(self.sender, '+573001234567', recipient_user_id=holder.pk)['error'],
                         'already_saved')


class SendPeopleTests(TestCase):
    def test_recent_people_are_those_money_moved_with_newest_first(self):
        # protects=Recientes lists exactly the people the sender may see by name, newest first; fails_when=a pending send or a stranger appears, or order is wrong; no_claim=the app's rendering
        me = make_user('people-me')
        old_friend, new_friend, pending = (make_user(n) for n in ('old-friend', 'new-friend', 'pending-one'))
        for other, status in ((old_friend, 'CONFIRMED'), (new_friend, 'CONFIRMED'), (pending, 'PENDING')):
            SendTransaction.objects.create(
                sender_user=me, recipient_user=other, sender_type='user', recipient_type='user', amount=1,
                token_type='CUSD', status=status, sender_address='0x' + '1' * 40, recipient_address='0x' + '2' * 40)
        SendTransaction.objects.filter(recipient_user=old_friend).update(created_at=timezone.now() - timedelta(days=3))
        self.assertEqual([u.username for u in link_invite.recent_people(me)], ['new-friend', 'old-friend'])


class ClaimSettlementTests(TestCase):
    def setUp(self):
        self.sender = make_user('settle-sender', '0x' + '1' * 40)
        self.claimer = make_user('settle-claimer', '0x' + '3' * 40)
        self.invite = link_invite_row(self.sender, EthAccount.create().address, status='claiming')
        PhoneInvite.objects.filter(pk=self.invite.pk).update(claimed_by=self.claimer, claimed_txid='0x' + 'c' * 64)
        self.invite.refresh_from_db()

    def test_the_escrow_payout_is_never_an_external_deposit(self):
        # protects=the claimer's money is not booked as "Billetera externa"; fails_when=the scanner finds no owner for the claim hash; no_claim=scanner cursor logic
        from cusd_plus.tasks import _source_row_covers
        self.assertTrue(_source_row_covers('0x' + 'C' * 64, '0x' + '3' * 40))
        self.assertFalse(_source_row_covers('0x' + 'c' * 64, '0x' + '9' * 40))

    def test_a_settled_claim_becomes_a_send_to_the_claimer(self):
        # protects=both sides see who sent and who received; fails_when=the send still names nobody after the claim settles; no_claim=finality rules (separately tested)
        from send import invite_tasks
        receipt = {'status': '0x1', 'blockNumber': '0x10', 'blockHash': '0xabc', 'logs': []}
        def rpc(method, params):
            return {'eth_getTransactionReceipt': receipt, 'eth_getBlockByNumber': {'hash': '0xabc'}}.get(method)
        with mock.patch('cusd_plus.sponsor_7702._rpc', side_effect=rpc), \
             mock.patch('cusd_plus.tasks._finalized_block_number', return_value=100), \
             mock.patch('cusd_plus.tasks._mark_receipt_balances_stale'), \
             mock.patch('notifications.utils.create_notification') as notify, \
             self.captureOnCommitCallbacks(execute=True):
            invite_tasks.confirm_bsc_invite_claim.run(self.invite.pk, '0x' + 'c' * 64)
        stx = SendTransaction.objects.get(pk=self.invite.send_transaction_id)
        self.assertEqual((stx.recipient_user_id, stx.recipient_type, stx.invitation_claimed), (self.claimer.pk, 'user', True))
        self.assertEqual(notify.call_args.kwargs['user'], self.claimer)

    def test_the_claimer_is_told_the_token_they_received(self):
        # protects=a claim across the cUSD/cUSD+ line names what landed; fails_when=the notification repeats the sender's token; no_claim=conversion amounts
        from send import invite_tasks
        vault = '0x' + 'e' * 40
        log = {'address': vault, 'topics': [invite_tasks._TRANSFER_TOPIC, '0x' + '0' * 64, '0x' + '0' * 24 + '3' * 40]}
        with self.settings(CUSD_PLUS_VAULT_ADDRESS=vault):
            self.assertEqual(invite_tasks._received_token({'logs': [log]}, self.claimer), 'CUSD_PLUS')
            self.assertEqual(invite_tasks._received_token({'logs': []}, self.claimer), '')


class SendDetailQueryTests(TestCase):
    def test_the_apps_send_detail_query_is_valid_and_hides_the_other_number(self):
        # protects=TransactionDetail loads a send (its WhatsApp share needs it); fails_when=senderUser resolves through a User type without the fields the app asks for, or the counterparty's phoneKey leaks; no_claim=other screens' queries
        import re
        from pathlib import Path
        from django.conf import settings
        from django.test import RequestFactory
        from graphql import parse, validate
        from config.schema import schema
        source = (Path(settings.BASE_DIR) / 'apps/src/apollo/queries.ts').read_text()
        query = re.search(r'GET_SEND_TRANSACTION_BY_ID = gql`(.*?)`', source, re.S).group(1)
        self.assertEqual(validate(schema.graphql_schema, parse(query)), [])
        sender = make_user('detail-sender', '0x' + '1' * 40, phone_country='US', phone_number='2025550101')
        recipient = make_user('detail-recipient', '0x' + '2' * 40, phone_country='US', phone_number='2025550102')
        recipient.refresh_from_db()
        self.assertTrue(recipient.phone_key)
        stx = SendTransaction.objects.create(
            sender_user=sender, recipient_user=recipient, sender_type='user', recipient_type='user', amount=1,
            token_type='CUSD', status='CONFIRMED', sender_address='0x' + '1' * 40, recipient_address='0x' + '2' * 40)
        request = RequestFactory().post('/graphql')
        request.user = sender
        result = schema.execute(query, variables={'id': str(stx.pk)}, context_value=request)
        self.assertIsNone(result.errors)
        data = result.data['sendTransaction']
        sender.refresh_from_db()
        self.assertEqual(data['senderUser']['phoneKey'], sender.phone_key or None)
        self.assertIsNone(data['recipientUser']['phoneKey'])
