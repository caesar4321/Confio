"""
EIP-7702 sponsored batch rail (sponsor_7702 + SponsorBscBatch): policy
rejections, signature verification, authorization handling, and a full
happy path whose produced type-4 raw tx is decoded back with eth-account
and checked field by field.

Runs without a database (ledger writes and JWT lookups are mocked):
    myvenv/bin/python manage.py test cusd_plus.tests.test_sponsor_7702
"""
import json
import time
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import SimpleTestCase, override_settings

from eth_keys import keys
from eth_utils import keccak
from eth_abi import encode as abi_encode

from cusd_plus import sponsor_7702
from cusd_plus.sponsor_7702 import PolicyError

VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'
CUSD = '0x' + '66' * 20
DELEGATE = '0x' + '77' * 20
ROUTER = '0x' + '88' * 20
STOCK = '0x' + '99' * 20
USDT = sponsor_7702.USDT_BSC
CHAIN_ID = 56
RUNTIME_CODE = '0x6080aabb'  # anything non-empty for the state override

USER_KEY = keys.PrivateKey(b'\x11' * 32)
USER = USER_KEY.public_key.to_address()          # lowercase
SPONSOR_KEY = keys.PrivateKey(b'\x22' * 32)
MALLORY_KEY = keys.PrivateKey(b'\x33' * 32)


def _word(x) -> str:
    if isinstance(x, str):  # address
        return x.lower().replace('0x', '').rjust(64, '0')
    return format(int(x), 'x').rjust(64, '0')


def _approve_data(spender=VAULT, amount=2**256 - 1) -> str:
    return '0x' + sponsor_7702.SEL_APPROVE + _word(spender) + _word(amount)


def _mint_data(recipient=USER, amount=2 * 10**18, min_out=0) -> str:
    return '0x' + sponsor_7702.SEL_SUBSCRIBE_AND_MINT + _word(amount) + _word(min_out) + _word(recipient)


def _redeem_data(recipient=USER, shares=10**18, min_out=0) -> str:
    return '0x' + sponsor_7702.SEL_REDEEM_TO_USDT + _word(shares) + _word(min_out) + _word(recipient)


def _cusd_mint_data(recipient=USER, amount=2 * 10**18, min_out=0) -> str:
    return '0x' + sponsor_7702.SEL_CUSD_MINT + _word(amount) + _word(min_out) + _word(recipient)


def _unwrap_data(recipient=USER, shares=10**18, min_out=0) -> str:
    return '0x' + sponsor_7702.SEL_UNWRAP_TO_CUSD + _word(shares) + _word(min_out) + _word(recipient)


def _cusd_redeem_data(recipient=USER, amount=10**18, min_out=0) -> str:
    return '0x' + sponsor_7702.SEL_CUSD_REDEEM + _word(amount) + _word(min_out) + _word(recipient)


def _call(to, data, value='0'):
    return {'to': to.lower(), 'value': value, 'data': data.lower()}


def _stock_data(side=0, *, max_fee=30, expiration=None, min_usdt=None):
    expiration = expiration or int(time.time()) + 300
    quote = (CHAIN_ID, 123, b'\x44' * 32, STOCK, 300 * 10**18, 2 * 10**18,
             expiration, side, b'\x00' * 32)
    signature = b'\x55' * 65
    if side == 0:
        types = [sponsor_7702.GM_QUOTE_ABI, 'bytes', 'uint256', 'uint256', 'uint256', 'uint256']
        spend = 600 * 10**18
        fee = (spend * 30 + 9969) // 9970
        floor = min_usdt if min_usdt is not None else spend + fee
        values = [quote, signature, 602 * 10**18, spend, floor, max_fee]
        selector = sponsor_7702.SEL_STOCK_BUY
    else:
        types = [sponsor_7702.GM_QUOTE_ABI, 'bytes', 'uint256', 'uint256', 'uint256']
        floor = min_usdt if min_usdt is not None else 594 * 10**18
        values = [quote, signature, floor, 588 * 10**18, max_fee]
        selector = sponsor_7702.SEL_STOCK_SELL
    return '0x' + selector + abi_encode(types, values).hex()


def _intent_id(calls, request_id=None):
    """The generic rail's intentId derivation — kind from the selectors
    (mirror of cusd_plus/schema.py), source_id omitted."""
    return sponsor_7702.intent_id_for(
        sponsor_7702.classify_calls_kind(calls),
        client_request_id=request_id,
    )


def _sign_intent(calls, nonce, deadline, key=USER_KEY, user_addr=USER,
                 request_id=None):
    digest = sponsor_7702.intent_digest(
        calls, nonce, deadline, user_addr, CHAIN_ID,
        _intent_id(calls, request_id))
    return '0x' + key.sign_msg_hash(digest).to_bytes().hex()  # r‖s‖v(0/1)


def _sign_authorization(nonce=0, key=USER_KEY, chain_id=CHAIN_ID, delegate=DELEGATE):
    import rlp
    payload = rlp.encode([chain_id, bytes.fromhex(delegate[2:]), nonce])
    sig = key.sign_msg_hash(keccak(b'\x05' + payload))
    return {
        'chain_id': chain_id,
        'address': delegate.lower(),
        'nonce': str(nonce),
        'y_parity': sig.v,
        'r': hex(sig.r),
        's': hex(sig.s),
    }


class PolicyTests(SimpleTestCase):
    """validate_policy: only exact vault-flow calls for THIS user pass."""

    def _validate(self, calls, user=None):
        with override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT, CUSD_VAULT_ADDRESS=CUSD):
            sponsor_7702.validate_policy(calls, user or mock.Mock(id=1), USER)

    def _assert_rejected(self, calls, code):
        with self.assertRaises(PolicyError) as ctx:
            self._validate(calls)
        self.assertEqual(ctx.exception.code, code)

    def test_deposit_batch_accepted(self):
        self._validate([_call(USDT, _approve_data()), _call(VAULT, _mint_data())])

    def test_universal_cusd_mint_batch_accepted_and_classified(self):
        calls = [
            _call(USDT, _approve_data(spender=CUSD)),
            _call(CUSD, _cusd_mint_data()),
        ]
        self._validate(calls)
        self.assertEqual(sponsor_7702.classify_calls_kind(calls), 'mint_cusd')

    def test_universal_cusd_mint_recipient_is_pinned_to_user(self):
        self._assert_rejected(
            [_call(CUSD, _cusd_mint_data(recipient='0x' + 'cd' * 20))],
            'mint_recipient_not_allowed',
        )

    def test_multiple_conversion_actions_rejected(self):
        self._assert_rejected(
            [_call(CUSD, _cusd_mint_data()), _call(CUSD, _cusd_mint_data())],
            'multiple_conversion_actions',
        )

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=True)
    @mock.patch('cusd_plus.cusd_vault.preview_redeem_wei')
    def test_normalize_then_single_fee_exit_and_provider_transfer_allowed(self, preview):
        preview.return_value = mock.Mock(net_wei=991)
        transfer = '0x' + sponsor_7702.SEL_TRANSFER + _word('0x' + 'cd' * 20) + _word(991)
        self._validate([
            _call(VAULT, _unwrap_data(min_out=500)),
            _call(CUSD, _cusd_redeem_data(amount=1000, min_out=991)),
            _call(USDT, transfer),
        ])

    def test_value_rejected(self):
        self._assert_rejected([_call(USDT, _approve_data(), value='1')], 'value_not_allowed')

    def test_unknown_destination_rejected(self):
        self._assert_rejected([_call('0x' + 'ab' * 20, _approve_data())], 'destination_not_allowed')

    def test_usdt_transfer_allowed_any_recipient(self):
        # Before the cUSD perimeter rollout, retain the legacy raw-USDT rail.
        transfer = '0x' + sponsor_7702.SEL_TRANSFER + _word('0x' + 'cd' * 20) + _word(1)
        with override_settings(
            CUSD_PLUS_VAULT_ADDRESS=VAULT,
            CUSD_CONVERSION_FEE_ENABLED=False,
        ):
            sponsor_7702.validate_policy([_call(USDT, transfer)], mock.Mock(), USER)

    def test_usdt_transfer_rejected_when_fee_perimeter_is_live(self):
        transfer = '0x' + sponsor_7702.SEL_TRANSFER + _word('0x' + 'cd' * 20) + _word(1)
        with override_settings(
            CUSD_PLUS_VAULT_ADDRESS=VAULT,
            CUSD_CONVERSION_FEE_ENABLED=True,
        ):
            with self.assertRaisesRegex(PolicyError, 'raw_usdt_transfer_not_allowed'):
                sponsor_7702.validate_policy([_call(USDT, transfer)], mock.Mock(), USER)

    @override_settings(CUSD_CONVERSION_FEE_ENABLED=False)
    def test_usdt_transfer_bad_length_rejected(self):
        # Isolate calldata validation from the live perimeter policy, which
        # deliberately rejects every ordinary raw-USDT transfer first.
        short = '0x' + sponsor_7702.SEL_TRANSFER + _word(1)
        self._assert_rejected([_call(USDT, short)], 'bad_calldata')

    def test_usdt_other_selector_rejected(self):
        transfer_from = '0x' + '23b872dd' + _word(USER) + _word(USER) + _word(1)
        self._assert_rejected([_call(USDT, transfer_from)], 'selector_not_allowed')

    def test_approve_foreign_spender_rejected(self):
        self._assert_rejected(
            [_call(USDT, _approve_data(spender='0x' + 'cd' * 20))],
            'approve_spender_not_allowed')

    def test_mint_recipient_pinned_to_user(self):
        self._assert_rejected(
            [_call(VAULT, _mint_data(recipient='0x' + 'cd' * 20))],
            'mint_recipient_not_allowed')

    def test_vault_unknown_selector_rejected(self):
        self._assert_rejected([_call(VAULT, '0xdeadbeef' + _word(0) * 3)], 'selector_not_allowed')

    def test_redeem_to_self_accepted(self):
        self._validate([_call(VAULT, _redeem_data(recipient=USER))])

    def test_redeem_to_live_guardarian_address_accepted(self):
        ramp = '0x' + 'ee' * 20
        with mock.patch.object(sponsor_7702, '_guardarian_savings_deposit_address',
                               return_value=ramp):
            self._validate([_call(VAULT, _redeem_data(recipient=ramp))])

    def test_redeem_to_stranger_rejected(self):
        with mock.patch.object(sponsor_7702, '_guardarian_savings_deposit_address',
                               return_value=None):
            self._assert_rejected(
                [_call(VAULT, _redeem_data(recipient='0x' + 'ee' * 20))],
                'redeem_recipient_not_allowed')

    @override_settings(
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER,
        CUSD_PLUS_GM_TRADE_FEE_BPS=30,
    )
    def test_stock_buy_and_sell_batches_accepted(self):
        buy_approve = '0x' + sponsor_7702.SEL_APPROVE + _word(ROUTER) + _word(2**256 - 1)
        sell_approve = '0x' + sponsor_7702.SEL_APPROVE + _word(ROUTER) + _word(2**256 - 1)
        self._validate([_call(VAULT, buy_approve), _call(ROUTER, _stock_data(0))])
        self._validate([_call(STOCK, sell_approve), _call(ROUTER, _stock_data(1))])

    @override_settings(
        CUSD_PLUS_STOCK_TRADING_ENABLED=False,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER,
        CUSD_PLUS_GM_TRADE_FEE_BPS=31,
    )
    def test_historical_stock_decode_survives_later_ops_switches(self):
        action = sponsor_7702._decode_stock_call(
            _call(ROUTER, _stock_data(0, expiration=int(time.time()) - 3600)),
            historical=True,
        )
        self.assertEqual(action['kind'], 'stock_buy')
        self.assertGreater(action['history_amount_wei'], 600 * 10**18)

    @override_settings(
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER,
        CUSD_PLUS_GM_TRADE_FEE_BPS=30,
    )
    def test_stock_batch_rejects_wrong_approval_token_and_fee(self):
        approve = '0x' + sponsor_7702.SEL_APPROVE + _word(ROUTER) + _word(2**256 - 1)
        self._assert_rejected(
            [_call(USDT, approve), _call(ROUTER, _stock_data(0))], 'bad_stock_batch')
        self._assert_rejected([_call(ROUTER, _stock_data(0, max_fee=31))], 'bad_stock_fee_cap')

        with override_settings(CUSD_PLUS_GM_TRADE_FEE_BPS=31):
            self._assert_rejected(
                [_call(ROUTER, _stock_data(0, max_fee=31))], 'bad_stock_fee_cap')

    @override_settings(
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER,
        CUSD_PLUS_GM_TRADE_FEE_BPS=30,
    )
    def test_stock_batch_rejects_weak_slippage_floors(self):
        self._assert_rejected(
            [_call(ROUTER, _stock_data(0, min_usdt=1))], 'bad_stock_floor')
        self._assert_rejected(
            [_call(ROUTER, _stock_data(1, min_usdt=1))], 'bad_stock_floor')

    @override_settings(
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER,
    )
    def test_stock_batch_rejects_expired_attestation(self):
        self._assert_rejected(
            [_call(ROUTER, _stock_data(0, expiration=int(time.time()) - 1))],
            'bad_stock_expiration')

    @override_settings(
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER,
    )
    def test_stock_batch_rejects_noncanonical_and_multiple_router_calls(self):
        # Solidity's ABI decoder can ignore trailing words. The sponsor must
        # bind only the one canonical byte representation the client signs.
        self._assert_rejected(
            [_call(ROUTER, _stock_data(0) + '00' * 32)],
            'bad_calldata')
        self._assert_rejected(
            [_call(ROUTER, _stock_data(0)), _call(ROUTER, _stock_data(0))],
            'multiple_stock_trades')


class SignatureTests(SimpleTestCase):
    """Digest construction and recovery, incl. the cross-stack anchor."""

    def test_shared_eip712_vector(self):
        # SAME vector as test_sharedEip712Vector (forge) and the ethers-v6
        # validator script. Never change one alone.
        calls = [
            _call('0x1111111111111111111111111111111111111111', '0xdeadbeef'),
            {'to': '0x2222222222222222222222222222222222222222', 'value': '1000000', 'data': '0x'},
        ]
        # intentId = bytes32(0), matching the forge + mts vectors.
        digest = sponsor_7702.intent_digest(
            calls, 7, 1_900_000_000, '0x00000000000000000000000000000000000000aa', 56, b'\x00' * 32)
        self.assertEqual(
            digest.hex(),
            'f955b9171a0a662c24b602836539fb8a7bdd57272ea2aed94e41917ebd2bd2d2')

    def test_intent_signer_roundtrip(self):
        calls = [_call(USDT, _approve_data())]
        digest = sponsor_7702.intent_digest(
            calls, 0, 2_000_000_000, USER, CHAIN_ID, _intent_id(calls))
        sig = _sign_intent(calls, 0, 2_000_000_000)
        self.assertEqual(sponsor_7702.recover_intent_signer(digest, sig), USER)
        # 27/28-style v is accepted too (client sends what OZ ECDSA expects)
        raw = bytes.fromhex(sig[2:])
        sig27 = '0x' + raw[:64].hex() + bytes([raw[64] + 27]).hex()
        self.assertEqual(sponsor_7702.recover_intent_signer(digest, sig27), USER)

    def test_authorization_authority_matches_eth_account(self):
        # Ground our hand-rolled 0x05-magic digest against eth-account's own
        # sign_authorization (the library the sponsor tx is built with).
        from eth_account import Account
        signed = Account.sign_authorization({
            'chainId': CHAIN_ID, 'address': DELEGATE, 'nonce': 5,
        }, USER_KEY.to_bytes())
        auth = {
            'chain_id': CHAIN_ID, 'address': DELEGATE.lower(), 'nonce': '5',
            'y_parity': signed.y_parity, 'r': hex(signed.r), 's': hex(signed.s),
        }
        self.assertEqual(sponsor_7702.recover_authorization_authority(auth), USER)

    def test_wrong_key_recovers_different_address(self):
        calls = [_call(USDT, _approve_data())]
        digest = sponsor_7702.intent_digest(
            calls, 0, 2_000_000_000, USER, CHAIN_ID, _intent_id(calls))
        sig = _sign_intent(calls, 0, 2_000_000_000, key=MALLORY_KEY)
        self.assertNotEqual(sponsor_7702.recover_intent_signer(digest, sig), USER)


class _Info:
    class context:
        user = mock.Mock(is_authenticated=True, id=1)


def _rpc_factory(overrides=None, delegated=False, sent_raws=None):
    """Stub the BSC node: sane defaults, per-method overrides."""
    def rpc(method, params):
        if overrides and method in overrides:
            value = overrides[method]
            if isinstance(value, Exception):
                raise value
            return value
        if method == 'eth_getCode':
            target = (params[0] or '').lower()
            if target == DELEGATE.lower():
                return RUNTIME_CODE
            return ('0xef0100' + DELEGATE[2:].lower()) if delegated else '0x'
        if method == 'eth_call':
            return '0x'
        if method == 'eth_gasPrice':
            return hex(100_000_000)  # 0.1 gwei
        if method == 'eth_getTransactionCount':
            return '0x0'
        if method == 'eth_getBalance':
            return hex(10 ** 18)
        if method == 'eth_sendRawTransaction':
            if sent_raws is not None:
                sent_raws.append(params[0])
            return '0x' + 'ab' * 32
        if method == 'eth_getTransactionReceipt':
            # send_sponsored_batch's brief post-broadcast look. Default is
            # "not mined yet", the same answer a real node gives in the
            # milliseconds after a broadcast; the wait is set to 0ms below
            # so these tests never actually sleep on it.
            return None
        raise AssertionError(f'unexpected rpc {method}')
    return rpc


@override_settings(
    CUSD_PLUS_7702_ENABLED=True,
    CUSD_PLUS_BATCH_DELEGATE_ADDRESS=DELEGATE,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    BSC_CHAIN_ID=56,
    CUSD_PLUS_SUBMIT_RECEIPT_WAIT_MS=0,  # broadcast path only; the wait has its own tests
)
class SponsorBscBatchTests(SimpleTestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.deadline = int(time.time()) + 600

    class _StubSigner:
        """Local stand-in for the KMS signer: same interface, eth_keys key.
        sign_typed_transaction is borrowed from the real class so the type-4
        assembly under test is the production code path."""

        def __init__(self, priv):
            from blockchain.evm_kms_signer import EVMKMSSigner
            self._priv = priv
            self.key_id = 'stub'
            self.key_alias = 'stub'
            self.address = priv.public_key.to_checksum_address()
            self._real = EVMKMSSigner.sign_typed_transaction

        def sign_digest(self, digest):
            sig = self._priv.sign_msg_hash(digest)
            return sig.v, sig.r, sig.s

        def sign_typed_transaction(self, tx):
            return self._real(self, tx)

    def _mutate(self, calls=None, nonce='0', deadline=None, intent_sig=None,
                authorization=None, delegated=False, rpc_overrides=None,
                sent_raws=None, user_addr=USER, request_id=None,
                existing_batch=None, create_side_effect=None):
        from cusd_plus.schema import SponsorBscBatch

        deadline = deadline if deadline is not None else self.deadline
        if calls is None:
            calls = [_call(USDT, _approve_data()), _call(VAULT, _mint_data())]
        if intent_sig is None:
            intent_sig = _sign_intent(
                calls, int(nonce), deadline, request_id=request_id)

        gql_calls = [mock.Mock(to=c['to'], value_wei=c['value'], data=c['data']) for c in calls]
        gql_auth = None
        if authorization is not None:
            gql_auth = mock.Mock(
                chain_id=authorization['chain_id'], address=authorization['address'],
                nonce=authorization['nonce'], y_parity=authorization['y_parity'],
                r=authorization['r'], s=authorization['s'])

        rpc = _rpc_factory(rpc_overrides, delegated=delegated, sent_raws=sent_raws)
        with mock.patch.object(sponsor_7702, '_rpc', side_effect=rpc), \
             mock.patch('cusd_plus.schema._active_bsc_address', return_value=user_addr), \
             mock.patch('blockchain.models.SponsoredBatch.objects') as ledger, \
             mock.patch('cusd_plus.tasks.check_sponsored_batch_receipt') as receipt_task, \
             mock.patch('cusd_plus.sponsor_7702.transaction.atomic'), \
             mock.patch('blockchain.evm_kms_signer.get_bsc_sponsor_signer_from_settings',
                        return_value=self._StubSigner(SPONSOR_KEY)):
            ledger.create.return_value = mock.Mock(id=99)
            ledger.create.side_effect = create_side_effect
            ledger.filter.return_value.order_by.return_value.first.return_value = existing_batch
            res = SponsorBscBatch.mutate(
                None, _Info(), gql_calls, str(nonce), str(deadline), intent_sig,
                gql_auth, request_id)
        return res, ledger, receipt_task

    # ── gates ──

    @override_settings(CUSD_PLUS_7702_ENABLED=False)
    def test_disabled_gate(self):
        res, *_ = self._mutate()
        self.assertEqual(res.error, 'disabled')

    @override_settings(CUSD_PLUS_BATCH_DELEGATE_ADDRESS='')
    def test_delegate_not_configured(self):
        res, *_ = self._mutate()
        self.assertEqual(res.error, 'delegate_not_configured')

    def test_no_bsc_address(self):
        res, *_ = self._mutate(user_addr=None)
        self.assertEqual(res.error, 'no_bsc_address')

    def test_batch_size_cap(self):
        calls = [_call(USDT, _approve_data())] * 5
        res, *_ = self._mutate(calls=calls, intent_sig='0x' + '00' * 65)
        self.assertEqual(res.error, 'bad_batch_size')

    def test_deadline_window(self):
        res, *_ = self._mutate(deadline=int(time.time()) + 10)
        self.assertEqual(res.error, 'bad_deadline')
        res, *_ = self._mutate(deadline=int(time.time()) + 4000)
        self.assertEqual(res.error, 'bad_deadline')

    def test_no_daily_cap(self):
        """A stale day counter must not block anything.

        The per-day cap was removed: it counted every sponsored operation, so
        a few ordinary sends starved the savings mint for the rest of the day.
        Cache keys from before the change can still be live, so assert they
        are simply ignored rather than that the key is absent.
        """
        from django.core.cache import cache
        cache.set(f'cusd_plus_7702_day_{USER}', 9999, 3600)
        res, *_ = self._mutate()
        self.assertNotEqual(res.error, 'daily_cap')

    def test_no_per_user_or_address_sponsorship_cap(self):
        """Valid signed batches are bounded by policy and nonces, not time."""
        from django.core.cache import cache

        # A stale key from the retired cooldown must be inert after deploy.
        cache.set(f'cusd_plus_7702_cooldown_{USER}', 1, 60)
        for _ in range(7):
            res, ledger, _ = self._mutate(delegated=True)
            self.assertTrue(res.success, res.error)
            ledger.create.assert_called_once()

    # ── signatures & authorization ──

    def test_foreign_intent_signature_rejected(self):
        calls = [_call(USDT, _approve_data())]
        res, *_ = self._mutate(
            calls=calls, intent_sig=_sign_intent(calls, 0, self.deadline, key=MALLORY_KEY),
            delegated=True)
        self.assertEqual(res.error, 'bad_intent_signature')

    def test_undelegated_without_authorization_asks_for_one(self):
        res, *_ = self._mutate(delegated=False, authorization=None)
        self.assertEqual(res.error, 'authorization_required')
        self.assertTrue(res.authorization_required)

    def test_wildcard_chain_zero_rejected(self):
        res, *_ = self._mutate(authorization=_sign_authorization(chain_id=0))
        self.assertEqual(res.error, 'bad_auth_chain')

    def test_foreign_delegate_rejected(self):
        res, *_ = self._mutate(
            authorization=_sign_authorization(delegate='0x' + '99' * 20))
        self.assertEqual(res.error, 'bad_auth_delegate')

    def test_foreign_authorization_signer_rejected(self):
        res, *_ = self._mutate(authorization=_sign_authorization(key=MALLORY_KEY))
        self.assertEqual(res.error, 'bad_auth_signature')

    def test_stale_authorization_nonce_rejected(self):
        res, *_ = self._mutate(
            authorization=_sign_authorization(nonce=0),
            rpc_overrides={'eth_getTransactionCount': '0x3'})
        self.assertEqual(res.error, 'stale_auth_nonce')
        self.assertTrue(res.authorization_required)

    # ── sponsor-outflow guards ──

    def test_gas_price_cap(self):
        res, *_ = self._mutate(
            delegated=True, rpc_overrides={'eth_gasPrice': hex(50_000_000_000)})
        self.assertEqual(res.error, 'gas_price_too_high')

    def test_sponsor_balance_preflight(self):
        res, *_ = self._mutate(
            delegated=True, rpc_overrides={'eth_getBalance': '0x1'})
        self.assertEqual(res.error, 'sponsor_balance_low')

    def test_simulation_revert_rejects_before_broadcast(self):
        sent = []
        res, *_ = self._mutate(
            delegated=True, sent_raws=sent,
            rpc_overrides={'eth_call': RuntimeError('bsc rpc: execution reverted')})
        self.assertEqual(res.error, 'simulation_reverted')
        self.assertEqual(sent, [])

    # ── happy paths ──

    def test_first_use_full_roundtrip(self):
        """Undelegated user: authorization rides along; the raw tx decodes
        back to a type-4 with the exact policy-approved contents."""
        from eth_account import Account
        from eth_account.typed_transactions.set_code_transaction import SetCodeTransaction
        from hexbytes import HexBytes

        sent = []
        calls = [_call(USDT, _approve_data()), _call(VAULT, _mint_data())]
        res, ledger, receipt_task = self._mutate(
            calls=calls, authorization=_sign_authorization(nonce=0),
            delegated=False, sent_raws=sent)

        self.assertTrue(res.success, res.error)
        self.assertEqual(len(sent), 1)

        def _int(v):
            return int(v, 16) if isinstance(v, str) else int(v)

        def _addr(v):
            return v.lower() if isinstance(v, str) else '0x' + bytes(v).hex()

        decoded = SetCodeTransaction.from_bytes(HexBytes(sent[0])).as_dict()
        self.assertEqual(_int(decoded['type']), 4)
        self.assertEqual(_int(decoded['chainId']), 56)
        self.assertEqual(_addr(decoded['to']), USER)
        self.assertEqual(_int(decoded['value']), 0)
        self.assertEqual(len(decoded['authorizationList']), 1)
        auth = dict(decoded['authorizationList'][0])
        self.assertEqual(_int(auth['chainId']), 56)
        self.assertEqual(_addr(auth['address']), DELEGATE.lower())
        self.assertEqual(_int(auth['nonce']), 0)
        # calldata is execute(...) carrying our exact batch
        self.assertEqual(HexBytes(decoded['data'])[:4], bytes.fromhex(sponsor_7702.SEL_EXECUTE))
        self.assertLessEqual(_int(decoded['gas']), 1_100_000)
        # outer signature is the sponsor's
        self.assertEqual(
            Account.recover_transaction(sent[0]).lower(),
            SPONSOR_KEY.public_key.to_address().lower())

        ledger.create.assert_called_once()
        row = ledger.create.call_args.kwargs
        self.assertEqual(row['kind'], 'subscribe')
        self.assertEqual(row['num_calls'], 2)
        receipt_task.apply_async.assert_called_once()

    def test_delegated_user_needs_no_authorization(self):
        """After delegation the sponsor sends a plain type-2 to the EOA —
        EIP-7702 forbids a type-4 with an empty authorization list."""
        from hexbytes import HexBytes

        sent = []
        calls = [_call(VAULT, _redeem_data(recipient=USER))]
        res, ledger, _ = self._mutate(calls=calls, delegated=True, sent_raws=sent)

        self.assertTrue(res.success, res.error)
        self.assertEqual(HexBytes(sent[0])[0], 2)  # type-2 envelope
        self.assertEqual(ledger.create.call_args.kwargs['kind'], 'redeem')

    def test_new_request_id_is_signature_bound_and_persisted(self):
        request_id = 'gm_0123456789abcdef0123456789abcdef'
        calls = [_call(VAULT, _redeem_data(recipient=USER))]
        res, ledger, _ = self._mutate(
            calls=calls, delegated=True, request_id=request_id)

        self.assertTrue(res.success, res.error)
        self.assertEqual(
            ledger.create.call_args.kwargs['client_request_id'], request_id)
        self.assertTrue(ledger.create.call_args.kwargs['delegate_nonce_claimed'])

        legacy_sig = _sign_intent(calls, 0, self.deadline)
        rejected, *_ = self._mutate(
            calls=calls, delegated=True, request_id=request_id,
            intent_sig=legacy_sig)
        self.assertEqual(rejected.error, 'bad_intent_signature')

    def test_request_id_replay_returns_original_without_broadcast(self):
        request_id = 'gm_0123456789abcdef0123456789abcdef'
        calls = [_call(VAULT, _redeem_data(recipient=USER))]
        existing = mock.Mock(
            user_bsc_address=USER,
            kind='redeem',
            calls_json=json.dumps(calls),
            tx_hash='0x' + '12' * 32,
            status='sent',
        )
        sent = []
        res, ledger, _ = self._mutate(
            calls=calls, delegated=True, request_id=request_id,
            existing_batch=existing, sent_raws=sent)

        self.assertTrue(res.success, res.error)
        self.assertEqual(res.tx_hash, existing.tx_hash)
        self.assertEqual(sent, [])
        ledger.create.assert_not_called()

        existing.user_bsc_address = '0x' + 'ab' * 20
        conflict, *_ = self._mutate(
            calls=calls, delegated=True, request_id=request_id,
            existing_batch=existing)
        self.assertEqual(conflict.error, 'idempotency_conflict')

    def test_nonce_collision_is_coalesced_only_for_same_calls(self):
        calls = [_call(VAULT, _redeem_data(recipient=USER))]
        existing = mock.Mock(
            user_bsc_address=USER,
            kind='redeem',
            calls_json=json.dumps(calls),
            tx_hash='0x' + '34' * 32,
            status='sent',
        )
        sent = []
        res, _, _ = self._mutate(
            calls=calls, delegated=True, existing_batch=existing,
            create_side_effect=IntegrityError('duplicate nonce'),
            sent_raws=sent)
        self.assertTrue(res.success, res.error)
        self.assertEqual(res.tx_hash, existing.tx_hash)
        self.assertEqual(sent, [])

        different = mock.Mock(
            user_bsc_address=USER,
            kind='subscribe',
            calls_json=json.dumps([_call(USDT, _approve_data())]),
            tx_hash='0x' + '56' * 32,
            status='sent',
        )
        rejected, _, _ = self._mutate(
            calls=calls, delegated=True, existing_batch=different,
            create_side_effect=IntegrityError('duplicate nonce'))
        self.assertEqual(rejected.error, 'delegate_nonce_in_flight')

    @override_settings(CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER)
    def test_stock_replay_ignores_only_incidental_approval_call(self):
        stock_call = _call(ROUTER, _stock_data(side=1))
        existing = mock.Mock(
            kind='stock_sell',
            calls_json=json.dumps([_call(STOCK, _approve_data()), stock_call]),
        )
        self.assertTrue(sponsor_7702.batch_matches_stock_intent(
            existing, [stock_call]))

        different_trade = _call(ROUTER, _stock_data(side=0))
        self.assertFalse(sponsor_7702.batch_matches_stock_intent(
            existing, [different_trade]))


class ReceiptCheckerTests(SimpleTestCase):
    """Finality-aware receipt resolution (audit 2026-07-31 P1-3): a 7702
    batch is CONFIRMED only with the exact BatchExecuted(nonce) log AND
    finality depth AND a canonical block; the silent no-op (no such log) is
    flagged; a reorg is caught."""

    NONCE = 7
    TXH = '0x' + 'ab' * 32
    BLK = 100
    BLKHASH = '0x' + 'cd' * 32

    def _batch(self, delegate_nonce=NONCE, kind='subscribe'):
        return mock.Mock(status='sent', tx_hash=self.TXH, user_bsc_address=USER,
                         delegate_nonce=delegate_nonce, block_number=None, block_hash='',
                         kind=kind)

    def _exec_log(self, nonce=NONCE):
        from cusd_plus.tasks import _BATCH_EXECUTED_TOPIC
        return {'address': USER,
                'topics': [_BATCH_EXECUTED_TOPIC, '0x' + format(nonce, 'x').rjust(64, '0')]}

    def setUp(self):
        # _finalized_block_number caches for 2s; a value leaking between
        # tests would silently decide the gate they are trying to exercise.
        from django.core.cache import cache
        cache.delete('cusd_plus_bsc_finalized')

    def _run(self, batch, receipt, head=BLK + 100, canonical_hash=BLKHASH,
             finalized='unsupported'):
        """finalized: a block number the node reports as FINALIZED, or
        'unsupported' to model a node that doesn't serve the tag (which is
        what drives the depth fallback)."""
        from cusd_plus import tasks
        def _rpc(method, params, *a, **k):
            if method == 'eth_getTransactionReceipt':
                return receipt
            if method == 'eth_blockNumber':
                return hex(head)
            if method == 'eth_getBlockByNumber':
                if params and params[0] == 'finalized':
                    if finalized == 'unsupported':
                        return None
                    return {'number': hex(finalized), 'hash': canonical_hash}
                return {'hash': canonical_hash}
            return '0x'
        with mock.patch('blockchain.models.SponsoredBatch.objects') as objs, \
             mock.patch.object(tasks, '_rpc', side_effect=_rpc):
            objs.get.return_value = batch
            try:
                tasks.check_sponsored_batch_receipt(99)
            except Exception:  # a retry() raises; treat as "still pending"
                pass
        return batch

    def _receipt(self, status='0x1', logs=None):
        return {'status': status, 'logs': logs or [],
                'blockNumber': hex(self.BLK), 'blockHash': self.BLKHASH}

    def test_confirmed(self):
        batch = self._batch()
        self._run(batch, self._receipt(logs=[self._exec_log()]))
        self.assertEqual(batch.status, 'confirmed')
        self.assertEqual(batch.block_number, self.BLK)

    def test_stock_history_failure_keeps_batch_retryable(self):
        batch = self._batch(kind='stock_buy')
        receipt = self._receipt(logs=[self._exec_log()])
        with mock.patch(
                'cusd_plus.unified.sync_unified_from_stock_batch',
                side_effect=RuntimeError('database unavailable')) as sync:
            self._run(batch, receipt)
        sync.assert_called_once_with(batch, receipt, require_event=True, strict=True)
        self.assertEqual(batch.status, 'sent')

    def test_finalized_tag_settles_without_waiting_for_depth(self):
        """BSC finalizes in ~2 blocks (a validator-set commitment), so once
        the chain says the block is finalized we must NOT keep counting to
        CUSD_PLUS_FINALITY_DEPTH — that heuristic made users wait ~6.8s for a
        guarantee the chain had already given at ~0.9s."""
        batch = self._batch()
        self._run(batch, self._receipt(logs=[self._exec_log()]),
                  head=self.BLK + 2, finalized=self.BLK)
        self.assertEqual(batch.status, 'confirmed')

    def test_not_finalized_stays_pending_even_when_deep(self):
        """The finalized tag OVERRIDES depth in the strict direction too: a
        block buried under 100 confirmations that the validator set has not
        committed to is not settled."""
        batch = self._batch()
        self._run(batch, self._receipt(logs=[self._exec_log()]),
                  head=self.BLK + 100, finalized=self.BLK - 1)
        self.assertEqual(batch.status, 'sent')

    def test_falls_back_to_depth_when_tag_unsupported(self):
        """A partial or pre-BEP-126 endpoint must degrade to the old
        behaviour, not strand settlement."""
        batch = self._batch()
        self._run(batch, self._receipt(logs=[self._exec_log()]),
                  head=self.BLK + 100, finalized='unsupported')
        self.assertEqual(batch.status, 'confirmed')

        shallow = self._batch()
        self._run(shallow, self._receipt(logs=[self._exec_log()]),
                  head=self.BLK + 1, finalized='unsupported')
        self.assertEqual(shallow.status, 'sent')

    def test_reverted(self):
        batch = self._batch()
        self._run(batch, self._receipt(status='0x0'))
        self.assertEqual(batch.status, 'reverted')
        self.assertEqual(batch.block_number, self.BLK)
        self.assertEqual(batch.block_hash, self.BLKHASH)
        self.assertIn('block_number', batch.save.call_args.kwargs['update_fields'])

    def test_silent_noop_flagged(self):
        # The delegation didn't apply, so the tx called a CODELESS EOA and
        # could not emit anything. Zero logs is the only shape a real 7702
        # no-op has, and it is what earns a terminal noop_failed.
        batch = self._batch()
        self._run(batch, self._receipt(logs=[]))
        self.assertEqual(batch.status, 'noop_failed')

    def test_logs_present_without_proof_retries_instead_of_failing(self):
        """Codex re-audit [P1]. Non-empty logs mean SOMETHING executed, so
        this was not a no-op — we just can't see our own proof. Since
        BatchExecuted is emitted last, a clipped response looks exactly like
        this. Retry (recoverable) instead of settling noop_failed, which
        fails a batch that may have moved money and invites a re-send."""
        batch = self._batch()
        self._run(batch, self._receipt(logs=[{'address': USER, 'topics': []}]))
        self.assertEqual(batch.status, 'sent')

    def test_wrong_nonce_retries(self):
        # Same reasoning: a BatchExecuted for a different intent is evidence
        # that logs exist, not evidence that ours is absent.
        batch = self._batch()
        self._run(batch, self._receipt(logs=[self._exec_log(nonce=999)]))
        self.assertEqual(batch.status, 'sent')

    def test_missing_logs_field_never_settles_noop(self):
        """The authoritative path used to fold a missing `logs` field into []
        and settle noop_failed off it — failing an executed batch."""
        batch = self._batch()
        rec = self._receipt(logs=[])
        rec.pop('logs', None)
        self._run(batch, rec)
        self.assertEqual(batch.status, 'sent')

    def test_not_final_stays_pending(self):
        batch = self._batch()
        self._run(batch, self._receipt(logs=[self._exec_log()]), head=self.BLK + 1)
        self.assertEqual(batch.status, 'sent')  # retried, not settled

    def test_reorg_flagged(self):
        # The block that held the receipt is no longer canonical, and a
        # re-check finds no receipt → orphaned.
        batch = self._batch()
        def _rpc(method, params, *a, **k):
            if method == 'eth_getTransactionReceipt':
                # first call returns the receipt, second (re-check) returns None
                if not hasattr(_rpc, 'seen'):
                    _rpc.seen = True
                    return self._receipt(logs=[self._exec_log()])
                return None
            if method == 'eth_blockNumber':
                return hex(self.BLK + 100)
            if method == 'eth_getBlockByNumber':
                return {'hash': '0x' + 'ee' * 32}  # different hash = reorged
            return '0x'
        from cusd_plus import tasks
        with mock.patch('blockchain.models.SponsoredBatch.objects') as objs, \
             mock.patch.object(tasks, '_rpc', side_effect=_rpc):
            objs.get.return_value = batch
            tasks.check_sponsored_batch_receipt(99)
        self.assertEqual(batch.status, 'reorged')

    def test_plain_kms_confirmed_on_logs(self):
        # delegate_nonce=None (payroll payout etc.): any log + finality.
        batch = self._batch(delegate_nonce=None)
        self._run(batch, self._receipt(logs=[{'address': '0x' + '22' * 20, 'topics': []}]))
        self.assertEqual(batch.status, 'confirmed')


@override_settings(CUSD_PLUS_SIGNED_GRACE_MIN=0)
class ReconcileSignedBatchesTests(SimpleTestCase):
    """Orphaned 'signed' rows (durable-broadcast crash recovery, P1-2): a
    hash any node knows is PROMOTED and its domain confirm re-enqueued; a
    hash no node knows after the grace window is DROPPED so the domain flow
    fails and the user retries."""

    TXH = '0x' + 'ab' * 32

    def _batch(self, kind='send_usdt', source_id=7):
        return mock.Mock(id=99, status='signed', tx_hash=self.TXH, kind=kind,
                         source_id=source_id)

    def _run(self, batch, tx_result):
        from cusd_plus import tasks

        def _rpc(method, params, *a, **k):
            if method == 'eth_getTransactionByHash':
                return tx_result
            return '0x'

        qs = mock.MagicMock()
        qs.order_by.return_value.__getitem__.return_value = [batch]
        with mock.patch('blockchain.models.SponsoredBatch.objects') as objs, \
             mock.patch.object(tasks, '_rpc', side_effect=_rpc), \
             mock.patch.object(tasks, 'check_sponsored_batch_receipt') as receipt_task, \
             mock.patch.object(tasks, 'current_app') as capp:
            objs.filter.return_value = qs
            result = tasks.reconcile_signed_batches()
        return result, receipt_task, capp

    def test_known_hash_promoted_and_domain_reenqueued(self):
        batch = self._batch(kind='send_usdt', source_id=7)
        result, receipt_task, capp = self._run(batch, {'hash': self.TXH})
        self.assertEqual(batch.status, 'sent')
        self.assertEqual(result['promoted'], 1)
        receipt_task.apply_async.assert_called_once()
        capp.send_task.assert_called_once_with(
            'send.confirm_bsc_send', args=[7, 99], countdown=10)

    def test_unknown_hash_dropped(self):
        batch = self._batch(kind='pay_usdt', source_id=5)
        result, receipt_task, capp = self._run(batch, None)
        self.assertEqual(batch.status, 'dropped')
        self.assertEqual(result['dropped'], 1)
        receipt_task.apply_async.assert_not_called()
        # domain confirm still gets nudged so the row fails and the user retries
        capp.send_task.assert_called_once_with(
            'payments.confirm_bsc_payment', args=[5, 99], countdown=10)

    def test_unmapped_kind_promotes_without_domain_task(self):
        # Stock trades settle via the batch receipt task alone; chain state
        # is the portfolio ledger, so there is no separate domain row/task.
        batch = self._batch(kind='stock_buy', source_id=None)
        result, receipt_task, capp = self._run(batch, {'hash': self.TXH})
        self.assertEqual(batch.status, 'sent')
        receipt_task.apply_async.assert_called_once()
        capp.send_task.assert_not_called()


class ReconcileStockBatchesTests(SimpleTestCase):
    def test_sent_stock_receipt_is_requeued_with_compare_and_set(self):
        from cusd_plus import tasks

        batch = mock.Mock(id=44, pk=44)
        selected = mock.MagicMock()
        selected.order_by.return_value.__getitem__.return_value = [batch]
        claimed = mock.MagicMock()
        claimed.update.return_value = 1
        with mock.patch('blockchain.models.SponsoredBatch.objects') as objects, \
             mock.patch.object(tasks, 'check_sponsored_batch_receipt') as receipt_task:
            objects.filter.side_effect = [selected, claimed]
            result = tasks.reconcile_stock_batches()
        self.assertEqual(result, {'requeued': 1})
        receipt_task.apply_async.assert_called_once_with(args=[44], countdown=3)
        first_filter = objects.filter.call_args_list[0].kwargs
        self.assertEqual(first_filter['kind__in'], ('stock_buy', 'stock_sell'))
        self.assertEqual(first_filter['status'], 'sent')

    def test_terminalized_stock_is_not_requeued(self):
        from cusd_plus import tasks

        batch = mock.Mock(id=44, pk=44)
        selected = mock.MagicMock()
        selected.order_by.return_value.__getitem__.return_value = [batch]
        lost_race = mock.MagicMock()
        lost_race.update.return_value = 0
        with mock.patch('blockchain.models.SponsoredBatch.objects') as objects, \
             mock.patch.object(tasks, 'check_sponsored_batch_receipt') as receipt_task:
            objects.filter.side_effect = [selected, lost_race]
            result = tasks.reconcile_stock_batches()
        self.assertEqual(result, {'requeued': 0})
        receipt_task.apply_async.assert_not_called()


@override_settings(CUSD_PLUS_SUBMIT_RECEIPT_POLL_S=0)
class WaitForExecutionBrieflyTests(SimpleTestCase):
    """The brief post-broadcast look that lets the client skip its own poll.

    It must be as strict as the reconciler (exact BatchExecuted(nonce) from
    the user's own address) and must never turn an RPC problem into a
    verdict — an unobserved outcome is None, not a failure.
    """

    TXH = '0x' + 'cd' * 32
    ADDR = '0x' + '19' * 20
    NONCE = 7

    def _topic_nonce(self, n):
        return '0x' + format(n, 'x').rjust(64, '0')

    def _receipt(self, status='0x1', logs=None):
        return {'status': status, 'logs': logs if logs is not None else []}

    def _good_log(self, addr=None, nonce=None):
        from cusd_plus.tasks import _BATCH_EXECUTED_TOPIC
        return {
            'address': (addr or self.ADDR).upper(),  # nodes vary in casing
            'topics': [_BATCH_EXECUTED_TOPIC,
                       self._topic_nonce(self.NONCE if nonce is None else nonce)],
        }

    def _run(self, rpc_side_effect):
        # The wait now reads through _rpc_preferred_only (ONE endpoint, no
        # rotation) so its wall clock is bounded — patch that, not _rpc.
        from cusd_plus import tasks as _tasks
        with mock.patch.object(_tasks, '_rpc_preferred_only',
                               side_effect=lambda m, p, t: rpc_side_effect(m, p)):
            return sponsor_7702.wait_for_execution_briefly(
                self.TXH, self.ADDR, self.NONCE)

    def test_executed_when_batch_executed_log_matches(self):
        rec = self._receipt(logs=[self._good_log()])
        self.assertEqual(self._run(lambda m, p: rec), 'executed')

    def test_reverted_on_status_zero(self):
        # Logs are irrelevant once it reverted.
        rec = self._receipt(status='0x0', logs=[self._good_log()])
        self.assertEqual(self._run(lambda m, p: rec), 'reverted')

    def test_noop_when_node_reports_zero_logs(self):
        """The 7702 silent failure: mines 0x1 having executed nothing. An
        AFFIRMATIVE empty list is the node telling us there were no logs."""
        self.assertEqual(self._run(lambda m, p: self._receipt(logs=[])), 'noop')

    def test_unknown_when_logs_field_absent(self):
        """Codex audit [P1]: a receipt with NO logs field is not evidence of
        non-execution. Returning 'noop' here is what lets a client retry a
        batch that already executed and settle the same money twice."""
        self.assertIsNone(self._run(lambda m, p: {'status': '0x1'}))

    def test_unknown_when_nonce_differs(self):
        """A BatchExecuted from a DIFFERENT intent is not ours — but logs
        exist, so this was NOT a no-op and we must not call it one."""
        rec = self._receipt(logs=[self._good_log(nonce=self.NONCE + 1)])
        self.assertIsNone(self._run(lambda m, p: rec))

    def test_unknown_when_log_from_another_address(self):
        rec = self._receipt(logs=[self._good_log(addr='0x' + 'ee' * 20)])
        self.assertIsNone(self._run(lambda m, p: rec))

    def test_unknown_when_trailing_log_truncated(self):
        """Codex re-audit [P1]: BatchExecuted is emitted LAST, so a response
        that clips trailing logs keeps the inner transfers and drops exactly
        our proof. That must read as unknown, never as a no-op."""
        inner = {'address': '0x' + 'aa' * 20, 'topics': ['0x' + 'bb' * 32]}
        self.assertIsNone(self._run(lambda m, p: self._receipt(logs=[inner])))

    def test_never_raises_on_malformed_logs(self):
        """This runs AFTER broadcast: an exception here surfaces as "send
        failed" for a tx that is already on the network."""
        self.assertIsNone(self._run(lambda m, p: self._receipt(logs=['not-a-dict'])))
        self.assertIsNone(self._run(lambda m, p: {'status': '0x1', 'logs': [None]}))

    def test_uppercase_topics_still_match(self):
        """Codex audit [P1]: hex casing is not guaranteed across nodes, and a
        case mismatch used to read as 'did not execute' — the dangerous way to
        be wrong."""
        lg = self._good_log()
        lg['topics'] = [t.upper() for t in lg['topics']]
        self.assertEqual(self._run(lambda m, p: self._receipt(logs=[lg])), 'executed')

    def test_wall_clock_is_bounded_by_the_budget(self):
        """Codex audit [P1]: the per-call timeout must be clamped to the time
        LEFT, so a hanging endpoint cannot turn a 1.5s budget into 45s of
        rotation blocking an ASGI thread."""
        from cusd_plus import tasks as _tasks
        seen = []

        def rpc(method, params, timeout):
            seen.append(timeout)
            return None

        with override_settings(CUSD_PLUS_SUBMIT_RECEIPT_WAIT_MS=200,
                               CUSD_PLUS_SUBMIT_RECEIPT_POLL_S=0):
            with mock.patch.object(_tasks, '_rpc_preferred_only', side_effect=rpc):
                sponsor_7702.wait_for_execution_briefly(
                    self.TXH, self.ADDR, self.NONCE)
        self.assertTrue(seen, 'should have asked at least once')
        # Every per-call timeout fits inside the remaining budget.
        self.assertTrue(all(t <= 0.2 for t in seen), seen)

    def test_none_when_not_mined_inside_budget(self):
        calls = []

        def rpc(method, params):
            calls.append(method)
            return None

        # Above the 0.05s floor, so it polls at least once before giving up.
        with override_settings(CUSD_PLUS_SUBMIT_RECEIPT_WAIT_MS=60):
            self.assertIsNone(self._run(rpc))
        self.assertTrue(calls, 'should have asked at least once')

    def test_none_and_no_raise_when_rpc_fails(self):
        """An RPC problem must never be reported as an outcome — the client
        poll and the reconciler both still own this transaction."""
        def rpc(method, params):
            raise RuntimeError('all 3 BSC RPC endpoints failed')

        self.assertIsNone(self._run(rpc))

    def test_disabled_by_zero_budget_makes_no_call(self):
        def rpc(method, params):
            raise AssertionError('must not touch the node when disabled')

        with override_settings(CUSD_PLUS_SUBMIT_RECEIPT_WAIT_MS=0):
            self.assertIsNone(self._run(rpc))


@override_settings(CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER)
class StockHistoryTests(SimpleTestCase):
    TXH = '0x' + 'de' * 32

    def _batch(self, side):
        return mock.Mock(
            id=91,
            kind='stock_buy' if side == 0 else 'stock_sell',
            tx_hash=self.TXH,
            user_bsc_address=USER,
            calls_json=json.dumps([_call(ROUTER, _stock_data(side))]),
            created_at=mock.sentinel.created_at,
        )

    def _receipt(self, kind, principal, fee):
        signature = (
            'StockBought(address,address,uint256,uint256,uint256,uint256,uint256)'
            if kind == 'stock_buy'
            else 'StockSold(address,address,uint256,uint256,uint256,uint256,uint256)'
        )
        return {'logs': [{
            'address': ROUTER,
            'topics': [
                '0x' + keccak(text=signature).hex(),
                '0x' + USER[2:].rjust(64, '0'),
                '0x' + STOCK[2:].rjust(64, '0'),
            ],
            'data': '0x' + abi_encode(
                ['uint256'] * 5,
                [123, 2 * 10**18, principal, fee, 2 * 10**18],
            ).hex(),
        }]}

    def _sync(self, side, principal, fee):
        from cusd_plus.unified import sync_unified_from_stock_batch

        account = mock.Mock(
            user=mock.Mock(username='julian', phone_number='+51'),
            business=None,
            business_id=None,
        )
        account.user.get_full_name.return_value = 'Julian'
        row = mock.Mock(pk=77)
        with mock.patch('users.models.Account.objects') as accounts, \
             mock.patch('users.models_unified.UnifiedTransactionTable.objects') as rows, \
             mock.patch('send.models.SendTransaction.all_objects') as sends, \
             mock.patch('cusd_plus.unified._stock_symbol', return_value='TSLA'):
            accounts.filter.return_value.select_related.return_value.first.return_value = account
            rows.update_or_create.return_value = (row, True)
            batch = self._batch(side)
            sync_unified_from_stock_batch(
                batch, self._receipt(batch.kind, principal, fee))
        return rows, sends

    def test_buy_creates_outgoing_stock_receipt_with_exact_event_amount(self):
        rows, _ = self._sync(0, 600 * 10**18, 2 * 10**18)
        defaults = rows.update_or_create.call_args.kwargs['defaults']
        self.assertEqual(defaults['amount'], '602')
        self.assertEqual(defaults['token_type'], 'CUSD_PLUS')
        self.assertEqual(defaults['from_address'], USER)
        self.assertEqual(defaults['to_address'], ROUTER.lower())
        self.assertEqual(
            defaults['description'], 'Ondo Stocks: Compra de TSLA')
        self.assertEqual(
            rows.update_or_create.call_args.kwargs['sponsored_batch'].id, 91)

    def test_sell_creates_incoming_stock_receipt_and_hides_false_deposit(self):
        rows, sends = self._sync(1, 600 * 10**18, 2 * 10**18)
        defaults = rows.update_or_create.call_args.kwargs['defaults']
        self.assertEqual(defaults['amount'], '598')
        self.assertEqual(defaults['sender_type'], 'business')
        self.assertEqual(defaults['from_address'], ROUTER.lower())
        self.assertEqual(defaults['to_address'], USER)
        rows.filter.return_value.exclude.return_value.update.assert_called_once()
        sends.filter.return_value.update.assert_called_once()

    def test_exact_event_must_match_quoted_stock(self):
        from cusd_plus.unified import sync_unified_from_stock_batch

        batch = self._batch(0)
        receipt = self._receipt(batch.kind, 600 * 10**18, 2 * 10**18)
        receipt['logs'][0]['topics'][2] = '0x' + ('aa' * 20).rjust(64, '0')
        with mock.patch('users.models.Account.objects') as accounts:
            accounts.filter.return_value.select_related.return_value.first.return_value = mock.Mock()
            with self.assertRaisesRegex(ValueError, 'no matching exact settlement event'):
                sync_unified_from_stock_batch(
                    batch, receipt, require_event=True, strict=True)

    def test_backfill_fetches_receipt_and_writes_strict_exact_row(self):
        batch = self._batch(1)
        batch.status = 'confirmed'
        receipt = self._receipt(batch.kind, 600 * 10**18, 2 * 10**18)
        receipt['status'] = '0x1'
        queryset = mock.MagicMock()
        queryset.order_by.return_value = queryset
        queryset.count.return_value = 1
        queryset.iterator.return_value = iter([batch])
        with mock.patch(
                'blockchain.models.SponsoredBatch.objects.filter',
                return_value=queryset), \
             mock.patch('cusd_plus.management.commands.backfill_stock_history._rpc',
                        return_value=receipt), \
             mock.patch(
                 'cusd_plus.management.commands.backfill_stock_history.sync_unified_from_stock_batch'
             ) as sync:
            call_command('backfill_stock_history')
        sync.assert_called_once_with(batch, receipt, require_event=True, strict=True)

    def test_backfill_check_fails_loudly_when_rows_are_missing(self):
        queryset = mock.MagicMock()
        queryset.order_by.return_value = queryset
        queryset.count.return_value = 1
        with mock.patch(
                'blockchain.models.SponsoredBatch.objects.filter',
                return_value=queryset):
            with self.assertRaisesRegex(CommandError, '1 confirmed stock trades'):
                call_command('backfill_stock_history', check=True)

    def test_stock_batch_claims_scanner_settlement(self):
        from cusd_plus.tasks import _source_row_covers

        with mock.patch('send.models.SendTransaction.all_objects') as sends, \
             mock.patch('users.models_unified.UnifiedTransactionTable.objects') as unified, \
             mock.patch('presale.models.PresalePurchase.objects') as presale, \
             mock.patch('payments.models.PaymentTransaction.objects') as payments, \
             mock.patch('payroll.models.PayrollItem.objects') as payroll, \
             mock.patch('blockchain.models.SponsoredBatch.objects') as batches:
            sends.filter.return_value.exists.return_value = False
            unified.filter.return_value.exists.return_value = False
            presale.filter.return_value.exists.return_value = False
            payments.filter.return_value.filter.return_value.exists.return_value = False
            payroll.filter.return_value.exists.return_value = False
            batches.filter.return_value.exists.return_value = True
            self.assertTrue(_source_row_covers(self.TXH, USER))
            kwargs = batches.filter.call_args.kwargs
            self.assertEqual(kwargs['kind__in'], ('stock_buy', 'stock_sell'))
            self.assertEqual(kwargs['user_bsc_address__iexact'], USER)


class CusdFeeEventTests(SimpleTestCase):
    CUSD = '0x' + '42' * 20

    def _receipt(self, signature, values, *, address=None, log_index='0x7'):
        return {
            'logs': [{
                'address': address or self.CUSD,
                'topics': ['0x' + keccak(text=signature).hex()],
                'data': '0x' + ''.join(f'{value:064x}' for value in values),
                'logIndex': log_index,
            }],
        }

    @override_settings(CUSD_VAULT_ADDRESS=CUSD)
    def test_parses_exact_mint_fee_triplet(self):
        from cusd_plus.tasks import _cusd_fee_event

        event = _cusd_fee_event(self._receipt(
            'MintedWithFee(address,address,uint256,uint256,uint256,uint256)',
            [100, 1, 99, 90],
        ))
        self.assertEqual(event, {
            'direction': 'entry', 'conversion_type': 'usdt_to_cusd',
            'gross_wei': 100, 'fee_wei': 1, 'net_wei': 99,
            'fee_bps': 90,
            'log_index': 7,
        })

    @override_settings(CUSD_VAULT_ADDRESS=CUSD)
    def test_rejects_wrong_contract_and_inconsistent_triplet(self):
        from cusd_plus.tasks import _cusd_fee_event

        signature = 'RedeemedWithFee(address,address,uint256,uint256,uint256,uint256)'
        self.assertIsNone(_cusd_fee_event(self._receipt(
            signature, [100, 1, 99, 90], address='0x' + '43' * 20)))
        self.assertIsNone(_cusd_fee_event(self._receipt(signature, [100, 2, 99, 90])))
