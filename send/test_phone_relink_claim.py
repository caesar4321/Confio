from contextlib import ExitStack
from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from send import invite_bsc_flow as flow
from send.models import PhoneInvite
from sms_verification.models import SMSVerification
from users.models import Account, User
from users.test_phone_relinking import confirmed_test_link as link_verified_phone


@override_settings(REVIEW_TEST_ENABLED=False, BSC_INVITE_ENABLED=True,
                   BSC_INVITE_ESCROW_ADDRESS='0x' + 'ee' * 20)
class RelinkedInviteClaimTests(TestCase):
    def setUp(self):
        self.old = User.objects.create_user(username='previous-phone-owner',
            firebase_uid='previous-phone-owner', phone_country='CO',
            phone_number='3132587634')
        self.new = User.objects.create_user(username='new-phone-owner',
            firebase_uid='new-phone-owner')
        for user, address in ((self.old, '22'), (self.new, '33')):
            Account.objects.create(user=user, account_type='personal',
                account_index=0, bsc_address='0x' + address * 20)
        self.invite = PhoneInvite.objects.create(rail='bsc',
            invitation_id='ab' * 32, phone_key='57:3132587634',
            phone_number='3132587634', inviter_address='0x' + '11' * 20,
            amount=1, token_type='CONFIO', status='pending')

    def transfer(self):
        proof = SMSVerification.objects.create(user=self.new,
            phone_number='+573132587634', code_hash='unused',
            expires_at=timezone.now() + timedelta(minutes=5))
        link_verified_phone(self.new, proof, 'CO')

    def claim(self, recipient, during_quote=None):
        signer = Mock(address='0x' + '44' * 20)
        signer.sign_typed_transaction.return_value = ('0xsigned', '0xhash')
        with ExitStack() as stack:
            stack.enter_context(patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True))
            stack.enter_context(patch.object(flow, '_claim_min_amount_out',
                side_effect=during_quote, return_value=0))
            stack.enter_context(patch('blockchain.evm_kms_signer.get_bsc_sponsor_signer_from_settings', return_value=signer))
            stack.enter_context(patch('cusd_plus.sponsor_7702._rpc', return_value='0x1'))
            nonce = stack.enter_context(patch('cusd_plus.sponsor_7702.acquire_sponsor_nonce_lock', return_value='token'))
            stack.enter_context(patch('cusd_plus.sponsor_7702.release_sponsor_nonce_lock'))
            stack.enter_context(patch.object(flow, 'confirm_bsc_invite_claim_later'))
            result = flow.claim_for_recipient(self.invite, recipient)
        self.invite.refresh_from_db()
        return result, signer, nonce

    def assert_rejected(self, result, signer, nonce):
        self.assertEqual(result.get('error'), 'recipient_phone_changed')
        signer.sign_typed_transaction.assert_not_called()
        nonce.assert_not_called()
        self.assertEqual(self.invite.status, 'pending')
        self.assertIsNone(self.invite.claimed_by_id)

    def test_stale_previous_owner_cannot_claim_after_transfer(self):
        self.transfer()
        self.assertEqual(self.old.phone_key, self.invite.phone_key)
        self.assert_rejected(*self.claim(self.old))

    def test_transfer_during_claim_preparation_is_rechecked_at_reservation(self):
        def transfer_during_quote(*args):
            self.transfer()
            return 0
        self.assert_rejected(*self.claim(self.old, during_quote=transfer_during_quote))

    def test_new_verified_owner_can_claim(self):
        self.transfer()
        result, signer, _ = self.claim(self.new)
        self.assertTrue(result['success'], result)
        signer.sign_typed_transaction.assert_called_once()
        self.assertEqual(self.invite.status, 'claiming')
        self.assertEqual(self.invite.claimed_by_id, self.new.pk)
