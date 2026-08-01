"""
BSC invoice payments (payments/bsc_flow.py via ConfioPayContract) — the
properties that make the [approve, pay] batch safe:

  1. the 0.9% fee is CEILING division in wei, exact parity with the
     Algorand payment builder AND ConfioPayContract.feeFor;
  2. the submit-side validator accepts only [token.approve(payContract,
     gross), payContract.pay(invoiceId, token, gross, merchant, deadline,
     authSig)] with every field pinned to the stored row AND the embedded
     server authorization recovering to the expected paymentSigner — the
     contract re-enforces token allowlist, fee math, the global invoice
     guard, and the same signature on-chain;
  3. a merchant business without a registered bsc_address BLOCKS the
     payment and nudges the invoice creator (owner-only registration).

Runs without a database (ORM + RPC mocked, house style):
    myvenv/bin/python manage.py test payments.test_bsc_flow
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings
from eth_abi import decode as abi_decode, encode as abi_encode
from eth_keys import keys
from eth_utils import to_checksum_address

from cusd_plus.sponsor_7702 import PolicyError, SEL_APPROVE, SEL_PAY, USDT_BSC
from payments import bsc_flow

VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'
CONFIO_TOKEN = '0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8'
PAY_CONTRACT = '0x' + 'ca' * 20
PAYER = '0x' + '11' * 20
MERCHANT = '0x' + '22' * 20
WAD = 10 ** 18

# A real secp256k1 key so the validator's genuine ECDSA recovery runs.
TEST_PK = keys.PrivateKey(bytes.fromhex('42' * 32))
TEST_SIGNER = TEST_PK.public_key.to_checksum_address()
DEADLINE = 9_999_999_999  # far future, so the auth never looks expired


def _sign(digest: bytes) -> str:
    s = TEST_PK.sign_msg_hash(digest)
    return '0x' + (s.r.to_bytes(32, 'big') + s.s.to_bytes(32, 'big')
                   + bytes([27 + s.v])).hex()


class FeeMathTests(SimpleTestCase):
    """Wei ceiling parity with (amount*90 + 9999) // 10000 — the same rule
    ConfioPayContract.feeFor enforces on-chain (test_fee_ceiling_vectors
    in ConfioPayContract.t.sol pins the identical vectors)."""

    def test_ceiling_vectors(self):
        for gross, want in [
            (10_000, 90),          # exact multiple: 0.9% flat
            (10_001, 91),          # one unit over → fee rounds UP
            (1, 1),                # dust still pays a full unit
            (1_111, 10),           # ceil(9.999) = 10
            (10 * WAD, (10 * WAD * 90 + 9999) // 10000),
        ]:
            self.assertEqual(bsc_flow.payment_fee_wei(gross), want, gross)

    def test_zero_and_dust(self):
        self.assertEqual(bsc_flow.payment_fee_wei(0), 0)
        self.assertGreaterEqual(bsc_flow.payment_fee_wei(1), 1)


@override_settings(
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    BSC_CONFIO_TOKEN_ADDRESS=CONFIO_TOKEN,
    BSC_PAY_CONTRACT_ADDRESS=PAY_CONTRACT,
    BSC_PAY_ENABLED=True,
)
class PrepareBatchTests(SimpleTestCase):
    def _invoice(self, amount='10', token='CUSD_PLUS', chain='BSC'):
        merchant_business = SimpleNamespace(id=77, name='Bodega La 22')
        return SimpleNamespace(
            internal_id='inv123', status='PENDING', is_expired=False,
            token_type=token, settlement_chain=chain, amount=Decimal(amount),
            merchant_business=merchant_business, merchant_business_id=77,
            merchant_display_name='Bodega La 22',
            merchant_account=SimpleNamespace(id=5),
            created_by_user=SimpleNamespace(id=9),
            description='',
        )

    def _user(self, uid=1):
        account = SimpleNamespace(bsc_address=PAYER, business=None)
        accounts = mock.Mock()
        accounts.filter.return_value.first.return_value = account
        return SimpleNamespace(
            id=uid, accounts=accounts, phone_number='58412',
            get_full_name=lambda: 'Payer', username='payer')

    def _prepare(self, invoice, shares_value=100 * WAD, usdt=0,
                 merchant_addr=MERCHANT):
        merchant_account = SimpleNamespace(bsc_address=merchant_addr)
        captured = {}

        def _goc(**kw):
            row = SimpleNamespace(
                id=555, internal_id='pay123', save=mock.Mock(), **kw['defaults'])
            captured['row'] = row
            return row, True

        def _sign_auth(digest):
            return _sign(digest), TEST_SIGNER

        pps = 11 * WAD // 10
        with mock.patch('cusd_plus.vault.p_plus_wad', return_value=pps), \
             mock.patch('cusd_plus.vault.erc20_balance_raw',
                        return_value=(shares_value * WAD) // pps), \
             mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=usdt), \
             mock.patch.object(bsc_flow, '_sign_pay_authorization', side_effect=_sign_auth), \
             mock.patch('users.models.Account.objects') as acct_objs, \
             mock.patch('payments.models.PaymentTransaction.objects') as pt_objs:
            acct_objs.filter.return_value.order_by.return_value.first.return_value = \
                merchant_account
            pt_objs.get_or_create.side_effect = _goc
            result = bsc_flow.prepare_bsc_payment(
                self._user(), {'account_type': 'personal', 'account_index': 0}, invoice)
        return result, captured.get('row'), pps

    def _decode_pay(self, pay):
        return abi_decode(
            ['bytes32', 'address', 'uint256', 'address', 'uint256', 'bytes'],
            bytes.fromhex(pay['data'][10:]))

    def _assert_batch_shape(self, calls, token, gross_units):
        """[approve(payContract, gross),
            pay(invoiceId, token, gross, merchant, deadline, authSig)]"""
        self.assertEqual(len(calls), 2)
        approve, pay = calls
        inv32 = bsc_flow.invoice_id_bytes32('inv123')[2:]

        self.assertEqual(approve['to'], token)
        self.assertEqual(approve['data'][2:10], SEL_APPROVE)
        self.assertEqual(approve['data'][10:74], PAY_CONTRACT[2:].lower().rjust(64, '0'))
        self.assertEqual(int(approve['data'][74:138], 16), gross_units)

        self.assertEqual(pay['to'], PAY_CONTRACT.lower())
        self.assertEqual(pay['data'][2:10], SEL_PAY)
        inv_b, d_token, d_gross, d_merchant, d_deadline, auth_sig = self._decode_pay(pay)
        self.assertEqual(inv_b.hex(), inv32)
        self.assertEqual(d_token.lower(), token)
        self.assertEqual(int(d_gross), gross_units)
        self.assertEqual(d_merchant.lower(), MERCHANT)
        self.assertGreater(int(d_deadline), 0)
        self.assertEqual(len(auth_sig), 65)  # a real r||s||v authorization

    def test_cusd_plus_batch_shape_and_fee(self):
        result, row, pps = self._prepare(self._invoice('10'))
        self.assertTrue(result['success'], result)
        gross_wei = 10 * WAD
        self._assert_batch_shape(result['calls'], VAULT.lower(),
                                 (gross_wei * WAD) // pps)
        self.assertEqual(result['token_type'], 'CUSD_PLUS')
        fee_wei = bsc_flow.payment_fee_wei(gross_wei)
        self.assertEqual(result['fee'], str(Decimal(fee_wei) / WAD))
        self.assertEqual(result['net'], str(Decimal(gross_wei - fee_wei) / WAD))
        # The authorization terms are stashed for the submit-side re-check.
        self.assertEqual(row.blockchain_data['pay_signer'], TEST_SIGNER)
        self.assertGreater(row.blockchain_data['pay_deadline'], 0)

    def test_usdt_fallback_batch(self):
        result, _, _ = self._prepare(self._invoice('10'), shares_value=0, usdt=100 * WAD)
        self.assertTrue(result['success'], result)
        self._assert_batch_shape(result['calls'], USDT_BSC, 10 * WAD)
        self.assertEqual(result['token_type'], 'USDT')

    def test_merchant_without_address_blocks_and_nudges(self):
        with mock.patch.object(bsc_flow, '_notify_merchant_needs_app') as nudge:
            result, _, _ = self._prepare(self._invoice('10'), merchant_addr=None)
        self.assertEqual(result['error'], 'merchant_no_bsc_address')
        nudge.assert_called_once()

    def test_algorand_invoice_refused_on_bsc(self):
        """THE cross-rail guard (Codex audit [P1]). A legacy CONFIO invoice
        is indistinguishable from a migrated one by token_type alone, so the
        invoice names its chain and this rail refuses anything else —
        otherwise both rails could prepare the same PENDING row and the
        contract's per-chain invoiceDone guard could not stop the Algorand
        half of a double settlement."""
        for token in ('CONFIO', 'CUSD', 'CUSD_PLUS'):
            result, _, _ = self._prepare(
                self._invoice('10', token=token, chain='ALGORAND'))
            self.assertEqual(result['error'], 'invoice_not_bsc', token)

    def test_missing_chain_attribute_fails_closed(self):
        invoice = self._invoice('10')
        del invoice.settlement_chain
        result, _, _ = self._prepare(invoice)
        self.assertEqual(result['error'], 'invoice_not_bsc')

    def test_confio_invoice_pays_in_confio(self):
        """The second charge denomination (2026-08-01): the BEP-20 moves
        directly, amount is a token COUNT, no share-price conversion."""
        # shares_value drives the mocked erc20_balance_raw, which the CONFIO
        # branch reads as the payer's raw CONFIO balance.
        result, row, _ = self._prepare(
            self._invoice('250', token='CONFIO'), shares_value=1_000 * WAD)
        self.assertTrue(result['success'], result)
        self._assert_batch_shape(result['calls'], CONFIO_TOKEN.lower(), 250 * WAD)
        self.assertEqual(result['token_type'], 'CONFIO')
        self.assertEqual(row.blockchain_data['kind'], 'pay_confio')
        fee_wei = bsc_flow.payment_fee_wei(250 * WAD)
        self.assertEqual(result['fee'], str(Decimal(fee_wei) / WAD))

    def test_confio_invoice_insufficient_confio_balance(self):
        # The CONFIO branch never falls back to the dollar funding sources.
        result, _, _ = self._prepare(
            self._invoice('250', token='CONFIO'), shares_value=0, usdt=10_000 * WAD)
        self.assertEqual(result['error'], 'insufficient_balance')

    @override_settings(BSC_CONFIO_TOKEN_ADDRESS='')
    def test_confio_invoice_without_token_configured(self):
        result, _, _ = self._prepare(self._invoice('250', token='CONFIO'))
        self.assertEqual(result['error'], 'confio_not_configured')

    def test_unknown_invoice_token_rejected(self):
        result, _, _ = self._prepare(self._invoice('10', token='USDC'))
        self.assertEqual(result['error'], 'unsupported_token')

    def test_expired_invoice_rejected(self):
        invoice = self._invoice('10')
        invoice.is_expired = True
        result, _, _ = self._prepare(invoice)
        self.assertEqual(result['error'], 'invoice_expired')

    def test_insufficient_balance(self):
        result, _, _ = self._prepare(self._invoice('10'), shares_value=0, usdt=0)
        self.assertEqual(result['error'], 'insufficient_balance')

    @override_settings(BSC_PAY_CONTRACT_ADDRESS='')
    def test_missing_pay_contract_refuses(self):
        result, _, _ = self._prepare(self._invoice('10'))
        self.assertEqual(result['error'], 'pay_contract_not_configured')

    def test_self_pay_blocked_for_merchant_business(self):
        result = bsc_flow.prepare_bsc_payment(
            self._user(), {'account_type': 'business', 'business_id': 77},
            self._invoice('10'))
        self.assertEqual(result['error'], 'self_pay_not_allowed')

    @override_settings(BSC_PAY_ENABLED=False)
    def test_dark_flag_blocks(self):
        result, _, _ = self._prepare(self._invoice('10'))
        self.assertEqual(result['error'], 'bsc_pay_disabled')


@override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT, BSC_CONFIO_TOKEN_ADDRESS=CONFIO_TOKEN,
                   BSC_PAY_CONTRACT_ADDRESS=PAY_CONTRACT)
class SubmitValidatorTests(SimpleTestCase):
    GROSS = 10 * WAD

    def _tx(self, kind='pay_usdt'):
        return SimpleNamespace(
            payer_address=PAYER,
            merchant_address=MERCHANT,
            invoice=SimpleNamespace(internal_id='inv123'),
            blockchain_data={'kind': kind, 'pay_deadline': DEADLINE,
                             'pay_signer': TEST_SIGNER.lower()},
        )

    def _approve(self, token, spender=PAY_CONTRACT, amount=None):
        return {'to': token, 'value': '0',
                'data': '0x' + SEL_APPROVE + spender[2:].lower().rjust(64, '0')
                        + format(amount if amount is not None else self.GROSS, 'x').rjust(64, '0')}

    def _pay(self, token, to=PAY_CONTRACT, invoice_id='inv123', amount=None,
             merchant=MERCHANT, deadline=DEADLINE, signer=None):
        """Build the real dynamic-bytes pay() calldata with a genuine
        authorization signed over the exact terms (chain_id default 56)."""
        amount = self.GROSS if amount is None else amount
        inv32 = bsc_flow.invoice_id_bytes32(invoice_id)
        digest = bsc_flow.pay_authorization_digest(
            PAY_CONTRACT, 56, inv32, PAYER, token, amount, merchant, deadline)
        sig = (signer or TEST_PK).sign_msg_hash(digest)
        sig_bytes = sig.r.to_bytes(32, 'big') + sig.s.to_bytes(32, 'big') + bytes([27 + sig.v])
        args = abi_encode(
            ['bytes32', 'address', 'uint256', 'address', 'uint256', 'bytes'],
            [bytes.fromhex(inv32[2:]), to_checksum_address(token), amount,
             to_checksum_address(merchant), deadline, sig_bytes])
        return {'to': to.lower(), 'value': '0', 'data': '0x' + SEL_PAY + args.hex()}

    def test_valid_batch_passes(self):
        for token, kind in ((USDT_BSC, 'pay_usdt'), (VAULT, 'pay_cusd_plus'),
                            (CONFIO_TOKEN.lower(), 'pay_confio')):
            bsc_flow._validate_payment_batch(
                [self._approve(token), self._pay(token)], self._tx(kind))

    def test_token_not_pinned_to_kind_rejected(self):
        """A CONFIO row can only move CONFIO: an otherwise well-formed
        dollar batch stored on a pay_confio row is refused, even though the
        contract's own allowlist would accept the token."""
        calls = [self._approve(VAULT), self._pay(VAULT)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx('pay_confio'))

    def test_unknown_kind_rejected(self):
        calls = [self._approve(USDT_BSC), self._pay(USDT_BSC)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx('pay_something_else'))

    def test_merchant_tamper_rejected(self):
        calls = [self._approve(USDT_BSC),
                 self._pay(USDT_BSC, merchant='0x' + '99' * 20)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())

    def test_invoice_tamper_rejected(self):
        calls = [self._approve(USDT_BSC), self._pay(USDT_BSC, invoice_id='OTHER')]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())

    def test_gross_mismatch_rejected(self):
        # approve MORE than pay() pulls → residual allowance would linger.
        calls = [self._approve(USDT_BSC, amount=self.GROSS + 1), self._pay(USDT_BSC)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())

    def test_foreign_spender_rejected(self):
        calls = [self._approve(USDT_BSC, spender='0x' + '99' * 20), self._pay(USDT_BSC)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())

    def test_pay_to_foreign_contract_rejected(self):
        calls = [self._approve(USDT_BSC), self._pay(USDT_BSC, to='0x' + '99' * 20)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())

    def test_token_mismatch_rejected(self):
        # approve USDT but pay() names the vault → pay() would pull a token
        # the payer never approved in this batch — reject upfront.
        calls = [self._approve(USDT_BSC), self._pay(VAULT)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())

    def test_foreign_token_rejected(self):
        alien = '0x' + 'ab' * 20
        calls = [self._approve(alien), self._pay(alien)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())

    def test_single_call_rejected(self):
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch([self._approve(USDT_BSC)], self._tx())

    def test_expired_authorization_rejected(self):
        tx = self._tx()
        tx.blockchain_data['pay_deadline'] = 1  # long past
        calls = [self._approve(USDT_BSC), self._pay(USDT_BSC, deadline=1)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, tx)

    def test_deadline_tamper_rejected(self):
        # calldata deadline differs from the stored authorization deadline.
        calls = [self._approve(USDT_BSC), self._pay(USDT_BSC, deadline=DEADLINE - 1)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())

    def test_forged_authorization_rejected(self):
        # A signature from a different key does not recover to paymentSigner.
        attacker = keys.PrivateKey(bytes.fromhex('99' * 32))
        calls = [self._approve(USDT_BSC), self._pay(USDT_BSC, signer=attacker)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())
