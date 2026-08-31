"""
BSC send flow (send/bsc_flow.py) — the properties that make sponsored
dollar sends safe:

  1. call-shape selection follows the eligibility matrix (A: cUSD+ transfer
     to eligible internal recipients; B: atomic redeem-to-USDT for
     ineligible/external; C: legacy raw USDT fallback) — and explicit cUSD+
     still follows recipient eligibility (D: transfer to an eligible friend,
     fee-free unwrap to cUSD for an ineligible friend, fee-bearing exit for
     an external address; E: BEP-20 CONFIO, never dollar-funded);
  2. a recipient without a registered bsc_address BLOCKS the send and
     nudges the recipient (the coverage-cold-start adoption loop);
  3. the submit-side validator accepts only the stored single-call shapes
     with the stored recipient — calldata tampering is structurally
     impossible.

Runs without a database (ORM + RPC mocked, house style):
    myvenv/bin/python manage.py test send.tests
"""
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from cusd_plus.sponsor_7702 import (
    PolicyError,
    SEL_REDEEM_TO_USDT,
    SEL_APPROVE,
    SEL_TRANSFER,
    SEL_UNWRAP_TO_CUSD,
    SEL_WRAP_CUSD,
    USDT_BSC,
)
from send import bsc_flow

VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'
CUSD = '0x' + '66' * 20
CONFIO_TOKEN = '0x' + 'cc' * 20
SENDER = '0x' + '11' * 20
RECIPIENT = '0x' + '22' * 20
WAD = 10 ** 18


def _jwt_ctx():
    return {'account_type': 'personal', 'account_index': 0}


def _sender_user(uid=1):
    account = SimpleNamespace(bsc_address=SENDER, business=None)
    accounts = mock.Mock()
    accounts.filter.return_value.first.return_value = account
    return SimpleNamespace(
        id=uid, accounts=accounts, phone_number='584121234567',
        get_full_name=lambda: 'Sender Person', username='sender', email='s@x.co',
    )


def _recipient_resolution(user=None, business=None, addr=RECIPIENT, err=None):
    return mock.patch.object(
        bsc_flow, '_resolve_recipient', return_value=(user, business, addr, err))


def _recipient_user(eligible_country='VE', uid=2):
    return SimpleNamespace(
        id=uid, phone_country=eligible_country, phone_number='573001112233',
        get_full_name=lambda: 'Recipient Person', username='rcpt', email='r@x.co',
    )


@override_settings(
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    CUSD_VAULT_ADDRESS=CUSD,
    BSC_SEND_ENABLED=True,
)
class PrepareCallShapeTests(SimpleTestCase):
    """The A/B/C matrix, exercised with mocked balances + ORM."""

    def _prepare(self, amount='10', shares_value=100 * WAD, cusd=0, usdt=0,
                 recipient_user=None, recipient_business=None,
                 recipient_addr=RECIPIENT, token='', locked_recipient_addr=None):
        captured = {}

        def _create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(id=7, internal_id='sid123', **kwargs)

        pps = 11 * WAD // 10  # pPlus = $1.10
        with _recipient_resolution(recipient_user, recipient_business, recipient_addr), \
             mock.patch.object(
                 bsc_flow,
                 '_lock_internal_recipient_account',
                 return_value=SimpleNamespace(
                     bsc_address=locked_recipient_addr or recipient_addr,
                 ),
             ), \
             mock.patch('cusd_plus.vault.p_plus_wad', return_value=pps), \
             mock.patch('cusd_plus.vault.last_oracle_price_wad', return_value=105 * WAD // 100), \
             mock.patch('cusd_plus.vault.current_oracle_price_wad', return_value=106 * WAD // 100), \
             mock.patch('cusd_plus.vault.erc20_balance_raw',
                        side_effect=lambda token, _holder: (
                            cusd if token.lower() == CUSD.lower()
                            else (shares_value * WAD) // pps
                        )), \
             mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=usdt), \
             mock.patch('send.bsc_flow.transaction.atomic'), \
             mock.patch('send.models.SendTransaction.objects') as objs:
            objs.filter.return_value.first.return_value = None
            objs.create.side_effect = _create
            result = bsc_flow.prepare_bsc_send(
                _sender_user(), _jwt_ctx(), amount,
                recipient_user_id='2', token=token)
        return result, captured, pps

    def test_case_a_eligible_recipient_gets_vault_transfer(self):
        result, row, pps = self._prepare(recipient_user=_recipient_user('VE'))
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertEqual(call['to'], VAULT.lower())
        self.assertTrue(call['data'][2:].startswith(SEL_TRANSFER))
        # recipient word pinned
        self.assertEqual(call['data'][10:74], RECIPIENT[2:].lower().rjust(64, '0'))
        self.assertEqual(result['token_type'], 'CUSD_PLUS')
        self.assertEqual(json.loads(row['bsc_calls_json'])['kind'], 'send_cusd_plus')
        # $10 at pPlus $1.10 → floor(10e18*1e18/1.1e18) shares
        shares = int(call['data'][74:138], 16)
        self.assertEqual(shares, (10 * WAD * WAD) // pps)

    def test_case_b_ineligible_recipient_gets_fee_free_cusd_unwrap(self):
        result, row, _ = self._prepare(recipient_user=_recipient_user('US'))
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertEqual(call['to'], VAULT.lower())
        self.assertTrue(call['data'][2:].startswith(SEL_UNWRAP_TO_CUSD))
        # minOut = amount * 0.995
        min_out = int(call['data'][74:138], 16)
        self.assertEqual(min_out, (10 * WAD * 9950) // 10000)
        self.assertEqual(call['data'][138:202], RECIPIENT[2:].lower().rjust(64, '0'))
        self.assertEqual(result['token_type'], 'CUSD')
        self.assertEqual(json.loads(row['bsc_calls_json'])['kind'], 'send_unwrap_cusd')

    def test_case_b_external_address_gets_atomic_redeem(self):
        result, _, _ = self._prepare(recipient_user=None)
        self.assertTrue(result['success'], result)
        self.assertTrue(result['calls'][0]['data'][2:].startswith(SEL_REDEEM_TO_USDT))

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_external_plus_send_treats_entered_amount_as_gross(self):
        """A $10 entry burns a $10 gross position and delivers $9.91.

        It must not silently debit ~$10.09 to make the recipient receive $10;
        that was the legacy fee-on-top behavior.
        """
        net = 9_910_000_000_000_000_000
        with mock.patch(
            'cusd_plus.cusd_vault.preview_redeem_wei',
            side_effect=lambda gross: SimpleNamespace(
                gross_wei=gross,
                fee_wei=gross - (gross * 9_910 // 10_000),
                net_wei=gross * 9_910 // 10_000,
                fee_bps=90,
            ),
        ):
            result, _, pps = self._prepare('10', recipient_user=None)
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        shares = int(call['data'][10:74], 16)
        min_out = int(call['data'][74:138], 16)
        # At the mocked $1 oracle, this share amount represents the requested
        # $10 gross (allowing only the vault's integer-floor dust).
        self.assertLessEqual(shares, -(-10 * WAD * WAD // pps) + 1)
        self.assertLess(min_out, 10 * WAD)
        self.assertEqual(min_out, net * bsc_flow.REDEEM_MIN_OUT_BPS // 10_000)
        # The exact share preview may be one wei above the entered display
        # amount because the redeem path floors twice. The receipt reports
        # the chain-authoritative values, and they must reconcile exactly.
        self.assertLessEqual(abs(Decimal(result['gross_amount']) - Decimal('10')), Decimal('0.000000000000000001'))
        self.assertEqual(result['net_amount'], '9.91')
        self.assertEqual(
            Decimal(result['fee_amount']) + Decimal(result['net_amount']),
            Decimal(result['gross_amount']),
        )
        self.assertEqual(result['fee_bps'], 90)

    def test_case_c_usdt_fallback(self):
        result, row, _ = self._prepare(
            shares_value=0, usdt=100 * WAD, recipient_user=_recipient_user('VE'))
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertEqual(call['to'], USDT_BSC)
        self.assertTrue(call['data'][2:].startswith(SEL_TRANSFER))
        self.assertEqual(int(call['data'][74:138], 16), 10 * WAD)
        self.assertEqual(json.loads(row['bsc_calls_json'])['kind'], 'send_usdt')

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_transient_raw_usdt_cannot_bypass_live_perimeter(self):
        result, _, _ = self._prepare(
            shares_value=0, usdt=100 * WAD, recipient_user=_recipient_user('VE'))
        self.assertEqual(result['error'], 'conversion_pending')

    def test_cusd_to_ineligible_friend_is_fee_free_transfer(self):
        result, row, _ = self._prepare(
            shares_value=0, cusd=100 * WAD,
            recipient_user=_recipient_user('US'),
        )
        self.assertTrue(result['success'], result)
        self.assertEqual(len(result['calls']), 1)
        self.assertEqual(result['calls'][0]['to'], CUSD.lower())
        self.assertTrue(result['calls'][0]['data'][2:].startswith(SEL_TRANSFER))
        meta = json.loads(row['bsc_calls_json'])
        self.assertEqual(meta['kind'], 'send_cusd')
        bsc_flow._validate_send_batch(
            result['calls'], SimpleNamespace(recipient_address=RECIPIENT), meta)

    def test_cusd_to_eligible_friend_wraps_fee_free_atomically(self):
        result, row, _ = self._prepare(
            shares_value=0, cusd=100 * WAD,
            recipient_user=_recipient_user('VE'),
        )
        self.assertTrue(result['success'], result)
        self.assertEqual(len(result['calls']), 2)
        self.assertEqual(result['calls'][0]['to'], CUSD.lower())
        self.assertTrue(result['calls'][0]['data'][2:].startswith(SEL_APPROVE))
        self.assertEqual(result['calls'][1]['to'], VAULT.lower())
        self.assertTrue(result['calls'][1]['data'][2:].startswith(SEL_WRAP_CUSD))
        min_out = int(result['calls'][1]['data'][74:138], 16)
        self.assertEqual(
            min_out,
            bsc_flow._min_usdy_out(10 * WAD, 106 * WAD // 100),
        )
        meta = json.loads(row['bsc_calls_json'])
        self.assertEqual(meta['kind'], 'send_wrap_cusd')
        bsc_flow._validate_send_batch(
            result['calls'], SimpleNamespace(recipient_address=RECIPIENT), meta)

    def test_insufficient_balance(self):
        result, _, _ = self._prepare(
            shares_value=0, usdt=0, recipient_user=_recipient_user('VE'))
        self.assertEqual(result['error'], 'insufficient_balance')

    def test_recipient_without_address_blocks_and_nudges(self):
        recipient = _recipient_user('VE')
        with _recipient_resolution(recipient, None, None), \
             mock.patch.object(bsc_flow, '_notify_recipient_needs_app') as nudge:
            result = bsc_flow.prepare_bsc_send(
                _sender_user(), _jwt_ctx(), '10', recipient_user_id='2')
        self.assertEqual(result['error'], 'recipient_no_bsc_address')
        nudge.assert_called_once()

    def test_refuses_to_snapshot_an_address_changed_during_prepare(self):
        result, row, _ = self._prepare(
            recipient_user=_recipient_user('VE'),
            locked_recipient_addr='0x' + ('9' * 40),
        )
        self.assertEqual(result['error'], 'recipient_address_changed')
        self.assertEqual(row, {})

    @override_settings(BSC_SEND_ENABLED=False)
    def test_dark_flag_blocks(self):
        result, _, _ = self._prepare(recipient_user=_recipient_user('VE'))
        self.assertEqual(result['error'], 'bsc_send_disabled')

    # ── explicit token shapes (D/E) ─────────────────────────────────────

    def test_explicit_cusd_plus_to_external_still_pays_exit_fee(self):
        result, row, pps = self._prepare(recipient_user=None, token='CUSD_PLUS')
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertEqual(call['to'], VAULT.lower())
        self.assertTrue(call['data'][2:].startswith(SEL_REDEEM_TO_USDT))
        self.assertEqual(result['token_type'], 'USDT')
        self.assertEqual(json.loads(row['bsc_calls_json'])['kind'], 'send_redeem')

    def test_explicit_cusd_plus_cannot_bypass_ineligible_routing(self):
        result, _, _ = self._prepare(
            recipient_user=_recipient_user('US'), token='CUSD_PLUS')
        self.assertTrue(result['success'], result)
        self.assertTrue(result['calls'][0]['data'][2:].startswith(SEL_UNWRAP_TO_CUSD))
        self.assertEqual(result['token_type'], 'CUSD')

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    def test_explicit_cusd_plus_cannot_spend_transient_usdt(self):
        result, _, _ = self._prepare(
            shares_value=0, usdt=100 * WAD, token='CUSD_PLUS')
        self.assertEqual(result['error'], 'conversion_pending')

    def test_mixed_balance_can_send_to_ineligible_friend(self):
        result, row, _ = self._prepare(
            amount='10', shares_value=8 * WAD, cusd=4 * WAD,
            recipient_user=_recipient_user('US'))
        self.assertTrue(result['success'], result)
        self.assertEqual(len(result['calls']), 2)
        meta = json.loads(row['bsc_calls_json'])
        self.assertEqual(meta['kind'], 'send_mixed_cusd')
        bsc_flow._validate_send_batch(
            result['calls'],
            SimpleNamespace(recipient_address=RECIPIENT, sender_address=SENDER),
            meta,
        )

    def test_mixed_external_exit_normalizes_then_charges_one_fee(self):
        with mock.patch(
            'cusd_plus.cusd_vault.preview_redeem_wei',
            return_value=SimpleNamespace(
                gross_wei=10 * WAD,
                fee_wei=90_000_000_000_000_000,
                net_wei=9_910_000_000_000_000_000,
                fee_bps=90,
            ),
        ):
            result, row, _ = self._prepare(
                amount='10', shares_value=8 * WAD, cusd=4 * WAD,
                recipient_user=None)
        self.assertTrue(result['success'], result)
        self.assertEqual(len(result['calls']), 2)
        meta = json.loads(row['bsc_calls_json'])
        self.assertEqual(meta['kind'], 'send_mixed_cusd_redeem')

    @override_settings(BSC_CONFIO_TOKEN_ADDRESS=CONFIO_TOKEN)
    def test_case_e_confio_transfer(self):
        # The generic erc20 mock serves the CONFIO read here: ~90.9 tokens.
        result, row, _ = self._prepare(recipient_user=None, token='CONFIO')
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertEqual(call['to'], CONFIO_TOKEN.lower())
        self.assertTrue(call['data'][2:].startswith(SEL_TRANSFER))
        self.assertEqual(call['data'][10:74], RECIPIENT[2:].lower().rjust(64, '0'))
        # amount is a token COUNT: 10 CONFIO → 10e18 wei, no price math.
        self.assertEqual(int(call['data'][74:138], 16), 10 * WAD)
        self.assertEqual(result['token_type'], 'CONFIO')
        self.assertEqual(json.loads(row['bsc_calls_json'])['kind'], 'send_confio')

    @override_settings(BSC_CONFIO_TOKEN_ADDRESS=CONFIO_TOKEN)
    def test_case_e_insufficient_confio(self):
        result, _, _ = self._prepare(
            shares_value=0, usdt=100 * WAD, token='CONFIO')
        self.assertEqual(result['error'], 'insufficient_balance')

    @override_settings(BSC_CONFIO_TOKEN_ADDRESS=None)
    def test_case_e_unconfigured_token_blocks(self):
        result, _, _ = self._prepare(recipient_user=None, token='CONFIO')
        self.assertEqual(result['error'], 'confio_not_configured')

    def test_unknown_token_rejected(self):
        result, _, _ = self._prepare(recipient_user=None, token='DOGE')
        self.assertEqual(result['error'], 'unsupported_token')

    # ── MAX dust tolerance ──────────────────────────────────────────────
    # The mint path floors twice on-chain, so a $2.99 deposit reads back as
    # exactly 2.99 in every float layer while being wei-short of 2.99e18.
    # MAX re-requests 2.99 → that's a full-position send, never an overdraft.

    def _prepare_raw(self, amount, shares_raw, usdt=0, token='',
                     pps=11 * WAD // 10, recipient_user=None):
        captured = {}

        def _create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(id=7, internal_id='sid123', **kwargs)

        with _recipient_resolution(recipient_user, None, RECIPIENT), \
             mock.patch.object(
                 bsc_flow,
                 '_lock_internal_recipient_account',
                 return_value=SimpleNamespace(bsc_address=RECIPIENT),
             ), \
             mock.patch('cusd_plus.vault.p_plus_wad', return_value=pps), \
             mock.patch('cusd_plus.vault.last_oracle_price_wad', return_value=WAD), \
             mock.patch('cusd_plus.vault.erc20_balance_raw', return_value=shares_raw), \
             mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=usdt), \
             mock.patch('send.bsc_flow.transaction.atomic'), \
             mock.patch('send.models.SendTransaction.objects') as objs:
            objs.filter.return_value.first.return_value = None
            objs.create.side_effect = _create
            result = bsc_flow.prepare_bsc_send(
                _sender_user(), _jwt_ctx(), amount,
                recipient_user_id='2', token=token)
        return result, captured

    def test_max_on_dust_short_position_redeems_full_position(self):
        pps = 11 * WAD // 10
        amount_wei = 299 * WAD // 100
        shares_raw = (amount_wei * WAD) // pps - 1  # 1 share-wei short of 2.99
        result, _ = self._prepare_raw('2.99', shares_raw, pps=pps)
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertTrue(call['data'][2:].startswith(SEL_REDEEM_TO_USDT))
        # clamped to the ENTIRE position, not the (unaffordable) ideal shares
        self.assertEqual(int(call['data'][10:74], 16), shares_raw)

    def test_max_explicit_cusd_plus_dust_short_redeems_full_position(self):
        pps = 11 * WAD // 10
        amount_wei = 299 * WAD // 100
        shares_raw = (amount_wei * WAD) // pps - 1
        result, _ = self._prepare_raw('2.99', shares_raw, pps=pps, token='CUSD_PLUS')
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertTrue(call['data'][2:].startswith(SEL_REDEEM_TO_USDT))
        self.assertEqual(int(call['data'][10:74], 16), shares_raw)

    def test_max_usdt_dust_short_sends_full_wallet_balance(self):
        usdt_raw = 299 * WAD // 100 - 1
        result, _ = self._prepare_raw('2.99', shares_raw=0, usdt=usdt_raw)
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertEqual(call['to'], USDT_BSC)
        self.assertEqual(int(call['data'][74:138], 16), usdt_raw)

    @override_settings(BSC_CONFIO_TOKEN_ADDRESS=CONFIO_TOKEN)
    def test_max_confio_dust_short_sends_full_balance(self):
        confio_raw = 10 * WAD - 1
        result, _ = self._prepare_raw('10', shares_raw=confio_raw, token='CONFIO')
        self.assertTrue(result['success'], result)
        self.assertEqual(int(result['calls'][0]['data'][74:138], 16), confio_raw)

    # ── Ondo's 1.00 USDT redemption floor ───────────────────────────────
    # Verified against BSC mainnet on 2026-08-01 with the live vault state
    # below: redeeming 998214106173270802 shares yields exactly 10**18 USDT
    # and succeeds, one share-wei less yields 10**18 - 1 and reverts with
    # Ondo's 0xd0022dba. The floor division picked the losing side.

    PROD_PPS = 1001789088949639830
    PROD_SHARES = 998456587689402305   # a position worth $1.00024
    ONDO_OK_SHARES = 998214106173270802

    def test_redeem_rounds_up_to_clear_ondo_minimum(self):
        result, _ = self._prepare_raw(
            '1', self.PROD_SHARES, pps=self.PROD_PPS)
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertTrue(call['data'][2:].startswith(SEL_REDEEM_TO_USDT))
        shares = int(call['data'][10:74], 16)
        self.assertEqual(shares, self.ONDO_OK_SHARES)
        # the floored value is what production sent, and it reverts
        self.assertEqual(shares - 1, (WAD * WAD) // self.PROD_PPS)

    def test_redeem_under_one_dollar_refused_not_stranded(self):
        # Ondo cannot serve it at any share count, so refuse at prepare
        # rather than build a batch that only fails in simulation.
        result, _ = self._prepare_raw('0.5', 10 * WAD)
        self.assertEqual(result['error'], 'redeem_below_minimum')

    def test_eligible_transfer_still_floors(self):
        # The rounding-up is redeem-only: a share TRANSFER must never move
        # more of the sender's position than the value they asked for.
        result, _ = self._prepare_raw(
            '1', self.PROD_SHARES, pps=self.PROD_PPS,
            recipient_user=_recipient_user('VE'))
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertTrue(call['data'][2:].startswith(SEL_TRANSFER))
        self.assertEqual(int(call['data'][74:138], 16),
                         (WAD * WAD) // self.PROD_PPS)

    # ── Codex audit 2026-08-01 ──────────────────────────────────────────
    # The guard used shares * pPlus / WAD, but the chain floors TWICE
    # (shares -> USDY at the oracle price, then USDY -> USDT), so that proxy
    # is an OVER-estimate and could approve a redemption Ondo rejects.

    def test_guard_uses_the_exact_two_floor_preview(self):
        # A price where the proxy says exactly 1e18 but the truth is a wei short.
        pps, oracle = WAD, 1_050_000_000_000_000_000
        shares = WAD
        proxy = (shares * pps) // WAD
        from cusd_plus.vault import redeem_usdt_out
        truth = redeem_usdt_out(shares, pps, oracle)
        self.assertEqual(proxy, WAD)          # the old guard would pass this
        self.assertEqual(truth, WAD - 1)      # Ondo would reject it
        self.assertLess(truth, proxy)

    def test_redeem_below_minimum_falls_through_to_usdt(self):
        # $0.50 of savings but plenty of raw USDT: refusing outright stranded
        # a user who could obviously be served by branch C.
        result, _ = self._prepare_raw('0.5', shares_raw=WAD // 2, usdt=10 * WAD)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['token_type'], 'USDT')
        self.assertEqual(result['calls'][0]['to'], USDT_BSC)

    def test_redeem_below_minimum_with_no_usdt_still_refuses(self):
        result, _ = self._prepare_raw('0.5', shares_raw=WAD // 2, usdt=0)
        self.assertEqual(result['error'], 'redeem_below_minimum')

    def test_shortfall_beyond_dust_still_refuses(self):
        pps = 11 * WAD // 10
        amount_wei = 299 * WAD // 100
        short = amount_wei - 2 * bsc_flow.MAX_SEND_DUST_WEI
        shares_raw = (short * WAD) // pps
        result, _ = self._prepare_raw('2.99', shares_raw, pps=pps)
        self.assertEqual(result['error'], 'redeem_below_minimum')


class SubmitValidatorTests(SimpleTestCase):
    """_validate_send_batch: the stored call must equal the canonical intent
    (kind + token + recipient + units + min_out) rebuilt byte-for-byte —
    tampering the AMOUNT, recipient, token, or shape is all structurally
    rejected."""

    def _meta(self, calls, kind, token, recipient=RECIPIENT, units=10 * WAD,
              min_out=None):
        return {'calls': calls, 'kind': kind, 'token': token,
                'recipient': recipient, 'units': str(units),
                'min_out': (str(min_out) if min_out is not None else None)}

    def _tx(self, recipient=RECIPIENT, token_type='USDT'):
        return SimpleNamespace(recipient_address=recipient, token_type=token_type)

    def _transfer_call(self, to=None, recipient=RECIPIENT, amount=10 * WAD):
        data = ('0x' + SEL_TRANSFER + recipient[2:].lower().rjust(64, '0')
                + format(amount, 'x').rjust(64, '0'))
        return {'to': (to or USDT_BSC), 'value': '0', 'data': data}

    def _redeem_call(self, shares=10 * WAD, min_out=9 * WAD, recipient=RECIPIENT, to=VAULT):
        data = ('0x' + SEL_REDEEM_TO_USDT
                + format(shares, 'x').rjust(64, '0')
                + format(min_out, 'x').rjust(64, '0')
                + recipient[2:].lower().rjust(64, '0'))
        return {'to': to.lower(), 'value': '0', 'data': data}

    @override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT)
    def test_valid_transfer_passes(self):
        call = self._transfer_call()
        bsc_flow._validate_send_batch(
            [call], self._tx(), self._meta([call], 'send_usdt', USDT_BSC))

    @override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT)
    def test_valid_redeem_passes(self):
        call = self._redeem_call()
        bsc_flow._validate_send_batch(
            [call], self._tx(),
            self._meta([call], 'send_redeem', VAULT, min_out=9 * WAD))

    @override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT)
    def test_amount_tamper_rejected(self):
        # The stored call moves MORE than the canonical units → rebuild differs.
        call = self._transfer_call(amount=20 * WAD)
        with self.assertRaises(PolicyError):
            bsc_flow._validate_send_batch(
                [call], self._tx(), self._meta([call], 'send_usdt', USDT_BSC, units=10 * WAD))

    @override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT)
    def test_redeem_min_out_tamper_rejected(self):
        # A lowered min_out in the calldata (recipient could lose value) fails.
        call = self._redeem_call(min_out=1)
        with self.assertRaises(PolicyError):
            bsc_flow._validate_send_batch(
                [call], self._tx(), self._meta([call], 'send_redeem', VAULT, min_out=9 * WAD))

    @override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT)
    def test_recipient_tamper_rejected(self):
        # calldata recipient differs from the canonical (== row) recipient.
        evil = self._transfer_call(recipient='0x' + '99' * 20)
        with self.assertRaises(PolicyError):
            bsc_flow._validate_send_batch(
                [evil], self._tx(), self._meta([evil], 'send_usdt', USDT_BSC))

    @override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT)
    def test_row_recipient_mismatch_rejected(self):
        # canonical recipient must equal the SendTransaction row's recipient.
        call = self._transfer_call()
        with self.assertRaises(PolicyError):
            bsc_flow._validate_send_batch(
                [call], self._tx(recipient='0x' + '99' * 20),
                self._meta([call], 'send_usdt', USDT_BSC))

    @override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT)
    def test_foreign_destination_rejected(self):
        call = self._transfer_call(to='0x' + 'ab' * 20)
        with self.assertRaises(PolicyError):
            bsc_flow._validate_send_batch(
                [call], self._tx(), self._meta([call], 'send_usdt', '0x' + 'ab' * 20))

    @override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT)
    def test_unknown_kind_rejected(self):
        call = self._transfer_call()
        with self.assertRaises(PolicyError):
            bsc_flow._validate_send_batch(
                [call], self._tx(), self._meta([call], 'send_bogus', USDT_BSC))

    @override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT)
    def test_multi_call_rejected(self):
        call = self._transfer_call()
        with self.assertRaises(PolicyError):
            bsc_flow._validate_send_batch(
                [call, call], self._tx(), self._meta([call, call], 'send_usdt', USDT_BSC))

    @override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT,
                       BSC_CONFIO_TOKEN_ADDRESS=CONFIO_TOKEN)
    def test_confio_row_accepts_only_the_confio_token(self):
        good = self._transfer_call(to=CONFIO_TOKEN)
        bsc_flow._validate_send_batch(
            [good], self._tx(token_type='CONFIO'),
            self._meta([good], 'send_confio', CONFIO_TOKEN))
        # A send_confio row whose token is USDT is rejected (kind pins token).
        evil = self._transfer_call(to=USDT_BSC)
        with self.assertRaises(PolicyError):
            bsc_flow._validate_send_batch(
                [evil], self._tx(token_type='CONFIO'),
                self._meta([evil], 'send_confio', USDT_BSC))

    @override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT,
                       BSC_CONFIO_TOKEN_ADDRESS=CONFIO_TOKEN)
    def test_non_confio_kind_rejects_the_confio_token(self):
        call = self._transfer_call(to=CONFIO_TOKEN)
        with self.assertRaises(PolicyError):
            bsc_flow._validate_send_batch(
                [call], self._tx(), self._meta([call], 'send_usdt', CONFIO_TOKEN))


class RecipientResolutionTests(TestCase):
    def test_invalid_evm_address_rejected(self):
        _, _, _, err = bsc_flow._resolve_recipient(None, None, '0x1234')
        self.assertEqual(err, 'invalid_recipient_address')

    def test_nothing_supplied(self):
        _, _, _, err = bsc_flow._resolve_recipient(None, None, None)
        self.assertEqual(err, 'recipient_required')

    def test_retired_raw_bsc_address_rejected(self):
        from users.models import RetiredWalletAddress

        RetiredWalletAddress.objects.create(
            chain=RetiredWalletAddress.CHAIN_BSC,
            address=RECIPIENT.upper(),
        )
        _, _, _, err = bsc_flow._resolve_recipient(None, None, RECIPIENT)
        self.assertEqual(err, 'retired_recipient_address')
        self.assertEqual(
            RetiredWalletAddress.objects.get().address,
            RECIPIENT.lower(),
        )


@override_settings(
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    CUSD_VAULT_ADDRESS=CUSD,
    BSC_SEND_ENABLED=True,
)
class IdempotencyTests(SimpleTestCase):
    """A reused idempotency key REPLAYS only when the request matches the
    stored row; different params → conflict, never the stale calls (P3)."""

    def _existing(self, amount='10', token_type='USDT', recipient_addr=RECIPIENT, ruid=2):
        return SimpleNamespace(
            id=42, internal_id='old123',
            bsc_calls_json=json.dumps({'calls': [{'to': USDT_BSC, 'value': '0', 'data': '0x'}],
                                       'kind': 'send_usdt'}),
            amount=Decimal(amount), recipient_address=recipient_addr,
            recipient_user_id=ruid, recipient_business_id=None, token_type=token_type)

    def _prepare(self, existing, amount='10', token='', recipient_addr=RECIPIENT):
        with _recipient_resolution(_recipient_user('VE'), None, recipient_addr), \
             mock.patch('cusd_plus.vault.p_plus_wad', return_value=11 * WAD // 10), \
             mock.patch('cusd_plus.vault.erc20_balance_raw', return_value=0), \
             mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=1000 * WAD), \
             mock.patch('send.models.SendTransaction.objects') as objs:
            objs.filter.return_value.first.return_value = existing
            objs.create.side_effect = AssertionError('idempotent path must not create')
            return bsc_flow.prepare_bsc_send(
                _sender_user(), _jwt_ctx(), amount,
                recipient_user_id='2', token=token, idempotency_key='k1')

    def test_same_params_replays(self):
        result = self._prepare(self._existing(amount='10'))
        self.assertTrue(result['success'], result)
        self.assertEqual(result['send_id'], 'old123')
        self.assertEqual(result['calls'], [{'to': USDT_BSC, 'value': '0', 'data': '0x'}])

    def test_different_amount_conflicts(self):
        result = self._prepare(self._existing(amount='10'), amount='20')
        self.assertEqual(result['error'], 'idempotency_key_conflict')

    def test_different_recipient_conflicts(self):
        result = self._prepare(
            self._existing(recipient_addr='0x' + '99' * 20))
        self.assertEqual(result['error'], 'idempotency_key_conflict')

    def test_different_token_intent_conflicts(self):
        # stored a dollar (USDT) send; now an explicit CONFIO request.
        result = self._prepare(self._existing(token_type='USDT'), token='CONFIO')
        self.assertEqual(result['error'], 'idempotency_key_conflict')


class ConfirmTaskTests(SimpleTestCase):
    """confirm_bsc_send settles the row, writes both ledger sides for
    internal sends, and notifies both parties."""

    def _run(self, batch_status='confirmed', kind='send_cusd_plus'):
        from send import tasks as send_tasks
        s = SimpleNamespace(
            id=7, internal_id='sid', status='SUBMITTED',
            sender_user_id=1, sender_user=SimpleNamespace(id=1),
            sender_business=None, sender_business_id=None,
            recipient_user_id=2, recipient_user=SimpleNamespace(id=2),
            recipient_business=None, recipient_business_id=None,
            sender_address=SENDER, recipient_address=RECIPIENT,
            sender_display_name='Sender', recipient_display_name='Rcpt',
            sender_phone='', recipient_phone='', memo='',
            amount=Decimal('10'), token_type='CUSD_PLUS',
            transaction_hash='0x' + 'aa' * 32,
            save=mock.Mock(),
        )
        batch = SimpleNamespace(id=9, status=batch_status, tx_hash=s.transaction_hash,
                                kind=kind, source_id=s.id)
        with mock.patch('send.models.SendTransaction.objects') as sobjs, \
             mock.patch('blockchain.models.SponsoredBatch.objects') as bobjs, \
             mock.patch.object(send_tasks, '_account_for_bsc_address',
                               side_effect=lambda a: SimpleNamespace(addr=a)), \
             mock.patch.object(send_tasks, '_notify_send_parties') as notify:
            sobjs.get.return_value = s
            bobjs.get.return_value = batch
            send_tasks.confirm_bsc_send(7, 9)
        return s, notify

    def test_confirmed_sets_status_and_notifies(self):
        # The ledger row is NOT this task's job any more: the unified
        # transaction is written by SendTransaction's post_save signal, so a
        # cUSD+ send lands in the same history as every other rail rather
        # than in a second, savings-only ledger.
        s, notify = self._run('confirmed')
        self.assertEqual(s.status, 'CONFIRMED')
        notify.assert_called_once()

    def test_reverted_fails_and_stays_silent(self):
        s, notify = self._run('reverted')
        self.assertEqual(s.status, 'FAILED')
        notify.assert_not_called()

    def test_every_preparable_kind_can_settle(self):
        for kind in sorted(bsc_flow.BSC_SEND_KINDS):
            with self.subTest(kind=kind):
                s, _ = self._run('confirmed', kind=kind)
                self.assertEqual(s.status, 'CONFIRMED')

    def test_every_preparable_kind_is_crash_recoverable(self):
        from cusd_plus.tasks import _DOMAIN_CONFIRM_TASKS
        for kind in bsc_flow.BSC_SEND_KINDS:
            self.assertEqual(
                _DOMAIN_CONFIRM_TASKS.get(kind),
                'send.confirm_bsc_send',
                kind,
            )

    def test_one_live_batch_per_economic_send_is_a_db_constraint(self):
        from blockchain.models import SponsoredBatch
        constraint = next(
            c for c in SponsoredBatch._meta.constraints
            if c.name == 'cpsb_unique_active_send'
        )
        self.assertEqual(tuple(constraint.fields), ('source_id',))
        condition = str(constraint.condition)
        for kind in bsc_flow.BSC_SEND_KINDS:
            self.assertIn(kind, condition)
