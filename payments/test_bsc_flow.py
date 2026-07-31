"""
BSC invoice payments (payments/bsc_flow.py) — the properties that make the
2-transfer batch safe:

  1. the 0.9% fee is CEILING division in wei, exact parity with the
     Algorand payment builder's integer semantics;
  2. the submit-side validator accepts only [transfer(merchant, net),
     transfer(feeTreasury, fee)] on one token — recipient or destination
     tampering is structurally impossible;
  3. a merchant business without a registered bsc_address BLOCKS the
     payment and nudges the invoice creator (owner-only registration).

Runs without a database (ORM + RPC mocked, house style):
    myvenv/bin/python manage.py test payments.test_bsc_flow
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from cusd_plus.sponsor_7702 import PolicyError, SEL_TRANSFER, USDT_BSC
from payments import bsc_flow

VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'
FEE_TREASURY = '0x' + 'fe' * 20
PAYER = '0x' + '11' * 20
MERCHANT = '0x' + '22' * 20
WAD = 10 ** 18


class FeeMathTests(SimpleTestCase):
    """Wei ceiling parity with (amount*90 + 9999) // 10000."""

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
    BSC_FEE_RECIPIENT_ADDRESS=FEE_TREASURY,
    BSC_PAY_ENABLED=True,
)
class PrepareBatchTests(SimpleTestCase):
    def _invoice(self, amount='10', token='CUSD'):
        merchant_business = SimpleNamespace(id=77, name='Bodega La 22')
        return SimpleNamespace(
            internal_id='inv123', status='PENDING', is_expired=False,
            token_type=token, amount=Decimal(amount),
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
                internal_id='pay123', save=mock.Mock(), **kw['defaults'])
            captured['row'] = row
            return row, True

        pps = 11 * WAD // 10
        with mock.patch('cusd_plus.vault.p_plus_wad', return_value=pps), \
             mock.patch('cusd_plus.vault.erc20_balance_raw',
                        return_value=(shares_value * WAD) // pps), \
             mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=usdt), \
             mock.patch('users.models.Account.objects') as acct_objs, \
             mock.patch('payments.models.PaymentTransaction.objects') as pt_objs:
            acct_objs.filter.return_value.order_by.return_value.first.return_value = \
                merchant_account
            pt_objs.get_or_create.side_effect = _goc
            result = bsc_flow.prepare_bsc_payment(
                self._user(), {'account_type': 'personal', 'account_index': 0}, invoice)
        return result, captured.get('row'), pps

    def test_cusd_plus_batch_shape_and_fee(self):
        result, _, pps = self._prepare(self._invoice('10'))
        self.assertTrue(result['success'], result)
        calls = result['calls']
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['to'], VAULT.lower())
        self.assertEqual(calls[1]['to'], VAULT.lower())
        gross_wei = 10 * WAD
        fee_wei = bsc_flow.payment_fee_wei(gross_wei)
        self.assertEqual(calls[0]['data'][10:74], MERCHANT[2:].lower().rjust(64, '0'))
        self.assertEqual(int(calls[0]['data'][74:138], 16),
                         ((gross_wei - fee_wei) * WAD) // pps)
        self.assertEqual(calls[1]['data'][10:74], FEE_TREASURY[2:].rjust(64, '0'))
        self.assertEqual(int(calls[1]['data'][74:138], 16), (fee_wei * WAD) // pps)
        self.assertEqual(result['token_type'], 'CUSD_PLUS')

    def test_usdt_fallback_batch(self):
        result, _, _ = self._prepare(self._invoice('10'), shares_value=0, usdt=100 * WAD)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['calls'][0]['to'], USDT_BSC)
        self.assertEqual(int(result['calls'][0]['data'][74:138], 16),
                         10 * WAD - bsc_flow.payment_fee_wei(10 * WAD))
        self.assertEqual(result['token_type'], 'USDT')

    def test_merchant_without_address_blocks_and_nudges(self):
        with mock.patch.object(bsc_flow, '_notify_merchant_needs_app') as nudge:
            result, _, _ = self._prepare(self._invoice('10'), merchant_addr=None)
        self.assertEqual(result['error'], 'merchant_no_bsc_address')
        nudge.assert_called_once()

    def test_confio_invoice_rejected(self):
        result, _, _ = self._prepare(self._invoice('10', token='CONFIO'))
        self.assertEqual(result['error'], 'invoice_not_dollar')

    def test_expired_invoice_rejected(self):
        invoice = self._invoice('10')
        invoice.is_expired = True
        result, _, _ = self._prepare(invoice)
        self.assertEqual(result['error'], 'invoice_expired')

    def test_insufficient_balance(self):
        result, _, _ = self._prepare(self._invoice('10'), shares_value=0, usdt=0)
        self.assertEqual(result['error'], 'insufficient_balance')

    @override_settings(BSC_FEE_RECIPIENT_ADDRESS='')
    def test_missing_fee_treasury_refuses(self):
        result, _, _ = self._prepare(self._invoice('10'))
        self.assertEqual(result['error'], 'fee_recipient_not_configured')

    def test_self_pay_blocked_for_merchant_business(self):
        result = bsc_flow.prepare_bsc_payment(
            self._user(), {'account_type': 'business', 'business_id': 77},
            self._invoice('10'))
        self.assertEqual(result['error'], 'self_pay_not_allowed')

    @override_settings(BSC_PAY_ENABLED=False)
    def test_dark_flag_blocks(self):
        result, _, _ = self._prepare(self._invoice('10'))
        self.assertEqual(result['error'], 'bsc_pay_disabled')


@override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT, BSC_FEE_RECIPIENT_ADDRESS=FEE_TREASURY)
class SubmitValidatorTests(SimpleTestCase):
    def _tx(self):
        return SimpleNamespace(merchant_address=MERCHANT)

    def _call(self, to, recipient, units):
        return {'to': to, 'value': '0',
                'data': '0x' + SEL_TRANSFER + recipient[2:].lower().rjust(64, '0')
                        + format(units, 'x').rjust(64, '0')}

    def test_valid_batch_passes(self):
        calls = [self._call(USDT_BSC, MERCHANT, 991),
                 self._call(USDT_BSC, FEE_TREASURY, 9)]
        bsc_flow._validate_payment_batch(calls, self._tx())

    def test_fee_recipient_tamper_rejected(self):
        calls = [self._call(USDT_BSC, MERCHANT, 991),
                 self._call(USDT_BSC, '0x' + '99' * 20, 9)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())

    def test_merchant_tamper_rejected(self):
        calls = [self._call(USDT_BSC, '0x' + '99' * 20, 991),
                 self._call(USDT_BSC, FEE_TREASURY, 9)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())

    def test_mixed_token_batch_rejected(self):
        calls = [self._call(USDT_BSC, MERCHANT, 991),
                 self._call(VAULT, FEE_TREASURY, 9)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())

    def test_single_call_rejected(self):
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(
                [self._call(USDT_BSC, MERCHANT, 991)], self._tx())

    def test_foreign_token_rejected(self):
        alien = '0x' + 'ab' * 20
        calls = [self._call(alien, MERCHANT, 991),
                 self._call(alien, FEE_TREASURY, 9)]
        with self.assertRaises(PolicyError):
            bsc_flow._validate_payment_batch(calls, self._tx())
