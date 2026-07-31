"""
BSC payroll (payroll/bsc_flow.py) — the properties that make the on-chain
delegate model safe from the backend side:

  1. the EIP-712 payout digest matches ConfioPayrollVault.payoutDigest
     byte-for-byte (shared vector, forge side:
     test_payoutDigest_sharedVector);
  2. admin batches are rebuilt from INTEGER params — withdraw destination
     is structurally pinned to the business's own EOA;
  3. payout prepare blocks on missing recipient address (with the
     activation nudge), non-delegates, and thin escrow — and picks the
     transfer/redeem branch from recipient eligibility.

Runs without a database (ORM + RPC mocked, house style):
    myvenv/bin/python manage.py test payroll.test_bsc_flow
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings
from eth_utils import keccak

from payroll import bsc_flow

PAYROLL_VAULT = '0x7777777777777777777777777777777777777777'
VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'
BUSINESS_ADDR = '0x' + '11' * 20
RECIPIENT_ADDR = '0x' + '22' * 20
SIGNER_ADDR = '0x' + '33' * 20
WAD = 10 ** 18


@override_settings(BSC_PAYROLL_VAULT_ADDRESS=PAYROLL_VAULT)
class DigestParityTests(SimpleTestCase):
    """The three-way anchor: this vector is asserted against the CONTRACT
    in forge (test_payoutDigest_sharedVector). Never change one alone."""

    def test_payout_digest_parity(self):
        p = {
            'business': '0x1111111111111111111111111111111111111111',
            'recipient': '0x2222222222222222222222222222222222222222',
            'net_shares': 100 * WAD,
            'fee_shares': WAD,
            'redeem_to_usdt': True,
            'min_usdt_out': 99 * WAD,
            'item_id': '0x' + keccak(text='item-vector').hex(),
            'deadline': 1_800_000_000,
        }
        self.assertEqual(
            '0x' + bsc_flow.payout_digest(p, 56).hex(),
            '0xef818ab5751bd3f46c0459e4afd2f4b2802562771dd9e2a96a63bbfa36295e9c',
        )

    def test_payout_calldata_roundtrip(self):
        from eth_abi import decode as abi_decode
        p = {
            'business': BUSINESS_ADDR, 'recipient': RECIPIENT_ADDR,
            'net_shares': 5 * WAD, 'fee_shares': 0, 'redeem_to_usdt': False,
            'min_usdt_out': 0, 'item_id': '0x' + 'ab' * 32, 'deadline': 123,
        }
        data = bsc_flow.payout_calldata(p, '0x' + 'cd' * 65)
        self.assertTrue(data.startswith('0x' + bsc_flow.SEL_PAYOUT))
        decoded = abi_decode(
            ['(address,address,uint256,uint256,bool,uint256,bytes32,uint256)', 'bytes'],
            bytes.fromhex(data[2 + 8:]),
        )
        tup, sig = decoded
        self.assertEqual(tup[0].lower(), BUSINESS_ADDR)
        self.assertEqual(tup[2], 5 * WAD)
        self.assertEqual(sig, bytes.fromhex('cd' * 65))

    def test_item_id_deterministic(self):
        a = bsc_flow.item_id_bytes32('abc123')
        self.assertEqual(a, bsc_flow.item_id_bytes32('abc123'))
        self.assertEqual(len(a), 2 + 64)
        self.assertNotEqual(a, bsc_flow.item_id_bytes32('abc124'))


@override_settings(
    BSC_PAYROLL_VAULT_ADDRESS=PAYROLL_VAULT,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
)
class AdminBatchTests(SimpleTestCase):
    def test_fund_batch_shape(self):
        calls = bsc_flow.build_admin_calls('fund', shares=7 * WAD)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['to'], VAULT.lower())
        self.assertEqual(calls[0]['data'][2:10], '095ea7b3')  # approve
        self.assertEqual(calls[0]['data'][10:74],
                         PAYROLL_VAULT[2:].rjust(64, '0'))
        self.assertEqual(calls[1]['to'], PAYROLL_VAULT)
        self.assertEqual(calls[1]['data'][2:10], bsc_flow.SEL_PAYROLL_DEPOSIT)
        self.assertEqual(int(calls[1]['data'][10:74], 16), 7 * WAD)

    def test_withdraw_destination_pinned_to_business(self):
        calls = bsc_flow.build_admin_calls(
            'withdraw', shares=WAD, business_addr=BUSINESS_ADDR)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['data'][2:10], bsc_flow.SEL_PAYROLL_WITHDRAW)
        self.assertEqual(calls[0]['data'][74:138], BUSINESS_ADDR[2:].rjust(64, '0'))

    def test_set_delegate_words(self):
        calls = bsc_flow.build_admin_calls(
            'set_delegate', delegate_addr=SIGNER_ADDR, allowed=False)
        self.assertEqual(calls[0]['data'][10:74], SIGNER_ADDR[2:].rjust(64, '0'))
        self.assertEqual(int(calls[0]['data'][74:138], 16), 0)


def _item(net='100', fee='0.9', recipient_addr=RECIPIENT_ADDR):
    recipient_user = SimpleNamespace(id=9, get_full_name=lambda: 'Empleado')
    return SimpleNamespace(
        id=42, internal_id='item42', status='PENDING',
        run=SimpleNamespace(business_id=77,
                            business=SimpleNamespace(id=77, name='Bodega')),
        recipient_user=recipient_user,
        recipient_account=SimpleNamespace(bsc_address=recipient_addr),
        net_amount=Decimal(net), fee_amount=Decimal(fee),
        blockchain_data=None, save=mock.Mock(),
    )


def _jwt_ctx():
    return {'account_type': 'business', 'business_id': 77, 'account_index': 0}


def _user():
    personal = SimpleNamespace(bsc_address=SIGNER_ADDR)
    accounts = mock.Mock()
    accounts.filter.return_value.first.return_value = personal
    return SimpleNamespace(id=1, accounts=accounts)


@override_settings(
    BSC_PAYROLL_VAULT_ADDRESS=PAYROLL_VAULT,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    BSC_PAYROLL_ENABLED=True,
)
class PreparePayoutTests(SimpleTestCase):
    def _prepare(self, item, eligible=True, escrow=10_000 * WAD,
                 is_delegate=True):
        business_account = SimpleNamespace(
            bsc_address=BUSINESS_ADDR,
            business=SimpleNamespace(id=77, name='Bodega'))
        pps = 11 * WAD // 10
        with mock.patch('users.models.Account.objects') as acct_objs, \
             mock.patch('cusd_plus.vault.p_plus_wad', return_value=pps), \
             mock.patch('cusd_plus.eligibility.is_ondo_eligible',
                        return_value=eligible), \
             mock.patch.object(bsc_flow, 'escrow_shares_raw',
                               return_value=escrow), \
             mock.patch.object(bsc_flow, 'is_onchain_delegate',
                               return_value=is_delegate):
            acct_objs.filter.return_value.select_related.return_value.first.return_value = \
                business_account
            result = bsc_flow.prepare_bsc_payroll_payout(_user(), _jwt_ctx(), item)
        return result, pps

    def test_eligible_recipient_transfer_branch(self):
        item = _item()
        result, pps = self._prepare(item, eligible=True)
        self.assertTrue(result['success'], result)
        self.assertFalse(result['redeem_to_usdt'])
        payout = item.blockchain_data['bsc_payout']
        self.assertEqual(int(payout['net_shares']), (100 * WAD * WAD) // pps)
        self.assertEqual(int(payout['min_usdt_out']), 0)
        self.assertEqual(payout['expected_signer'], SIGNER_ADDR)
        self.assertEqual(item.status, 'PREPARED')
        self.assertEqual(item.token_type, 'CUSD_PLUS')

    def test_ineligible_recipient_redeem_branch(self):
        item = _item()
        result, _ = self._prepare(item, eligible=False)
        self.assertTrue(result['success'], result)
        self.assertTrue(result['redeem_to_usdt'])
        payout = item.blockchain_data['bsc_payout']
        self.assertEqual(int(payout['min_usdt_out']),
                         (100 * WAD * 9_950) // 10_000)
        self.assertEqual(item.token_type, 'USDT')

    def test_recipient_without_address_blocks_and_nudges(self):
        item = _item(recipient_addr=None)
        with mock.patch.object(bsc_flow, '_notify_recipient_needs_app') as nudge:
            result, _ = self._prepare(item)
        self.assertEqual(result['error'], 'recipient_no_bsc_address')
        nudge.assert_called_once()

    def test_non_delegate_rejected(self):
        result, _ = self._prepare(_item(), is_delegate=False)
        self.assertEqual(result['error'], 'not_onchain_delegate')

    def test_thin_escrow_rejected(self):
        result, _ = self._prepare(_item(net='100', fee='0.9'), escrow=50 * WAD)
        self.assertEqual(result['error'], 'insufficient_escrow')

    def test_wrong_business_rejected(self):
        item = _item()
        item.run.business_id = 88
        result, _ = self._prepare(item)
        self.assertEqual(result['error'], 'not_your_payroll')

    @override_settings(BSC_PAYROLL_ENABLED=False)
    def test_dark_flag_blocks(self):
        result, _ = self._prepare(_item())
        self.assertEqual(result['error'], 'bsc_payroll_disabled')


@override_settings(
    BSC_PAYROLL_VAULT_ADDRESS=PAYROLL_VAULT,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    BSC_PAYROLL_ENABLED=True,
)
class SubmitPayoutTests(SimpleTestCase):
    def _prepared_item(self):
        import time as _time
        item = _item()
        item.status = 'PREPARED'
        item.blockchain_data = {'bsc_payout': {
            'business': BUSINESS_ADDR, 'recipient': RECIPIENT_ADDR,
            'net_shares': str(90 * WAD), 'fee_shares': str(WAD),
            'redeem_to_usdt': False, 'min_usdt_out': '0',
            'item_id': bsc_flow.item_id_bytes32('item42'),
            'deadline': int(_time.time()) + 600,
            'expected_signer': SIGNER_ADDR, 'chain_id': 56,
        }}
        return item

    def _submit(self, item, recovered=SIGNER_ADDR):
        business_account = SimpleNamespace(
            bsc_address=BUSINESS_ADDR,
            business=SimpleNamespace(id=77, name='Bodega'))
        with mock.patch('users.models.Account.objects') as acct_objs, \
             mock.patch('cusd_plus.sponsor_7702.recover_intent_signer',
                        return_value=recovered):
            acct_objs.filter.return_value.select_related.return_value.first.return_value = \
                business_account
            return bsc_flow.submit_bsc_payroll_payout(
                _user(), _jwt_ctx(), item, '0x' + 'ab' * 65)

    def test_wrong_signer_rejected(self):
        result = self._submit(self._prepared_item(), recovered='0x' + '99' * 20)
        self.assertEqual(result['error'], 'bad_payout_signature')

    def test_expired_payout_rejected(self):
        item = self._prepared_item()
        item.blockchain_data['bsc_payout']['deadline'] = 100
        result = self._submit(item)
        self.assertEqual(result['error'], 'payout_expired')

    def test_unprepared_item_rejected(self):
        item = self._prepared_item()
        item.status = 'PENDING'
        result = self._submit(item)
        self.assertEqual(result['error'], 'item_not_prepared')

    def test_business_mismatch_rejected(self):
        item = self._prepared_item()
        item.blockchain_data['bsc_payout']['business'] = '0x' + '99' * 20
        result = self._submit(item)
        self.assertEqual(result['error'], 'payout_not_prepared')
