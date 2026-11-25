"""The Comprar escrow's orderSigner is its own KMS key once configured (audit M2), never the sponsor."""
from unittest import mock

from django.test import SimpleTestCase, override_settings
from eth_account import Account
from eth_utils import keccak

from marketplace import escrow

KEY = Account.create()


class FakeKMSSigner:
    def __init__(self, alias, region_name=None):
        self.alias, self.address = alias, KEY.address

    def assert_matches_address(self, expected):
        if expected and expected.lower() != self.address.lower():
            raise ValueError('address mismatch')

    def sign_digest(self, digest):
        signed = Account._sign_hash(digest, KEY.key)
        return signed.v - 27, signed.r, signed.s


class OrderSignerTests(SimpleTestCase):
    digest = keccak(b'order')

    @override_settings(MARKETPLACE_ORDER_SIGNER_KMS_ALIAS='order-signer', MARKETPLACE_ORDER_SIGNER_ADDRESS=KEY.address)
    def test_its_own_key_signs_once_configured(self):
        with mock.patch('blockchain.evm_kms_signer.EVMKMSSigner', FakeKMSSigner), \
                mock.patch('payments.bsc_flow._sign_pay_authorization') as sponsor:
            sig, signer = escrow.sign_deposit(self.digest)
        sponsor.assert_not_called()
        self.assertEqual(signer, KEY.address.lower())
        self.assertEqual(escrow.recover_signer(self.digest, sig), KEY.address.lower())

    @override_settings(MARKETPLACE_ORDER_SIGNER_KMS_ALIAS='order-signer', MARKETPLACE_ORDER_SIGNER_ADDRESS='0x' + '11' * 20)
    def test_a_key_that_is_not_the_configured_address_never_signs(self):
        with mock.patch('blockchain.evm_kms_signer.EVMKMSSigner', FakeKMSSigner), self.assertRaises(ValueError):
            escrow.sign_deposit(self.digest)

    @override_settings(MARKETPLACE_ORDER_SIGNER_KMS_ALIAS='')
    def test_unconfigured_the_sponsor_signs_as_before(self):
        with mock.patch('payments.bsc_flow._sign_pay_authorization', return_value=('0xab', '0xABC')) as sponsor:
            self.assertEqual(escrow.sign_deposit(self.digest), ('0xab', '0xabc'))
        sponsor.assert_called_once()
