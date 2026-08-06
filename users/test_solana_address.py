from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from solders.pubkey import Pubkey
from solders.keypair import Keypair
import base64

from users.models import Account
from users.schema import PrepareSolanaAddressRegistration, UpdateAccountSolanaAddress


User = get_user_model()


class _Context:
    def __init__(self, user):
        self.user = user


class _Info:
    def __init__(self, user):
        self.context = _Context(user)


class UpdateAccountSolanaAddressTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='solana-user',
            email='solana@example.com',
            password='testpass123',
        )
        self.account = Account.objects.create(
            user=self.user,
            account_type='personal',
            account_index=0,
            is_keyless_migrated=True,
        )
        self.info = _Info(self.user)
        self.jwt_context = {
            'account_type': 'personal',
            'account_index': 0,
            'business_id': None,
        }
        self.keypair = Keypair()
        self.other_keypair = Keypair()
        self.address = str(self.keypair.pubkey())
        self.other_address = str(self.other_keypair.pubkey())

    def mutate(self, address, keypair=None):
        with patch(
            'users.jwt_context.get_jwt_business_context_with_validation',
            return_value=self.jwt_context,
        ):
            prepared = PrepareSolanaAddressRegistration.mutate(
                None, self.info, address
            )
            if not prepared.success:
                return prepared
            signer = keypair or self.keypair
            signature = base64.b64encode(
                bytes(signer.sign_message(prepared.challenge.encode('utf-8')))
            ).decode('ascii')
            return UpdateAccountSolanaAddress.mutate(
                None,
                self.info,
                address,
                prepared.challenge,
                signature,
            )

    def test_registers_valid_address_idempotently(self):
        self.assertTrue(self.mutate(self.address).success)
        self.assertTrue(self.mutate(self.address).success)
        self.account.refresh_from_db()
        self.assertEqual(self.account.solana_address, self.address)

    def test_rejects_invalid_or_changed_address(self):
        self.assertFalse(self.mutate('not-a-solana-address').success)
        self.assertTrue(self.mutate(self.address).success)
        result = self.mutate(self.other_address, self.other_keypair)
        self.assertFalse(result.success)
        self.assertIn('distinta', result.error)

    def test_rejects_address_owned_by_another_account(self):
        other_user = User.objects.create_user(
            username='other-solana-user',
            email='other-solana@example.com',
            password='testpass123',
        )
        Account.objects.create(
            user=other_user,
            account_type='personal',
            account_index=0,
            solana_address=self.address,
        )
        result = self.mutate(self.address)
        self.assertFalse(result.success)
        self.assertIn('otra cuenta', result.error)

    def test_rejects_signature_from_a_different_key(self):
        result = self.mutate(self.address, self.other_keypair)
        self.assertFalse(result.success)
        self.assertIn('ownership proof', result.error)

    def test_database_constraint_is_case_sensitive_and_unique(self):
        self.account.solana_address = self.address
        self.account.save(update_fields=['solana_address'])
        other_user = User.objects.create_user(
            username='constraint-solana-user',
            email='constraint-solana@example.com',
            password='testpass123',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Account.objects.create(
                    user=other_user,
                    account_type='personal',
                    account_index=0,
                    solana_address=self.address,
                )
