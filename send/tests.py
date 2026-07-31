"""
BSC send flow (send/bsc_flow.py) — the properties that make sponsored
dollar sends safe:

  1. call-shape selection follows the eligibility matrix (A: cUSD+ transfer
     to eligible internal recipients; B: atomic redeem-to-USDT for
     ineligible/external; C: raw USDT transfer) — and the explicit token
     shapes honor the request literally (D: cUSD+ itself to ANY address,
     never a silent redeem; E: BEP-20 CONFIO, never dollar-funded);
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

from django.test import SimpleTestCase, override_settings

from cusd_plus.sponsor_7702 import (
    PolicyError,
    SEL_REDEEM_TO_USDT,
    SEL_TRANSFER,
    USDT_BSC,
)
from send import bsc_flow

VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'
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


@override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT, BSC_SEND_ENABLED=True)
class PrepareCallShapeTests(SimpleTestCase):
    """The A/B/C matrix, exercised with mocked balances + ORM."""

    def _prepare(self, amount='10', shares_value=100 * WAD, usdt=0,
                 recipient_user=None, recipient_business=None,
                 recipient_addr=RECIPIENT, token=''):
        captured = {}

        def _create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(internal_id='sid123', **kwargs)

        pps = 11 * WAD // 10  # pPlus = $1.10
        with _recipient_resolution(recipient_user, recipient_business, recipient_addr), \
             mock.patch('cusd_plus.vault.p_plus_wad', return_value=pps), \
             mock.patch('cusd_plus.vault.erc20_balance_raw',
                        return_value=(shares_value * WAD) // pps), \
             mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=usdt), \
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

    def test_case_b_ineligible_recipient_gets_atomic_redeem(self):
        result, row, _ = self._prepare(recipient_user=_recipient_user('US'))
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertEqual(call['to'], VAULT.lower())
        self.assertTrue(call['data'][2:].startswith(SEL_REDEEM_TO_USDT))
        # minOut = amount * 0.995
        min_out = int(call['data'][74:138], 16)
        self.assertEqual(min_out, (10 * WAD * 9950) // 10000)
        self.assertEqual(call['data'][138:202], RECIPIENT[2:].lower().rjust(64, '0'))
        self.assertEqual(result['token_type'], 'USDT')

    def test_case_b_external_address_gets_atomic_redeem(self):
        result, _, _ = self._prepare(recipient_user=None)
        self.assertTrue(result['success'], result)
        self.assertTrue(result['calls'][0]['data'][2:].startswith(SEL_REDEEM_TO_USDT))

    def test_case_c_usdt_fallback(self):
        result, row, _ = self._prepare(
            shares_value=0, usdt=100 * WAD, recipient_user=_recipient_user('VE'))
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertEqual(call['to'], USDT_BSC)
        self.assertTrue(call['data'][2:].startswith(SEL_TRANSFER))
        self.assertEqual(int(call['data'][74:138], 16), 10 * WAD)
        self.assertEqual(json.loads(row['bsc_calls_json'])['kind'], 'send_usdt')

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

    @override_settings(BSC_SEND_ENABLED=False)
    def test_dark_flag_blocks(self):
        result, _, _ = self._prepare(recipient_user=_recipient_user('VE'))
        self.assertEqual(result['error'], 'bsc_send_disabled')

    # ── explicit token shapes (D/E) ─────────────────────────────────────

    def test_case_d_explicit_cusd_plus_to_external_never_redeems(self):
        result, row, pps = self._prepare(recipient_user=None, token='CUSD_PLUS')
        self.assertTrue(result['success'], result)
        call = result['calls'][0]
        self.assertEqual(call['to'], VAULT.lower())
        self.assertTrue(call['data'][2:].startswith(SEL_TRANSFER))
        self.assertEqual(call['data'][10:74], RECIPIENT[2:].lower().rjust(64, '0'))
        self.assertEqual(result['token_type'], 'CUSD_PLUS')
        self.assertEqual(json.loads(row['bsc_calls_json'])['kind'], 'send_cusd_plus')
        self.assertEqual(int(call['data'][74:138], 16), (10 * WAD * WAD) // pps)

    def test_case_d_ineligible_recipient_still_gets_the_token(self):
        result, _, _ = self._prepare(
            recipient_user=_recipient_user('US'), token='CUSD_PLUS')
        self.assertTrue(result['success'], result)
        self.assertTrue(result['calls'][0]['data'][2:].startswith(SEL_TRANSFER))
        self.assertEqual(result['token_type'], 'CUSD_PLUS')

    def test_case_d_never_falls_back_to_usdt(self):
        # Plenty of wallet USDT can NOT fund an explicit cUSD+ send.
        result, _, _ = self._prepare(
            shares_value=0, usdt=100 * WAD, token='CUSD_PLUS')
        self.assertEqual(result['error'], 'insufficient_balance')

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

    def test_case_e_unconfigured_token_blocks(self):
        result, _, _ = self._prepare(recipient_user=None, token='CONFIO')
        self.assertEqual(result['error'], 'confio_not_configured')

    def test_unknown_token_rejected(self):
        result, _, _ = self._prepare(recipient_user=None, token='DOGE')
        self.assertEqual(result['error'], 'unsupported_token')


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


class RecipientResolutionTests(SimpleTestCase):
    def test_invalid_evm_address_rejected(self):
        _, _, _, err = bsc_flow._resolve_recipient(None, None, '0x1234')
        self.assertEqual(err, 'invalid_recipient_address')

    def test_nothing_supplied(self):
        _, _, _, err = bsc_flow._resolve_recipient(None, None, None)
        self.assertEqual(err, 'recipient_required')


@override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT, BSC_SEND_ENABLED=True)
class IdempotencyTests(SimpleTestCase):
    """A reused idempotency key REPLAYS only when the request matches the
    stored row; different params → conflict, never the stale calls (P3)."""

    def _existing(self, amount='10', token_type='USDT', recipient_addr=RECIPIENT, ruid=2):
        return SimpleNamespace(
            internal_id='old123',
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

    def _run(self, batch_status='confirmed'):
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
                                kind='send_cusd_plus', source_id=s.id)
        movements = []
        with mock.patch('send.models.SendTransaction.objects') as sobjs, \
             mock.patch('cusd_plus.models.SponsoredBatch.objects') as bobjs, \
             mock.patch.object(send_tasks, '_account_for_bsc_address',
                               side_effect=lambda a: SimpleNamespace(addr=a)), \
             mock.patch.object(send_tasks, '_movement',
                               side_effect=lambda *a, **k: movements.append(a)), \
             mock.patch.object(send_tasks, '_notify_send_parties') as notify:
            sobjs.get.return_value = s
            bobjs.get.return_value = batch
            send_tasks.confirm_bsc_send(7, 9)
        return s, movements, notify

    def test_confirmed_writes_both_sides_and_notifies(self):
        s, movements, notify = self._run('confirmed')
        self.assertEqual(s.status, 'CONFIRMED')
        self.assertEqual(len(movements), 2)  # sender out + recipient in
        notify.assert_called_once()

    def test_reverted_fails_without_ledger(self):
        s, movements, notify = self._run('reverted')
        self.assertEqual(s.status, 'FAILED')
        self.assertEqual(movements, [])
        notify.assert_not_called()
