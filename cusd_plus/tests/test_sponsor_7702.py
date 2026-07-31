"""
EIP-7702 sponsored batch rail (sponsor_7702 + SponsorBscBatch): policy
rejections, signature verification, authorization handling, and a full
happy path whose produced type-4 raw tx is decoded back with eth-account
and checked field by field.

Runs without a database (ledger writes and JWT lookups are mocked):
    myvenv/bin/python manage.py test cusd_plus.tests.test_sponsor_7702
"""
import time
from unittest import mock

from django.test import SimpleTestCase, override_settings

from eth_keys import keys
from eth_utils import keccak

from cusd_plus import sponsor_7702
from cusd_plus.sponsor_7702 import PolicyError

VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'
DELEGATE = '0x' + '77' * 20
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


def _mint_data(recipient=USER, amount=10**18, min_out=0) -> str:
    return '0x' + sponsor_7702.SEL_SUBSCRIBE_AND_MINT + _word(amount) + _word(min_out) + _word(recipient)


def _redeem_data(recipient=USER, shares=10**18, min_out=0) -> str:
    return '0x' + sponsor_7702.SEL_REDEEM_TO_USDT + _word(shares) + _word(min_out) + _word(recipient)


def _call(to, data, value='0'):
    return {'to': to.lower(), 'value': value, 'data': data.lower()}


def _sign_intent(calls, nonce, deadline, key=USER_KEY, user_addr=USER):
    digest = sponsor_7702.intent_digest(calls, nonce, deadline, user_addr, CHAIN_ID)
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
        with override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT):
            sponsor_7702.validate_policy(calls, user or mock.Mock(id=1), USER)

    def _assert_rejected(self, calls, code):
        with self.assertRaises(PolicyError) as ctx:
            self._validate(calls)
        self.assertEqual(ctx.exception.code, code)

    def test_deposit_batch_accepted(self):
        self._validate([_call(USDT, _approve_data()), _call(VAULT, _mint_data())])

    def test_value_rejected(self):
        self._assert_rejected([_call(USDT, _approve_data(), value='1')], 'value_not_allowed')

    def test_unknown_destination_rejected(self):
        self._assert_rejected([_call('0x' + 'ab' * 20, _approve_data())], 'destination_not_allowed')

    def test_usdt_transfer_allowed_any_recipient(self):
        # Policy change 2026-07-30: sponsored USDT transfer IS allowed — the
        # raw-USDT exit. Recipient deliberately unrestricted (exits are never
        # gated), so even a foreign recipient passes.
        transfer = '0x' + sponsor_7702.SEL_TRANSFER + _word('0x' + 'cd' * 20) + _word(1)
        with override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT):
            sponsor_7702.validate_policy([_call(USDT, transfer)], mock.Mock(), USER)

    def test_usdt_transfer_bad_length_rejected(self):
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


class SignatureTests(SimpleTestCase):
    """Digest construction and recovery, incl. the cross-stack anchor."""

    def test_shared_eip712_vector(self):
        # SAME vector as test_sharedEip712Vector (forge) and the ethers-v6
        # validator script. Never change one alone.
        calls = [
            _call('0x1111111111111111111111111111111111111111', '0xdeadbeef'),
            {'to': '0x2222222222222222222222222222222222222222', 'value': '1000000', 'data': '0x'},
        ]
        digest = sponsor_7702.intent_digest(
            calls, 7, 1_900_000_000, '0x00000000000000000000000000000000000000aa', 56)
        self.assertEqual(
            digest.hex(),
            'cc3b97117afebdebc5713d09e5cbefbed16143c3405bda7b6516c0bc7efce6c6')

    def test_intent_signer_roundtrip(self):
        calls = [_call(USDT, _approve_data())]
        digest = sponsor_7702.intent_digest(calls, 0, 2_000_000_000, USER, CHAIN_ID)
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
        digest = sponsor_7702.intent_digest(calls, 0, 2_000_000_000, USER, CHAIN_ID)
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
        raise AssertionError(f'unexpected rpc {method}')
    return rpc


@override_settings(
    CUSD_PLUS_7702_ENABLED=True,
    CUSD_PLUS_BATCH_DELEGATE_ADDRESS=DELEGATE,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    BSC_CHAIN_ID=56,
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
                sent_raws=None, user_addr=USER):
        from cusd_plus.schema import SponsorBscBatch

        deadline = deadline if deadline is not None else self.deadline
        if calls is None:
            calls = [_call(USDT, _approve_data()), _call(VAULT, _mint_data())]
        if intent_sig is None:
            intent_sig = _sign_intent(calls, int(nonce), deadline)

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
             mock.patch('cusd_plus.models.SponsoredBatch.objects') as ledger, \
             mock.patch('cusd_plus.tasks.check_sponsored_batch_receipt') as receipt_task, \
             mock.patch('blockchain.evm_kms_signer.get_bsc_sponsor_signer_from_settings',
                        return_value=self._StubSigner(SPONSOR_KEY)):
            ledger.create.return_value = mock.Mock(id=99)
            res = SponsorBscBatch.mutate(
                None, _Info(), gql_calls, str(nonce), str(deadline), intent_sig, gql_auth)
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

    def test_daily_cap(self):
        from django.core.cache import cache
        cache.set(f'cusd_plus_7702_day_{USER}', 20, 3600)
        res, *_ = self._mutate()
        self.assertEqual(res.error, 'daily_cap')

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


class ReceiptCheckerTests(SimpleTestCase):
    """Finality-aware receipt resolution (audit 2026-07-31 P1-3): a 7702
    batch is CONFIRMED only with the exact BatchExecuted(nonce) log AND
    finality depth AND a canonical block; the silent no-op (no such log) is
    flagged; a reorg is caught."""

    NONCE = 7
    TXH = '0x' + 'ab' * 32
    BLK = 100
    BLKHASH = '0x' + 'cd' * 32

    def _batch(self, delegate_nonce=NONCE):
        return mock.Mock(status='sent', tx_hash=self.TXH, user_bsc_address=USER,
                         delegate_nonce=delegate_nonce, block_number=None, block_hash='')

    def _exec_log(self, nonce=NONCE):
        from cusd_plus.tasks import _BATCH_EXECUTED_TOPIC
        return {'address': USER,
                'topics': [_BATCH_EXECUTED_TOPIC, '0x' + format(nonce, 'x').rjust(64, '0')]}

    def _run(self, batch, receipt, head=BLK + 100, canonical_hash=BLKHASH):
        from cusd_plus import tasks
        def _rpc(method, params, *a, **k):
            if method == 'eth_getTransactionReceipt':
                return receipt
            if method == 'eth_blockNumber':
                return hex(head)
            if method == 'eth_getBlockByNumber':
                return {'hash': canonical_hash}
            return '0x'
        with mock.patch('cusd_plus.models.SponsoredBatch.objects') as objs, \
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

    def test_reverted(self):
        batch = self._batch()
        self._run(batch, self._receipt(status='0x0'))
        self.assertEqual(batch.status, 'reverted')

    def test_silent_noop_flagged(self):
        # status 0x1 but no BatchExecuted log = delegation didn't apply.
        batch = self._batch()
        self._run(batch, self._receipt(logs=[{'address': USER, 'topics': []}]))
        self.assertEqual(batch.status, 'noop_failed')

    def test_wrong_nonce_is_noop(self):
        batch = self._batch()
        self._run(batch, self._receipt(logs=[self._exec_log(nonce=999)]))
        self.assertEqual(batch.status, 'noop_failed')

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
        with mock.patch('cusd_plus.models.SponsoredBatch.objects') as objs, \
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
        with mock.patch('cusd_plus.models.SponsoredBatch.objects') as objs, \
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
        # invite_create settles via the batch receipt task alone.
        batch = self._batch(kind='invite_create', source_id=3)
        result, receipt_task, capp = self._run(batch, {'hash': self.TXH})
        self.assertEqual(batch.status, 'sent')
        receipt_task.apply_async.assert_called_once()
        capp.send_task.assert_not_called()
