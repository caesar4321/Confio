"""
The cUSD+ mint-side geo stack. External USDT reaches the same user address for
everyone; fee-capable clients route ineligible holders to cUSD, while both
legacy cUSD+ relay rails still enforce eligibility. These tests pin the
properties that keep the compatibility path safe:

  1. the gate itself (phone fails CLOSED, IP fails OPEN when unresolvable);
  2. cUSD+ mints are refused for ineligible users on both rails, while cUSD
     issuance and exits are not subject to the Ondo acquisition gate;
  3. the supporting flows agree: ramp orders no longer geo-refuse savings
     top-ups, sponsored batches carry the raw USDT transfer (the exit), and
     the arrival notification never promises a mint that won't happen.

Runs without a database:
    myvenv/bin/python manage.py test cusd_plus.tests.test_mint_geo_gate
"""
import time
from contextlib import nullcontext
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from cusd_plus import sponsor_7702
from cusd_plus.eligibility import (
    check_savings_mint_eligibility,
    check_stock_buy_eligibility,
)
from cusd_plus.tests.test_sponsor_7702 import (
    DELEGATE,
    USER,
    VAULT,
    ROUTER,
    STOCK,
    _approve_data,
    _call,
    _mint_data,
    _redeem_data,
    _stock_data,
    _wrap_data,
    _word,
)
from cusd_plus.tests.test_bnb_autoconvert_relay import SIGNER_ADDR, _legacy_tx

USDT = sponsor_7702.USDT_BSC


def _user(country, uid=1):
    return SimpleNamespace(is_authenticated=True, id=uid, phone_country=country)


def _info(user, meta=None):
    return SimpleNamespace(context=SimpleNamespace(user=user, META=meta or {}))


class EligibilityGateTests(SimpleTestCase):
    """check_savings_mint_eligibility — phone closed, IP open."""

    def test_blocked_phone_fails_closed_regardless_of_ip(self):
        self.assertFalse(check_savings_mint_eligibility(
            _user('US'), {'HTTP_CF_IPCOUNTRY': 'CO'}))

    def test_missing_phone_fails_closed(self):
        self.assertFalse(check_savings_mint_eligibility(_user(''), {}))
        self.assertFalse(check_savings_mint_eligibility(_user(None), {}))

    def test_blocked_ip_via_cloudflare_header(self):
        self.assertFalse(check_savings_mint_eligibility(
            _user('VE'), {'HTTP_CF_IPCOUNTRY': 'US'}))

    def test_eligible_phone_and_ip(self):
        self.assertTrue(check_savings_mint_eligibility(
            _user('VE'), {'HTTP_CF_IPCOUNTRY': 'CO'}))

    @override_settings(CUSD_PLUS_STOCK_BUY_BLOCKED_COUNTRIES=[])
    def test_colombia_allows_usdy_and_stock_purchases_when_overlay_is_empty(self):
        colombia = {'HTTP_CF_IPCOUNTRY': 'CO'}
        peru = {'HTTP_CF_IPCOUNTRY': 'PE'}

        self.assertTrue(check_savings_mint_eligibility(_user('CO'), colombia))
        self.assertTrue(check_stock_buy_eligibility(_user('CO'), peru))
        self.assertTrue(check_stock_buy_eligibility(_user('PE'), colombia))

    def test_unresolvable_ip_fails_open(self):
        # No header, no usable IP: get_country_for_ip returns None without
        # touching the DB (private/absent IPs short-circuit).
        self.assertTrue(check_savings_mint_eligibility(_user('VE'), {}))
        self.assertTrue(check_savings_mint_eligibility(
            _user('VE'), {'REMOTE_ADDR': '10.0.0.1'}))

    def test_resolver_crash_fails_open(self):
        with mock.patch('security.geo.get_country_for_ip',
                        side_effect=RuntimeError('boom')):
            self.assertTrue(check_savings_mint_eligibility(
                _user('VE'), {'HTTP_CF_IPCOUNTRY': 'CO'}))

    @override_settings(CUSD_PLUS_STOCK_BUY_BLOCKED_COUNTRIES=['BO'])
    def test_confio_stock_overlay_blocks_phone_or_ip_but_not_other_countries(self):
        self.assertFalse(check_stock_buy_eligibility(
            _user('BO'), {'HTTP_CF_IPCOUNTRY': 'PE'}))
        self.assertFalse(check_stock_buy_eligibility(
            _user('VE'), {'HTTP_CF_IPCOUNTRY': 'BO'}))
        self.assertTrue(check_stock_buy_eligibility(
            _user('VE'), {'HTTP_CF_IPCOUNTRY': 'PE'}))

    @override_settings(CUSD_PLUS_STOCK_BUY_BLOCKED_COUNTRIES=[])
    def test_ondo_ineligible_country_still_blocks_stock_buy(self):
        self.assertFalse(check_stock_buy_eligibility(
            _user('US'), {'HTTP_CF_IPCOUNTRY': 'CO'}))


@override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT)
class LegacyRelayGateTests(SimpleTestCase):
    """SubmitBscTransaction: mint gated, exits relay."""

    def setUp(self):
        cache.clear()

    def _submit(self, raw, user, info=None):
        from cusd_plus.schema import SubmitBscTransaction
        # The relay binds the recovered signer to the active account's
        # registered address; _legacy_tx signs with SIGNER_KEY. The business
        # permission gate is left unmocked on purpose — with no real JWT the
        # context resolves to None, which is the personal-account path.
        with mock.patch('cusd_plus.schema._active_bsc_address', return_value=SIGNER_ADDR):
            return SubmitBscTransaction.mutate(None, info or _info(user), raw)

    def _mint_raw(self, amount=2 * 10**18):
        return _legacy_tx(VAULT, 0, bytes.fromhex(_mint_data(amount=amount)[2:]))

    def test_mint_refused_for_blocked_phone(self):
        with mock.patch('cusd_plus.tasks._rpc') as rpc:
            res = self._submit(self._mint_raw(), _user('US', uid=11))
        self.assertFalse(res.success)
        self.assertEqual(res.error, 'mint_not_available')
        rpc.assert_not_called()

    def test_mint_refused_for_blocked_ip(self):
        info = _info(_user('VE', uid=12), meta={'HTTP_CF_IPCOUNTRY': 'US'})
        with mock.patch('cusd_plus.tasks._rpc') as rpc:
            res = self._submit(self._mint_raw(), None, info=info)
        self.assertEqual(res.error, 'mint_not_available')
        rpc.assert_not_called()

    def test_mint_relays_for_eligible_user(self):
        with mock.patch('cusd_plus.tasks._rpc', return_value='0xabc') as rpc:
            res = self._submit(self._mint_raw(), _user('VE', uid=13))
        self.assertTrue(res.success, res.error)
        rpc.assert_called_once()

    def test_exact_one_dollar_mint_stays_raw(self):
        with mock.patch('cusd_plus.tasks._rpc') as rpc, \
             mock.patch('cusd_plus.tasks.mark_saga_delivered_as_usdt') as close:
            res = self._submit(self._mint_raw(amount=10**18), _user('VE', uid=16))
        self.assertFalse(res.success)
        self.assertEqual(res.error, 'mint_below_redeemable_minimum')
        rpc.assert_not_called()
        close.assert_called_once_with(SIGNER_ADDR, 10**18)

    def test_one_micro_dollar_buffer_relays(self):
        amount = 10**18 + 10**12
        with mock.patch('cusd_plus.tasks._rpc', return_value='0xabc') as rpc:
            res = self._submit(self._mint_raw(amount=amount), _user('VE', uid=17))
        self.assertTrue(res.success, res.error)
        rpc.assert_called_once()

    def test_truncated_mint_calldata_is_rejected_cleanly(self):
        raw = _legacy_tx(
            VAULT, 0, bytes.fromhex(sponsor_7702.SEL_SUBSCRIBE_AND_MINT))
        with mock.patch('cusd_plus.tasks._rpc') as rpc:
            res = self._submit(raw, _user('VE', uid=18))
        self.assertFalse(res.success)
        self.assertEqual(res.error, 'bad_calldata')
        rpc.assert_not_called()

    def test_raw_usdt_transfer_relays_for_ineligible_user(self):
        # THE exit: a geo-blocked user moving arrived USDT out. Never gated.
        transfer = bytes.fromhex('a9059cbb') + b'\x00' * 64
        raw = _legacy_tx(USDT, 0, transfer)
        with mock.patch('cusd_plus.tasks._rpc', return_value='0xdef') as rpc:
            res = self._submit(raw, _user('US', uid=14))
        self.assertTrue(res.success, res.error)
        rpc.assert_called_once()

    def test_self_redeem_relays_for_ineligible_user(self):
        # Exit #2: redeeming an existing vault position is never geo-gated.
        # Recipient IS the signer — the self-redeem case the guard allows.
        raw = _legacy_tx(VAULT, 0, bytes.fromhex(_redeem_data(recipient=SIGNER_ADDR)[2:]))
        with mock.patch('cusd_plus.tasks._rpc', return_value='0xfee') as rpc:
            res = self._submit(raw, _user('US', uid=15))
        self.assertTrue(res.success, res.error)
        rpc.assert_called_once()


@override_settings(
    CUSD_PLUS_7702_ENABLED=True,
    CUSD_PLUS_BATCH_DELEGATE_ADDRESS=DELEGATE,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    BSC_CHAIN_ID=56,
)
class SponsoredRailGateTests(SimpleTestCase):
    """SponsorBscBatch: a batch carrying a mint consults the gate; a
    redeem-only batch does not. Refusal-side state changes happen only after
    the wallet intent signature has been verified."""

    def setUp(self):
        cache.clear()
        self.deadline = str(int(time.time()) + 600)

    def _mutate(self, calls, user, valid_signature=True, request_id=None):
        from cusd_plus.schema import SponsorBscBatch
        gql_calls = [mock.Mock(to=c['to'], value_wei=c['value'], data=c['data'])
                     for c in calls]
        signature = (
            mock.patch('cusd_plus.sponsor_7702.recover_intent_signer', return_value=USER)
            if valid_signature else nullcontext()
        )
        with mock.patch('cusd_plus.schema._active_bsc_address', return_value=USER), \
             mock.patch('cusd_plus.sponsor_7702.is_delegated', return_value=False), \
             signature:
            return SponsorBscBatch.mutate(
                None, _info(user), gql_calls, '0', self.deadline,
                '0x' + '00' * 65, None, request_id)

    def test_mint_batch_refused_for_ineligible(self):
        calls = [_call(USDT, _approve_data()), _call(VAULT, _mint_data())]
        res = self._mutate(calls, _user('US', uid=21))
        self.assertEqual(res.error, 'mint_not_available')

    def test_ineligible_internal_wrap_does_not_close_usdt_sagas(self):
        calls = [_call(VAULT, _wrap_data())]
        with mock.patch('cusd_plus.tasks.mark_saga_delivered_as_usdt') as close:
            res = self._mutate(calls, _user('US', uid=211))
        self.assertEqual(res.error, 'mint_not_available')
        close.assert_not_called()

    def test_mint_batch_passes_gate_for_eligible(self):
        calls = [_call(USDT, _approve_data()), _call(VAULT, _mint_data())]
        res = self._mutate(calls, _user('VE', uid=22))
        # Proceeds past the gate and dies later on the dummy signature.
        self.assertNotEqual(res.error, 'mint_not_available')

    def test_exact_one_dollar_batch_stays_raw(self):
        calls = [
            _call(USDT, _approve_data()),
            _call(VAULT, _mint_data(amount=10**18)),
        ]
        with mock.patch('cusd_plus.tasks.mark_saga_delivered_as_usdt') as close:
            res = self._mutate(calls, _user('VE', uid=27))
        self.assertEqual(res.error, 'mint_below_redeemable_minimum')
        close.assert_called_once_with(
            USER, 10**18, refusal_source='sponsored')

    def test_bad_signature_cannot_close_exact_one_dollar_saga(self):
        calls = [_call(VAULT, _mint_data(amount=10**18))]
        with mock.patch('cusd_plus.tasks.mark_saga_delivered_as_usdt') as close:
            res = self._mutate(
                calls, _user('VE', uid=271), valid_signature=False)
        self.assertEqual(res.error, 'bad_intent_signature')
        close.assert_not_called()

    def test_exact_replay_wins_over_a_new_policy_refusal(self):
        calls = [_call(VAULT, _mint_data(amount=2 * 10**18))]
        existing = SimpleNamespace(
            user_bsc_address=USER, kind='subscribe', tx_hash='0xabc')
        with mock.patch('blockchain.models.SponsoredBatch.objects') as objects, \
             mock.patch('cusd_plus.sponsor_7702.batch_matches_calls', return_value=True), \
             mock.patch('cusd_plus.sponsor_7702.batch_execution_hint', return_value='executed'), \
             mock.patch('cusd_plus.tasks.mark_saga_delivered_as_usdt') as close:
            objects.filter.return_value.order_by.return_value.first.return_value = existing
            res = self._mutate(
                calls, _user('US', uid=272), request_id='replay_0123456789abcdef')
        self.assertTrue(res.success)
        self.assertEqual(res.tx_hash, '0xabc')
        close.assert_not_called()

    def test_one_micro_dollar_buffer_passes_batch_gate(self):
        calls = [
            _call(USDT, _approve_data()),
            _call(VAULT, _mint_data(amount=10**18 + 10**12)),
        ]
        res = self._mutate(calls, _user('VE', uid=28))
        self.assertNotEqual(res.error, 'mint_below_redeemable_minimum')

    def test_exact_one_dollar_internal_wrap_is_refused(self):
        calls = [_call(VAULT, _wrap_data(amount=10**18))]
        with mock.patch('cusd_plus.tasks.mark_saga_delivered_as_usdt') as close:
            res = self._mutate(calls, _user('VE', uid=281))
        self.assertEqual(res.error, 'mint_below_redeemable_minimum')
        close.assert_not_called()

    def test_buffered_internal_wrap_passes_amount_gate(self):
        calls = [_call(VAULT, _wrap_data(amount=10**18 + 10**12))]
        res = self._mutate(calls, _user('VE', uid=282))
        self.assertNotEqual(res.error, 'mint_below_redeemable_minimum')

    def test_truncated_mint_batch_is_rejected_cleanly(self):
        calls = [_call(VAULT, '0x' + sponsor_7702.SEL_SUBSCRIBE_AND_MINT)]
        res = self._mutate(calls, _user('VE', uid=29))
        self.assertEqual(res.error, 'bad_calldata')

    def test_non_hex_mint_amount_is_rejected_cleanly(self):
        data = _mint_data(amount=10**18)
        malformed = data[:10] + ('z' * 64) + data[74:]
        res = self._mutate([_call(VAULT, malformed)], _user('VE', uid=291))
        self.assertEqual(res.error, 'bad_calldata')

    def test_second_mint_cannot_bypass_amount_floor(self):
        calls = [
            _call(VAULT, _mint_data(amount=2 * 10**18)),
            _call(VAULT, _mint_data(amount=10**18)),
        ]
        res = self._mutate(calls, _user('VE', uid=30))
        self.assertEqual(res.error, 'multiple_mints_not_allowed')

    def test_redeem_only_batch_never_consults_gate(self):
        calls = [_call(VAULT, _redeem_data(recipient=USER))]
        with mock.patch('cusd_plus.eligibility.check_savings_mint_eligibility') as gate:
            res = self._mutate(calls, _user('US', uid=23))
        gate.assert_not_called()
        self.assertNotEqual(res.error, 'mint_not_available')

    def test_sponsored_usdt_transfer_never_consults_gate(self):
        # The sponsored raw-USDT send (exit) — ineligible users ride it too.
        transfer = ('0x' + sponsor_7702.SEL_TRANSFER
                    + ('cd' * 20).rjust(64, '0') + format(1, 'x').rjust(64, '0'))
        calls = [_call(USDT, transfer)]
        with mock.patch('cusd_plus.eligibility.check_savings_mint_eligibility') as gate:
            res = self._mutate(calls, _user('US', uid=24))
        gate.assert_not_called()
        self.assertNotEqual(res.error, 'mint_not_available')

    @override_settings(
        CUSD_PLUS_STOCKS_ENABLED=True,
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER,
        CUSD_PLUS_GM_TRADE_FEE_BPS=30,
        CUSD_PLUS_STOCK_BUY_BLOCKED_COUNTRIES=['CO'],
    )
    def test_colombia_stock_buy_batch_refused_when_server_sets_sell_only(self):
        approve = '0x' + sponsor_7702.SEL_APPROVE + _word(ROUTER) + _word(2**256 - 1)
        calls = [_call(VAULT, approve), _call(ROUTER, _stock_data(0))]
        res = self._mutate(calls, _user('CO', uid=25))
        self.assertEqual(res.error, 'trade_not_available')

    @override_settings(
        CUSD_PLUS_STOCKS_ENABLED=True,
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER,
        CUSD_PLUS_GM_TRADE_FEE_BPS=30,
        CUSD_PLUS_STOCK_BUY_BLOCKED_COUNTRIES=['CO'],
    )
    def test_colombia_stock_sell_batch_remains_an_exit_in_sell_only_mode(self):
        approve = '0x' + sponsor_7702.SEL_APPROVE + _word(ROUTER) + _word(2**256 - 1)
        calls = [_call(STOCK, approve), _call(ROUTER, _stock_data(1))]
        with mock.patch('cusd_plus.eligibility.check_stock_buy_eligibility') as gate:
            res = self._mutate(calls, _user('CO', uid=26))
        gate.assert_not_called()
        self.assertNotEqual(res.error, 'trade_not_available')

    @override_settings(
        CUSD_PLUS_STOCKS_ENABLED=True,
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER,
        CUSD_PLUS_GM_TRADE_FEE_BPS=30,
    )
    def test_stock_sell_batch_refused_by_ondo_issuer_country(self):
        approve = '0x' + sponsor_7702.SEL_APPROVE + _word(ROUTER) + _word(2**256 - 1)
        calls = [_call(STOCK, approve), _call(ROUTER, _stock_data(1))]
        res = self._mutate(calls, _user('US', uid=27))
        self.assertEqual(res.error, 'trade_not_available')


class RampOrderGateRemovalTests(SimpleTestCase):
    """CreateRampOrder: savings ON_RAMP no longer geo-refuses; the
    missing-bsc_address refusal stays."""

    def _mutate(self, account, user):
        from ramps.schema import CreateRampOrder
        client = mock.Mock(is_configured=False)
        with mock.patch('ramps.schema._resolve_ramp_country_code', return_value='CO'), \
             mock.patch('ramps.schema._get_ramp_account_for_user', return_value=account), \
             mock.patch('ramps.schema._get_wallet_upgrade_blocker', return_value=None), \
             mock.patch('ramps.schema.KoyweClient', return_value=client), \
             override_settings(KOYWE_USE_MOCK_RAMP=False):
            return CreateRampOrder.mutate(
                None, _info(user), direction='ON_RAMP', amount='10',
                payment_method_code='PSE', destination='cusd_plus')

    def test_ineligible_savings_onramp_passes_geo(self):
        from cusd_plus.eligibility import INELIGIBLE_MESSAGE
        account = SimpleNamespace(bsc_address='0x' + '11' * 20)
        res = self._mutate(account, _user('US', uid=31))
        # Reaches the (unconfigured) provider step — i.e. past all geo logic.
        self.assertNotEqual(res.error, INELIGIBLE_MESSAGE)
        self.assertIn('Koywe', res.error or '')

    def test_missing_bsc_address_still_refused(self):
        account = SimpleNamespace(bsc_address=None)
        res = self._mutate(account, _user('US', uid=32))
        self.assertIn('ahorro aún no está activada', res.error or '')


class DepositNotificationCopyTests(SimpleTestCase):
    """The arrival push must never promise a mint the gate will refuse."""

    def _record(self, phone_country):
        from cusd_plus import tasks
        account = SimpleNamespace(
            account_type='personal', display_name='Test',
            user=SimpleNamespace(phone_country=phone_country), business=None)
        account_qs = mock.Mock()
        account_qs.select_related.return_value.first.return_value = account
        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)

        with mock.patch('conversion.models.Conversion.objects') as conv_objs, \
             mock.patch('users.models.Account.objects') as acct_objs, \
             mock.patch('send.models.SendTransaction.all_objects') as sends, \
             mock.patch('notifications.utils.create_notification', side_effect=_capture):
            conv_objs.filter.return_value.exists.return_value = False
            conv_objs.create.return_value = mock.Mock(internal_id='cid')
            # The receipt is the durable record for an ineligible holder; the
            # notification is suppressed without one (audit 2026-08-01).
            sends.filter.return_value.exists.return_value = False
            sends.create.return_value = mock.Mock(internal_id='rid')
            acct_objs.filter.return_value = account_qs
            tasks._record_inbound_deposit(
                1, USER, 12.5, 'ref', '0x' + 'aa' * 32, 'external', None)
        return captured

    def test_eligible_copy_promises_auto_mint(self):
        captured = self._record('VE')
        self.assertIn('ahorro', captured['message'])
        self.assertTrue(captured['data']['pending_auto_mint'])

    def test_ineligible_copy_says_confio_dollar(self):
        captured = self._record('US')
        self.assertIn('Confío Dollar', captured['message'])
        self.assertNotIn('ahorro', captured['message'])
        self.assertTrue(captured['data']['pending_auto_mint'])


class UsdtBalanceCacheTests(SimpleTestCase):
    """usdt_balance_raw/usd — position_usd cache posture."""

    ADDR = '0x' + 'ab' * 20

    def setUp(self):
        cache.clear()

    def test_cached_within_ttl(self):
        from cusd_plus import vault
        with mock.patch.object(vault, 'erc20_balance_raw',
                               return_value=5 * 10 ** 18) as read:
            self.assertEqual(vault.usdt_balance_usd(self.ADDR), 5.0)
            self.assertEqual(vault.usdt_balance_usd(self.ADDR), 5.0)
        read.assert_called_once()

    def test_rpc_failure_falls_back_to_last_known(self):
        from cusd_plus import vault
        with mock.patch.object(vault, 'erc20_balance_raw',
                               return_value=5 * 10 ** 18):
            vault.usdt_balance_usd(self.ADDR)
        cache.delete(f'cusd_plus_usdt:{self.ADDR.lower()}')
        with mock.patch.object(vault, 'erc20_balance_raw',
                               side_effect=RuntimeError('node down')):
            self.assertEqual(vault.usdt_balance_usd(self.ADDR), 5.0)

    def test_fresh_bypasses_cache_and_raises(self):
        from cusd_plus import vault
        with mock.patch.object(vault, 'erc20_balance_raw',
                               return_value=7 * 10 ** 18) as read:
            vault.usdt_balance_raw(self.ADDR)          # seeds the cache
            self.assertEqual(vault.usdt_balance_raw(self.ADDR, fresh=True),
                             7 * 10 ** 18)
        self.assertEqual(read.call_count, 2)
        with mock.patch.object(vault, 'erc20_balance_raw',
                               side_effect=RuntimeError('node down')):
            with self.assertRaises(RuntimeError):
                vault.usdt_balance_raw(self.ADDR, fresh=True)

    def test_invalidate_clears_usdt_key(self):
        from cusd_plus import vault
        with mock.patch.object(vault, 'erc20_balance_raw',
                               return_value=5 * 10 ** 18) as read:
            vault.usdt_balance_usd(self.ADDR)
            vault.invalidate_position(self.ADDR)
            vault.usdt_balance_usd(self.ADDR)
        self.assertEqual(read.call_count, 2)
