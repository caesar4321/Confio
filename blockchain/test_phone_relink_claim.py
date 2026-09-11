from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from blockchain.invite_send_mutations import ClaimInviteForPhone
from send.models import PhoneInvite
from sms_verification.models import SMSVerification
from users.models import Account, User
from users.test_phone_relinking import confirmed_test_link as link_verified_phone


@override_settings(REVIEW_TEST_ENABLED=False)
class LegacyPhoneClaimAuthorizationTests(TestCase):
    def setUp(self):
        self.old = User.objects.create_user(username='legacy-old', firebase_uid='legacy-old',
            phone_number='3132587634', phone_country='CO')
        self.new = User.objects.create_user(username='legacy-new', firebase_uid='legacy-new')
        self.old_address = 'A' * 58
        self.new_address = 'B' * 58
        for user, address in ((self.old, self.old_address), (self.new, self.new_address)):
            Account.objects.create(user=user, account_type='personal', account_index=0,
                algorand_address=address)
        self.invite = PhoneInvite.objects.create(rail='algorand', invitation_id='legacy-invite',
            phone_key=self.old.phone_key, phone_number=self.old.phone_number,
            amount=1, token_type='CONFIO', status='pending')

    def transfer(self):
        proof = SMSVerification.objects.create(user=self.new, phone_number='+573132587634',
            code_hash='unused', expires_at=timezone.now() + timedelta(minutes=5))
        link_verified_phone(self.new, proof, 'CO')

    def call(self, user, address, **kwargs):
        return ClaimInviteForPhone.mutate(None, SimpleNamespace(context=SimpleNamespace(user=user)),
            recipient_address=address, invitation_id=self.invite.invitation_id, **kwargs)

    def assert_denied(self, user, address):
        with patch.object(ClaimInviteForPhone, '_mutate_verified') as execute:
            result = self.call(user, address)
        self.assertFalse(result.success)
        execute.assert_not_called()
        self.invite.refresh_from_db()

    def test_stale_previous_owner_cannot_claim(self):
        self.transfer()
        self.assertEqual(self.old.phone_key, self.invite.phone_key)
        self.assert_denied(self.old, self.old_address)

    def test_recipient_must_be_callers_personal_account(self):
        self.assert_denied(self.old, self.new_address)

    def test_explicit_foreign_invitation_is_rejected(self):
        self.invite.phone_key = '57:3001112222'
        self.invite.save(update_fields=['phone_key'])
        self.assert_denied(self.old, self.old_address)

    def test_claimed_invite_is_not_reattributed_after_transfer(self):
        self.invite.status = 'claimed'
        self.invite.claimed_by = self.old
        self.invite.save(update_fields=['status', 'claimed_by'])
        self.transfer()
        self.assert_denied(self.new, self.new_address)
        self.assertEqual(self.invite.claimed_by_id, self.old.pk)

    def test_new_verified_owner_proceeds_with_fresh_user(self):
        self.transfer()
        with patch.object(ClaimInviteForPhone, '_mutate_verified',
                return_value=ClaimInviteForPhone(success=True)) as execute:
            result = self.call(self.new, self.new_address)
        self.assertTrue(result.success)
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[1].context.user.phone_key, self.invite.phone_key)

    def test_international_phone_does_not_require_country_argument(self):
        with patch.object(ClaimInviteForPhone, '_mutate_verified',
                return_value=ClaimInviteForPhone(success=True)) as execute:
            result = self.call(self.old, self.old_address, phone='+573132587634')
        self.assertTrue(result.success, result.error)
        execute.assert_called_once()

    def test_existing_chain_receipt_does_not_set_claimed_by(self):
        client = Mock()
        client.application_info.return_value = {'params': {'global-state': []}}
        builder = SimpleNamespace(app_id=1,
            contract=SimpleNamespace(methods=[SimpleNamespace(name='claim_invitation')]))
        with patch('blockchain.invite_send_mutations.get_algod_client', return_value=client), \
             patch('blockchain.invite_send_mutations.InviteSendTransactionBuilder', return_value=builder), \
             patch('blockchain.invite_send_mutations.AtomicTransactionComposer') as composer:
            result = self.call(self.old, self.old_address)
        self.assertFalse(result.success)
        self.assertEqual(result.error, 'La invitación ya fue reclamada.')
        composer.assert_not_called()
        self.invite.refresh_from_db()
        self.assertIsNone(self.invite.claimed_by_id)
        self.assertEqual(self.invite.status, 'pending')
