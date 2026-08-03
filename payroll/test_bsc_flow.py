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

    def _vector(self, asset):
        redeem = asset == bsc_flow.ASSET_CUSD_PLUS
        return {
            'business': '0x1111111111111111111111111111111111111111',
            'recipient': '0x2222222222222222222222222222222222222222',
            'asset': asset,
            'net_amount': 100 * WAD,
            'fee_amount': WAD,
            'redeem_to_usdt': redeem,
            'min_usdt_out': 99 * WAD if redeem else 0,
            'item_id': '0x' + keccak(text='item-vector').hex(),
            'deadline': 1_800_000_000,
        }

    def test_payout_digest_parity(self):
        self.assertEqual(
            '0x' + bsc_flow.payout_digest(self._vector(bsc_flow.ASSET_CUSD_PLUS), 56).hex(),
            '0x2c40c42f0c28313ecc1797a92bdcdb90ba02269f2637e7a9df46d019696aa62e',
        )

    def test_payout_digest_parity_usdt_pool(self):
        """The asset is INSIDE the struct hash: the same wage drawn from the
        other pool is a different signature, so a client that dropped the
        field could not accidentally authorize the wrong escrow."""
        self.assertEqual(
            '0x' + bsc_flow.payout_digest(self._vector(bsc_flow.ASSET_USDT), 56).hex(),
            '0x442f16cf1636af9d2af1a59a731d45e2f1fc2638767f9532844e128d62b2644f',
        )

    def test_payout_calldata_roundtrip(self):
        from eth_abi import decode as abi_decode
        p = {
            'business': BUSINESS_ADDR, 'recipient': RECIPIENT_ADDR,
            'asset': bsc_flow.ASSET_USDT,
            'net_amount': 5 * WAD, 'fee_amount': 0, 'redeem_to_usdt': False,
            'min_usdt_out': 0, 'item_id': '0x' + 'ab' * 32, 'deadline': 123,
        }
        data = bsc_flow.payout_calldata(p, '0x' + 'cd' * 65)
        self.assertTrue(data.startswith('0x' + bsc_flow.SEL_PAYOUT))
        decoded = abi_decode(
            ['(address,address,uint8,uint256,uint256,bool,uint256,bytes32,uint256)', 'bytes'],
            bytes.fromhex(data[2 + 8:]),
        )
        tup, sig = decoded
        self.assertEqual(tup[0].lower(), BUSINESS_ADDR)
        self.assertEqual(tup[2], bsc_flow.ASSET_USDT)
        self.assertEqual(tup[3], 5 * WAD)
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
        self.assertEqual(int(calls[1]['data'][10:74], 16), bsc_flow.ASSET_CUSD_PLUS)
        self.assertEqual(int(calls[1]['data'][74:138], 16), 7 * WAD)

    def test_usdt_fund_batch_approves_the_token_being_parked(self):
        """A USDT top-up that approved the cUSD+ vault by reflex would
        deposit nothing and revert on the transferFrom."""
        usdt = '0x55d398326f99059ff775485246999027b3197955'
        with mock.patch('cusd_plus.vault.usdt_address', return_value=usdt):
            calls = bsc_flow.build_admin_calls(
                'fund', shares=7 * WAD, asset=bsc_flow.ASSET_USDT)
        self.assertEqual(calls[0]['to'], usdt)
        self.assertEqual(calls[0]['data'][2:10], '095ea7b3')
        self.assertEqual(int(calls[1]['data'][10:74], 16), bsc_flow.ASSET_USDT)
        self.assertEqual(int(calls[1]['data'][74:138], 16), 7 * WAD)

    def test_withdraw_destination_pinned_to_business(self):
        calls = bsc_flow.build_admin_calls(
            'withdraw', shares=WAD, business_addr=BUSINESS_ADDR)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['data'][2:10], bsc_flow.SEL_PAYROLL_WITHDRAW)
        self.assertEqual(int(calls[0]['data'][10:74], 16), bsc_flow.ASSET_CUSD_PLUS)
        self.assertEqual(int(calls[0]['data'][74:138], 16), WAD)
        self.assertEqual(calls[0]['data'][138:202], BUSINESS_ADDR[2:].rjust(64, '0'))

    def test_set_delegate_words(self):
        calls = bsc_flow.build_admin_calls(
            'set_delegate', delegate_addr=SIGNER_ADDR, allowed=False)
        self.assertEqual(calls[0]['data'][10:74], SIGNER_ADDR[2:].rjust(64, '0'))
        self.assertEqual(int(calls[0]['data'][74:138], 16), 0)

    def test_activation_allowlists_everyone_in_one_batch(self):
        """Wizard activation is N delegates; N sponsored batches would eat
        the sponsor's whole daily allowance, so it must be ONE batch."""
        second = '0x' + '44' * 20
        calls = bsc_flow.build_admin_calls(
            'set_delegate', delegate_addrs=[SIGNER_ADDR, second])
        self.assertEqual(len(calls), 2)
        self.assertEqual([c['to'] for c in calls], [PAYROLL_VAULT] * 2)
        self.assertEqual(calls[0]['data'][10:74], SIGNER_ADDR[2:].rjust(64, '0'))
        self.assertEqual(calls[1]['data'][10:74], second[2:].rjust(64, '0'))
        self.assertTrue(all(int(c['data'][74:138], 16) == 1 for c in calls))

    def test_set_delegate_without_any_address_is_refused(self):
        with self.assertRaises(ValueError):
            bsc_flow.build_admin_calls('set_delegate')


@override_settings(
    BSC_PAYROLL_VAULT_ADDRESS=PAYROLL_VAULT,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    BSC_PAYROLL_ENABLED=True,
)
class ActivationTests(SimpleTestCase):
    """Activation on BSC = allowlisting signers. The owner signs payouts with
    their PERSONAL key, so leaving them out locks them out of their own
    payroll — and the client must not have to know who they are."""

    def _prepare(self, **kwargs):
        business_account = SimpleNamespace(
            id=5, bsc_address=BUSINESS_ADDR,
            business=SimpleNamespace(id=77, name='Bodega'))
        with mock.patch('users.models.Account.objects') as acct_objs:
            acct_objs.filter.return_value.select_related.return_value.first.return_value = \
                business_account
            return bsc_flow.prepare_bsc_payroll_admin(
                _user(), _jwt_ctx(), 'set_delegate', **kwargs)

    def test_include_self_allowlists_the_caller_from_the_jwt(self):
        result = self._prepare(include_self=True, delegate_user_ids=[])
        self.assertTrue(result['success'], result.get('error'))
        self.assertEqual(result['delegate_addresses'], [SIGNER_ADDR.lower()])
        self.assertEqual(len(result['calls']), 1)

    def test_a_lone_toggle_still_needs_a_named_delegate(self):
        result = self._prepare(delegate_user_ids=[])
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'delegate_not_found')


@override_settings(
    BSC_PAYROLL_VAULT_ADDRESS=PAYROLL_VAULT,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    BSC_PAYROLL_ENABLED=True,
)
class ReadSideTests(SimpleTestCase):
    """The half that shipped late: the screens read the Algorand boxes while
    the money lived in ConfioPayrollVault, so a funded business saw $0.00 and
    an allowlisted delegate saw "nómina no activada"."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
        # Most of these assert the SHARES pool; keep the USDT pool empty
        # unless a test says otherwise, rather than reaching for a node.
        empty_usdt = mock.patch.object(bsc_flow, 'escrow_usdt_raw', return_value=0)
        empty_usdt.start()
        self.addCleanup(empty_usdt.stop)

    def test_escrow_usd_is_shares_times_price(self):
        with mock.patch.object(bsc_flow, 'escrow_shares_raw', return_value=50 * WAD), \
                mock.patch('cusd_plus.vault.p_plus_wad', return_value=11 * WAD // 10):
            self.assertAlmostEqual(bsc_flow.escrow_usd(BUSINESS_ADDR), 55.0, places=6)

    def test_escrow_usd_sums_both_pools(self):
        """An employer who funded in USDT after being geo-blocked has float
        every bit as real as a share position; the hub prints one number."""
        with mock.patch.object(bsc_flow, 'escrow_shares_raw', return_value=50 * WAD), \
                mock.patch.object(bsc_flow, 'escrow_usdt_raw', return_value=20 * WAD), \
                mock.patch('cusd_plus.vault.p_plus_wad', return_value=11 * WAD // 10):
            self.assertAlmostEqual(bsc_flow.escrow_usd(BUSINESS_ADDR), 75.0, places=6)

    def test_funding_token_prefers_the_pool_that_already_has_money(self):
        """An employer who funded while eligible must not be told their
        existing float is unusable the day their country changes."""
        biz = SimpleNamespace(bsc_address=BUSINESS_ADDR)
        with mock.patch.object(bsc_flow, 'escrow_shares_raw', return_value=5 * WAD), \
                mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=False):
            self.assertEqual(bsc_flow.funding_token(biz, _user()), 'CUSD_PLUS')

    def test_funding_token_follows_eligibility_when_nothing_is_parked(self):
        biz = SimpleNamespace(bsc_address=BUSINESS_ADDR)
        with mock.patch.object(bsc_flow, 'escrow_shares_raw', return_value=0):
            with mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=False):
                # The blocked employer: their dollars stay raw USDT forever,
                # because the mint gate refuses them.
                self.assertEqual(bsc_flow.funding_token(biz, _user()), 'USDT')
            with mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True):
                self.assertEqual(bsc_flow.funding_token(biz, _user()), 'CUSD_PLUS')

    def test_escrow_split_reports_each_pool_separately(self):
        """[P1 2026-08-02] The pools are not fungible. A summed figure let the
        top-up screen validate a withdrawal against money the chosen pool did
        not have."""
        with mock.patch.object(bsc_flow, 'escrow_shares_raw', return_value=50 * WAD), \
                mock.patch.object(bsc_flow, 'escrow_usdt_raw', return_value=20 * WAD), \
                mock.patch('cusd_plus.vault.p_plus_wad', return_value=11 * WAD // 10):
            split = bsc_flow.escrow_split_usd(BUSINESS_ADDR)
        self.assertAlmostEqual(split['CUSD_PLUS'], 55.0, places=6)
        self.assertAlmostEqual(split['USDT'], 20.0, places=6)

    def test_escrow_split_reports_unknown_not_zero_on_a_dead_read(self):
        with mock.patch.object(bsc_flow, 'escrow_shares_raw',
                               side_effect=RuntimeError('node down')), \
                mock.patch.object(bsc_flow, 'escrow_usdt_raw', return_value=20 * WAD):
            split = bsc_flow.escrow_split_usd(BUSINESS_ADDR)
        self.assertIsNone(split['CUSD_PLUS'], 'unknown must not read as $0.00')
        self.assertAlmostEqual(split['USDT'], 20.0, places=6)

    def test_funding_token_reads_the_usdt_pool_before_falling_back(self):
        biz = SimpleNamespace(bsc_address=BUSINESS_ADDR)
        with mock.patch.object(bsc_flow, 'escrow_shares_raw', return_value=0), \
                mock.patch.object(bsc_flow, 'escrow_usdt_raw', return_value=3 * WAD), \
                mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True):
            self.assertEqual(bsc_flow.funding_token(biz, _user()), 'USDT')

    def test_escrow_read_failure_keeps_the_last_known_value(self):
        """A flaky node must not tell a business its payroll float is gone."""
        with mock.patch.object(bsc_flow, 'escrow_shares_raw', return_value=50 * WAD), \
                mock.patch('cusd_plus.vault.p_plus_wad', return_value=WAD):
            self.assertEqual(bsc_flow.escrow_usd(BUSINESS_ADDR), 50.0)
        bsc_flow.invalidate_escrow(BUSINESS_ADDR)
        with mock.patch.object(bsc_flow, 'escrow_shares_raw',
                               side_effect=RuntimeError('node down')):
            self.assertEqual(bsc_flow.escrow_usd(BUSINESS_ADDR), 50.0)

    def test_delegates_are_the_chain_s_answer_not_ours(self):
        """The DB proposes candidates; isDelegate decides."""
        other = '0x' + '55' * 20
        with mock.patch.object(bsc_flow, 'is_onchain_delegate',
                               side_effect=lambda _b, d: d == SIGNER_ADDR.lower()):
            got = bsc_flow.onchain_delegates(BUSINESS_ADDR, [SIGNER_ADDR, other])
        self.assertEqual(got, [SIGNER_ADDR.lower()])

    def test_a_new_candidate_is_asked_about_even_inside_the_ttl(self):
        """Caching the whole answer per business reported an employee who
        registered their address seconds ago as "not a delegate" without the
        chain ever being asked about them."""
        newcomer = '0x' + '66' * 20
        with mock.patch.object(bsc_flow, 'is_onchain_delegate', return_value=True):
            self.assertEqual(bsc_flow.onchain_delegates(BUSINESS_ADDR, [SIGNER_ADDR]),
                             [SIGNER_ADDR.lower()])
        with mock.patch.object(bsc_flow, 'is_onchain_delegate', return_value=True) as call:
            got = bsc_flow.onchain_delegates(BUSINESS_ADDR, [SIGNER_ADDR, newcomer])
            call.assert_called_once_with(BUSINESS_ADDR.lower(), newcomer.lower())
        self.assertEqual(got, [SIGNER_ADDR.lower(), newcomer.lower()])

    def test_revoking_is_visible_on_the_next_read(self):
        with mock.patch.object(bsc_flow, 'is_onchain_delegate', return_value=True):
            bsc_flow.onchain_delegates(BUSINESS_ADDR, [SIGNER_ADDR])
        bsc_flow.invalidate_delegates(BUSINESS_ADDR)
        with mock.patch.object(bsc_flow, 'is_onchain_delegate', return_value=False):
            self.assertEqual(bsc_flow.onchain_delegates(BUSINESS_ADDR, [SIGNER_ADDR]), [])

    def test_delegate_read_failure_is_not_a_revocation(self):
        with mock.patch.object(bsc_flow, 'is_onchain_delegate', return_value=True):
            self.assertEqual(bsc_flow.onchain_delegates(BUSINESS_ADDR, [SIGNER_ADDR]),
                             [SIGNER_ADDR.lower()])
        bsc_flow.invalidate_delegates(BUSINESS_ADDR)
        with mock.patch.object(bsc_flow, 'is_onchain_delegate',
                               side_effect=RuntimeError('node down')):
            self.assertEqual(bsc_flow.onchain_delegates(BUSINESS_ADDR, [SIGNER_ADDR]),
                             [SIGNER_ADDR.lower()])

    def test_execution_rail_follows_the_conditions_the_write_path_falls_through_on(self):
        biz = SimpleNamespace(bsc_address=BUSINESS_ADDR)
        self.assertEqual(bsc_flow.execution_rail(biz), 'bsc')
        self.assertEqual(bsc_flow.rail_token('bsc'), 'CUSD_PLUS')
        # No BSC address for the business — funding could not be signed.
        self.assertEqual(bsc_flow.execution_rail(SimpleNamespace(bsc_address='')), 'algorand')
        with override_settings(BSC_PAYROLL_ENABLED=False):
            self.assertEqual(bsc_flow.execution_rail(biz), 'algorand')
        with override_settings(BSC_PAYROLL_VAULT_ADDRESS=''):
            self.assertEqual(bsc_flow.execution_rail(biz), 'algorand')
        self.assertEqual(bsc_flow.rail_token('algorand'), 'CUSD')

    def test_display_rail_follows_the_money_through_the_kill_switch(self):
        """withdraw deliberately survives BSC_PAYROLL_ENABLED=False, so a
        business with escrow still parked on BSC must keep SEEING it — the
        alternative is an Algorand balance beside a button that drains BSC."""
        biz = SimpleNamespace(bsc_address=BUSINESS_ADDR)
        with override_settings(BSC_PAYROLL_ENABLED=False), \
                mock.patch.object(bsc_flow, 'escrow_shares_raw', return_value=5 * WAD), \
                mock.patch('cusd_plus.vault.p_plus_wad', return_value=WAD):
            self.assertEqual(bsc_flow.display_rail(biz), 'bsc')
        bsc_flow.invalidate_escrow(BUSINESS_ADDR)
        # Nothing parked there: the legacy vault is the honest answer.
        with override_settings(BSC_PAYROLL_ENABLED=False), \
                mock.patch.object(bsc_flow, 'escrow_shares_raw', return_value=0), \
                mock.patch('cusd_plus.vault.p_plus_wad', return_value=WAD):
            self.assertEqual(bsc_flow.display_rail(biz), 'algorand')

    def test_a_first_read_failure_is_unknown_not_zero(self):
        """$0.00 and "we could not reach the node" are different sentences;
        only one of them makes a business think its payroll float is gone."""
        with mock.patch.object(bsc_flow, 'escrow_shares_raw',
                               side_effect=RuntimeError('node down')):
            self.assertIsNone(bsc_flow.escrow_usd(BUSINESS_ADDR))

    def test_one_dead_call_does_not_discard_the_other_candidates(self):
        other = '0x' + '77' * 20

        def flaky(_b, d):
            if d == other:
                raise RuntimeError('node down')
            return True

        with mock.patch.object(bsc_flow, 'is_onchain_delegate', side_effect=flaky):
            got, degraded = bsc_flow.onchain_delegates(
                BUSINESS_ADDR, [SIGNER_ADDR, other], with_status=True)
        # The healthy answer survives, and the caller is told the set is partial.
        self.assertEqual(got, [SIGNER_ADDR.lower()])
        self.assertTrue(degraded)


def _item(net='100', fee='0.9', recipient_addr=RECIPIENT_ADDR,
          run_token='CUSD_PLUS'):
    recipient_user = SimpleNamespace(id=9, get_full_name=lambda: 'Empleado')
    return SimpleNamespace(
        id=42, internal_id='item42', status='PENDING',
        run=SimpleNamespace(business_id=77, token_type=run_token,
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
             mock.patch.object(bsc_flow, 'escrow_usdt_raw',
                               return_value=escrow), \
             mock.patch.object(bsc_flow, 'is_onchain_delegate',
                               return_value=is_delegate):
            acct_objs.filter.return_value.select_related.return_value.first.return_value = \
                business_account
            result = bsc_flow.prepare_bsc_payroll_payout(_user(), _jwt_ctx(), item)
        return result, pps

    def test_a_legacy_cusd_run_is_never_paid_from_the_cusd_plus_escrow(self):
        """Enabling the flag must not retroactively move where already-booked
        wages are settled from. The run's own token pins its rail; the
        fall-through code sends the client to the Algorand path."""
        result, _ = self._prepare(_item(run_token='CUSD'))
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'run_on_legacy_rail')

    def test_eligible_recipient_transfer_branch(self):
        item = _item()
        result, pps = self._prepare(item, eligible=True)
        self.assertTrue(result['success'], result)
        self.assertFalse(result['redeem_to_usdt'])
        payout = item.blockchain_data['bsc_payout']
        self.assertEqual(payout['asset'], bsc_flow.ASSET_CUSD_PLUS)
        self.assertEqual(int(payout['net_amount']), (100 * WAD * WAD) // pps)
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

    def test_a_usdt_run_pays_raw_usdt_and_never_redeems(self):
        """The Ondo-BLOCKED employer's rail. There is nothing to redeem: the
        money is already what an ineligible employee would be redeemed INTO,
        and an eligible one sweeps it into cUSD+ themselves."""
        item = _item(run_token='USDT')
        result, _ = self._prepare(item, eligible=False)
        self.assertTrue(result['success'], result)
        self.assertFalse(result['redeem_to_usdt'])
        payout = item.blockchain_data['bsc_payout']
        self.assertEqual(payout['asset'], bsc_flow.ASSET_USDT)
        # Dollars ARE the units: no share price anywhere in this branch.
        self.assertEqual(int(payout['net_amount']), 100 * WAD)
        self.assertEqual(int(payout['fee_amount']), 9 * WAD // 10)
        self.assertEqual(int(payout['min_usdt_out']), 0)
        self.assertEqual(item.token_type, 'USDT')

    def test_a_usdt_run_pays_an_eligible_employee_in_usdt_too(self):
        item = _item(run_token='USDT')
        result, _ = self._prepare(item, eligible=True)
        self.assertTrue(result['success'], result)
        self.assertFalse(result['redeem_to_usdt'])
        self.assertEqual(item.token_type, 'USDT')

    def test_a_usdt_run_is_not_blocked_by_the_one_dollar_redeem_floor(self):
        """The floor is Ondo's, and a raw transfer never touches Ondo —
        gating it there would refuse a legitimate sub-$1 wage."""
        item = _item(net='0.50', fee='0', run_token='USDT')
        result, _ = self._prepare(item, eligible=False)
        self.assertTrue(result['success'], result)

    def test_admin_honours_an_explicitly_named_pool(self):
        """[P1 2026-08-02] The caller names the pool. Deriving it server-side
        hid the entire USDT pool from a business that still held one share."""
        business_account = SimpleNamespace(
            id=5, bsc_address=BUSINESS_ADDR,
            business=SimpleNamespace(id=77, name='Bodega'))
        usdt = '0x55d398326f99059ff775485246999027b3197955'
        with mock.patch('users.models.Account.objects') as acct_objs, \
             mock.patch('cusd_plus.vault.usdt_address', return_value=usdt), \
             mock.patch('cusd_plus.vault.erc20_balance_raw', return_value=500 * WAD), \
             mock.patch.object(bsc_flow, 'escrow_shares_raw', return_value=5 * WAD), \
             mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True):
            acct_objs.filter.return_value.select_related.return_value.first.return_value = \
                business_account
            # funding_token() would say CUSD_PLUS here (shares are parked);
            # the caller asks for USDT and gets USDT.
            result = bsc_flow.prepare_bsc_payroll_admin(
                _user(), _jwt_ctx(), 'fund', amount='10', token_type='USDT')
        self.assertTrue(result['success'], result.get('error'))
        self.assertEqual(result['asset'], bsc_flow.ASSET_USDT)
        self.assertEqual(result['token_type'], 'USDT')
        self.assertEqual(result['calls'][0]['to'], usdt)

    def test_admin_refuses_a_pool_that_does_not_exist(self):
        business_account = SimpleNamespace(
            id=5, bsc_address=BUSINESS_ADDR,
            business=SimpleNamespace(id=77, name='Bodega'))
        with mock.patch('users.models.Account.objects') as acct_objs:
            acct_objs.filter.return_value.select_related.return_value.first.return_value = \
                business_account
            result = bsc_flow.prepare_bsc_payroll_admin(
                _user(), _jwt_ctx(), 'fund', amount='10', token_type='CUSD')
        self.assertEqual(result['error'], 'unknown_token_type')

    def test_a_usdt_run_draws_on_the_usdt_pool_only(self):
        item = _item(run_token='USDT')
        business_account = SimpleNamespace(
            bsc_address=BUSINESS_ADDR,
            business=SimpleNamespace(id=77, name='Bodega'))
        with mock.patch('users.models.Account.objects') as acct_objs, \
             mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True), \
             mock.patch.object(bsc_flow, 'escrow_shares_raw', return_value=10_000 * WAD), \
             mock.patch.object(bsc_flow, 'escrow_usdt_raw', return_value=0), \
             mock.patch.object(bsc_flow, 'is_onchain_delegate', return_value=True):
            acct_objs.filter.return_value.select_related.return_value.first.return_value = \
                business_account
            result = bsc_flow.prepare_bsc_payroll_payout(_user(), _jwt_ctx(), item)
        # Thousands parked in shares must not pay a USDT-denominated wage.
        self.assertEqual(result['error'], 'insufficient_escrow')

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
    def test_a_paused_rail_blocks_without_sending_the_client_elsewhere(self):
        """A cUSD+ run has exactly ONE rail. Answering `bsc_payroll_disabled`
        here sent the client to the Algorand path, which refused the same run —
        stranding the wage with an error naming the wrong chain."""
        result, _ = self._prepare(_item())
        self.assertEqual(result['error'], 'bsc_payroll_paused')

    @override_settings(BSC_PAYROLL_ENABLED=False)
    def test_a_paused_rail_still_routes_a_legacy_run_to_algorand(self):
        result, _ = self._prepare(_item(run_token='CUSD'))
        self.assertEqual(result['error'], 'run_on_legacy_rail')


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
            'asset': bsc_flow.ASSET_CUSD_PLUS,
            'net_amount': str(90 * WAD), 'fee_amount': str(WAD),
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

    def test_a_v1_prepared_payout_asks_for_a_re_prepare(self):
        """Items left PREPARED across the v2 deploy carry the old
        netShares/feeShares shape. That signature is worthless here anyway
        (different typehash, domain version and contract address), so the
        answer is "re-prepare" — not a KeyError on the old keys."""
        item = self._prepared_item()
        payout = item.blockchain_data['bsc_payout']
        payout['net_shares'] = payout.pop('net_amount')
        payout['fee_shares'] = payout.pop('fee_amount')
        payout.pop('asset')
        result = self._submit(item)
        self.assertEqual(result['error'], 'payout_not_prepared')

    def test_business_mismatch_rejected(self):
        item = self._prepared_item()
        item.blockchain_data['bsc_payout']['business'] = '0x' + '99' * 20
        result = self._submit(item)
        self.assertEqual(result['error'], 'payout_not_prepared')


@override_settings(BSC_PAYROLL_VAULT_ADDRESS=PAYROLL_VAULT)
class SettledAmountDecodeTests(SimpleTestCase):
    """PaidOut is decoded by TOPIC + fixed data offsets, and both moved in v2.

    This decoder fails SILENTLY when its offsets drift — it reads a wrong word,
    finds a redeem flag that isn't 1, and returns the nominal wage. The v1
    version did exactly that for its whole life: its comment said "four
    remaining values" but `signer` is not indexed, so every redeemed payout was
    recorded at nominal instead of the USDT that actually landed. Pin the
    layout against the contract, not against a sentence.
    """

    TOPIC = ('0x' + keccak(
        text='PaidOut(address,address,bytes32,address,uint8,uint256,uint256,bool,uint256)'
    ).hex())

    def _receipt(self, *, redeemed: bool, usdt_out: int, asset: int = 0):
        def word(v):
            return format(int(v), 'x').rjust(64, '0')
        # signer · asset · netAmount · feeAmount · redeemedToUsdt · usdtOut
        data = '0x' + (SIGNER_ADDR[2:].rjust(64, '0') + word(asset) + word(100 * WAD)
                       + word(WAD) + word(1 if redeemed else 0) + word(usdt_out))
        return {'logs': [{'address': PAYROLL_VAULT, 'topics': [self.TOPIC], 'data': data}]}

    def _decode(self, receipt):
        from payroll import tasks
        item = SimpleNamespace(internal_id='item42', net_amount=Decimal('100'))
        with mock.patch('cusd_plus.tasks._rpc', return_value=receipt):
            return tasks._decode_settled_amount('0x' + 'ab' * 32, item)

    def test_topic_matches_the_compiled_contract(self):
        # forge inspect ConfioPayrollVault events → this exact hash.
        self.assertEqual(
            self.TOPIC,
            '0x5b873c111d662ad7ad92551f91901eec7d9ece92d3306fde06a9c76c49ea2549')

    def test_redeemed_payout_records_the_usdt_that_actually_landed(self):
        # 99.5 USDT against a nominal 100 — the slippage the field exists for.
        settled = self._decode(self._receipt(redeemed=True, usdt_out=995 * WAD // 10))
        self.assertEqual(settled, Decimal('99.500000'))

    def test_share_payout_records_the_nominal(self):
        self.assertEqual(self._decode(self._receipt(redeemed=False, usdt_out=0)),
                         Decimal('100'))

    def test_usdt_pool_payout_records_the_nominal(self):
        # asset=1 never redeems, so the wage moved exactly as promised.
        self.assertEqual(
            self._decode(self._receipt(redeemed=False, usdt_out=0, asset=1)),
            Decimal('100'))

    def test_a_v1_shaped_log_is_ignored_rather_than_misread(self):
        """The old topic must not match: decoding a v1 log with v2 offsets
        would read past the data and invent a settled amount."""
        v1_topic = ('0x' + keccak(
            text='PaidOut(address,address,bytes32,address,uint256,uint256,bool,uint256)'
        ).hex())
        self.assertNotEqual(v1_topic, self.TOPIC)
        receipt = self._receipt(redeemed=True, usdt_out=995 * WAD // 10)
        receipt['logs'][0]['topics'] = [v1_topic]
        self.assertEqual(self._decode(receipt), Decimal('100'))


class PendingItemsPermissionTests(SimpleTestCase):
    """The list HomeScreen turns into a Pagar button must not be wider than
    the permission that button needs.

    It used to filter on BusinessEmployee.is_active alone, so every cashier
    of every business the user works at got the payroll card — and the app
    will not even let an owner APPOINT a cashier as a payroll delegate. They
    tapped Pagar and got permission_denied.
    """

    def _biz_ids_for(self, rows):
        """The delegate-branch filter, exercised over fake employee rows."""
        from users.jwt_context import check_role_permission
        out = []
        for emp in rows:
            overrides = emp.permissions or {}
            if 'send_funds' in overrides and not overrides['send_funds']:
                continue
            if check_role_permission(emp.role, 'send_funds'):
                out.append(emp.business_id)
        return out

    def _emp(self, business_id, role, permissions=None):
        return SimpleNamespace(business_id=business_id, role=role,
                               permissions=permissions)

    def test_cashier_is_excluded(self):
        self.assertEqual(self._biz_ids_for([self._emp(1, 'cashier')]), [])

    def test_manager_and_admin_are_included(self):
        rows = [self._emp(1, 'manager'), self._emp(2, 'admin')]
        self.assertEqual(self._biz_ids_for(rows), [1, 2])

    def test_an_explicit_revocation_wins_over_the_role(self):
        # Revoking send_funds on one manager must remove their card too —
        # the role still says yes, the override says no.
        rows = [self._emp(1, 'manager', {'send_funds': False})]
        self.assertEqual(self._biz_ids_for(rows), [])

    def test_an_explicit_true_does_not_widen_a_cashier(self):
        # Deny-only, matching jwt_context: an explicit True is left to the
        # role matrix, so this must NOT promote a cashier.
        rows = [self._emp(1, 'cashier', {'send_funds': True})]
        self.assertEqual(self._biz_ids_for(rows), [])

    def test_only_the_payable_businesses_survive(self):
        rows = [self._emp(1, 'cashier'), self._emp(2, 'manager'),
                self._emp(3, 'admin', {'send_funds': False})]
        self.assertEqual(self._biz_ids_for(rows), [2])

    def test_the_delegate_screen_agrees_about_cashiers(self):
        # PayrollDelegatesManageScreen filters eligible delegates with
        # `role !== 'cashier'`. If the role matrix ever granted a cashier
        # send_funds, that screen and this gate would disagree about who can
        # pay payroll.
        from users.jwt_context import check_role_permission
        self.assertFalse(check_role_permission('cashier', 'send_funds'))
        for role in ('admin', 'manager', 'owner'):
            self.assertTrue(check_role_permission(role, 'send_funds'), role)
