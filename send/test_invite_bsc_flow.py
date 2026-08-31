"""
BSC invite escrow flow (send/invite_bsc_flow.py) — batch shape + validator.
RPC/KMS mocked, house style.

    myvenv/bin/python manage.py test send.test_invite_bsc_flow
"""
import json
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from cusd_plus.sponsor_7702 import PolicyError, SEL_APPROVE
from send import invite_bsc_flow as f

ESCROW = '0x' + 'ee' * 20
VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'
CONFIO = '0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8'
CUSD = '0x' + 'dd' * 20
INVITER = '0x' + '11' * 20
INVITER2 = '0x' + '22' * 20
WAD = 10 ** 18


@override_settings(
    BSC_INVITE_ESCROW_ADDRESS=ESCROW,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    CUSD_VAULT_ADDRESS=CUSD,
    BSC_CONFIO_TOKEN_ADDRESS=CONFIO,
    BSC_INVITE_ENABLED=True,
)
class InviteBatchTests(SimpleTestCase):
    def test_invite_id_is_deterministic(self):
        a = f.invite_id_bytes32('58:412555', INVITER)
        b = f.invite_id_bytes32('58:412555', INVITER)
        c = f.invite_id_bytes32('57:300111', INVITER)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.startswith('0x') and len(a) == 66)

    def test_invite_id_case_insensitive_in_inviter(self):
        self.assertEqual(f.invite_id_bytes32('58:412555', INVITER),
                         f.invite_id_bytes32('58:412555', INVITER.upper()))

    def test_two_inviters_same_phone_get_distinct_ids(self):
        """PhoneInvite.invitation_id is unique, so a phone-only id would make
        the second inviter collide on insert — the escrow namespaces by
        (inviter, inviteId) precisely so both can coexist."""
        self.assertNotEqual(f.invite_id_bytes32('58:412555', INVITER),
                            f.invite_id_bytes32('58:412555', INVITER2))

    def test_create_batch_shape_cusd_plus(self):
        inv = f.invite_id_bytes32('58:412555', INVITER)
        calls = f.build_create_calls('CUSD_PLUS', 5 * WAD, inv)
        self.assertEqual(len(calls), 2)
        # approve(escrow, amount) on the vault token
        self.assertEqual(calls[0]['to'], VAULT.lower())
        self.assertEqual(calls[0]['data'][2:10], SEL_APPROVE)
        self.assertEqual(calls[0]['data'][10:74], ESCROW[2:].rjust(64, '0'))
        self.assertEqual(int(calls[0]['data'][74:138], 16), 5 * WAD)
        # createInvitation(inviteId, token, amount) on the escrow
        self.assertEqual(calls[1]['to'], ESCROW.lower())
        self.assertEqual(calls[1]['data'][10:74], inv[2:])
        self.assertEqual(calls[1]['data'][74:138], VAULT[2:].lower().rjust(64, '0'))
        self.assertEqual(int(calls[1]['data'][138:202], 16), 5 * WAD)

    def test_create_batch_confio(self):
        inv = f.invite_id_bytes32('58:412555', INVITER)
        calls = f.build_create_calls('CONFIO', 20 * WAD, inv)
        self.assertEqual(calls[0]['to'], CONFIO.lower())
        self.assertEqual(calls[1]['data'][74:138], CONFIO[2:].lower().rjust(64, '0'))

    def test_create_batch_cusd(self):
        inv = f.invite_id_bytes32('55:119999', INVITER)
        calls = f.build_create_calls('CUSD', 7 * WAD, inv)
        self.assertEqual(calls[0]['to'], CUSD.lower())
        self.assertEqual(calls[1]['data'][74:138], CUSD[2:].lower().rjust(64, '0'))

    def test_validator_accepts_matching_batch(self):
        inv = f.invite_id_bytes32('58:412555', INVITER)
        calls = f.build_create_calls('CUSD_PLUS', 5 * WAD, inv)
        f._validate_create_batch(calls, 'CUSD_PLUS', inv)

    def test_validator_rejects_amount_mismatch(self):
        inv = f.invite_id_bytes32('58:412555', INVITER)
        calls = f.build_create_calls('CUSD_PLUS', 5 * WAD, inv)
        # approve 5, but create 6 → residual allowance; reject
        bad = f.build_create_calls('CUSD_PLUS', 6 * WAD, inv)
        mixed = [calls[0], bad[1]]
        with self.assertRaises(PolicyError):
            f._validate_create_batch(mixed, 'CUSD_PLUS', inv)

    def test_validator_rejects_wrong_invite_id(self):
        inv = f.invite_id_bytes32('58:412555', INVITER)
        other = f.invite_id_bytes32('57:300111', INVITER)
        calls = f.build_create_calls('CUSD_PLUS', 5 * WAD, inv)
        with self.assertRaises(PolicyError):
            f._validate_create_batch(calls, 'CUSD_PLUS', other)

    def test_validator_rejects_foreign_token(self):
        inv = f.invite_id_bytes32('58:412555', INVITER)
        calls = f.build_create_calls('CUSD_PLUS', 5 * WAD, inv)
        alien = '0x' + 'ab' * 20
        calls[0]['to'] = alien
        calls[1]['data'] = ('0x' + calls[1]['data'][2:74]
                            + alien[2:].rjust(64, '0') + calls[1]['data'][138:])
        with self.assertRaises(PolicyError):
            f._validate_create_batch(calls, 'CUSD_PLUS', inv)

    def test_reclaim_batch_shape(self):
        inv = f.invite_id_bytes32('58:412555', INVITER)
        calls = f.build_reclaim_calls(inv)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['to'], ESCROW.lower())
        self.assertEqual(calls[0]['data'][2:10], f.SEL_RECLAIM)
        self.assertEqual(calls[0]['data'][10:74], inv[2:])

    def test_unescrowable_token_rejected(self):
        with self.assertRaises(ValueError):
            f.build_create_calls('USDT', 5 * WAD, f.invite_id_bytes32('58:1', INVITER))

    @mock.patch('cusd_plus.vault.p_plus_wad', return_value=11 * WAD // 10)
    def test_cusd_plus_display_dollars_are_converted_to_exact_shares(self, _pps):
        units = f._token_units_for_dollars('CUSD_PLUS', 10 * WAD)
        self.assertEqual(units, -(-10 * WAD * WAD // (11 * WAD // 10)))

    def test_locked_units_come_from_persisted_create_batch(self):
        inv = f.invite_id_bytes32('58:412555', INVITER)
        calls = f.build_create_calls('CUSD_PLUS', 7 * WAD, inv)
        invite = SimpleNamespace(
            amount=Decimal('999'),
            send_transaction=SimpleNamespace(
                bsc_calls_json=json.dumps({'calls': calls}),
            ),
        )
        self.assertEqual(f._locked_units(invite), 7 * WAD)

    @mock.patch('cusd_plus.vault.current_oracle_price_wad', return_value=105 * WAD // 100)
    def test_cusd_to_plus_claim_has_ondo_output_floor(self, _oracle):
        invite = SimpleNamespace(
            token_type='CUSD', amount=Decimal('10'), send_transaction=None,
        )
        expected_usdy = 10 * WAD * WAD // (105 * WAD // 100)
        self.assertEqual(
            f._claim_min_amount_out(invite, True),
            expected_usdy * f.INTERNAL_CONVERSION_MIN_OUT_BPS // 10_000,
        )

    @mock.patch('cusd_plus.vault.last_oracle_price_wad', return_value=WAD)
    @mock.patch('cusd_plus.vault.p_plus_wad', return_value=11 * WAD // 10)
    def test_plus_to_cusd_claim_has_redeem_output_floor(self, _pps, _oracle):
        invite = SimpleNamespace(
            token_type='CUSD_PLUS', amount=Decimal('10'), send_transaction=None,
        )
        predicted = 11 * WAD
        self.assertEqual(
            f._claim_min_amount_out(invite, False),
            predicted * f.INTERNAL_CONVERSION_MIN_OUT_BPS // 10_000,
        )

    @override_settings(BSC_INVITE_ENABLED=False)
    def test_disabled_flag(self):
        self.assertFalse(f._enabled())



class _CasObjects:
    """Stand-in for a Django manager where the tests care about the
    compare-and-set UPDATEs, not the ORM.

    Every transition in invite_tasks is `filter(pk=…, status=EXPECTED).update(
    status=NEW)`, and whether it matched is the whole point: a task that loses
    the race must do nothing. `wins` decides that, and `updates` records what
    each caller tried to write so a test can assert the intended transition
    without a database (the local test DB is unavailable — pgvector)."""

    def __init__(self, get_return=None, wins=True):
        self._get_return = get_return
        self._wins = wins
        self.updates = []

    def get(self, *a, **kw):
        return self._get_return

    def select_related(self, *a, **kw):
        return self

    def filter(self, **criteria):
        outer = self

        class _QS:
            def update(self, **values):
                outer.updates.append((criteria, values))
                return 1 if outer._wins else 0

            def exists(self):
                return False
        return _QS()

    def statuses_written(self):
        return [v.get('status') for _, v in self.updates if 'status' in v]


class CreateConfirmTests(SimpleTestCase):
    """confirm_bsc_invite_create settles a create from its batch. 'creating' is
    the in-flight state; only a confirmed batch means the escrow holds money."""

    def _run(self, batch_status, kind='invite_create', source_id=3, wins=True,
             status='creating'):
        from send import invite_tasks
        send_tx = SimpleNamespace(pk=7, transaction_hash='0x' + 'ab' * 32,
                                  status='SUBMITTED', error_message='',
                                  invitation_expires_at=None, save=mock.Mock())
        invite = SimpleNamespace(pk=3, status=status, amount=5,
                                 token_type='CUSD_PLUS', phone_key='58:412555',
                                 inviter_user_id=1, send_transaction=send_tx,
                                 send_transaction_id=7)
        batch = SimpleNamespace(id=9, status=batch_status, kind=kind,
                                source_id=source_id, tx_hash='0x' + 'ab' * 32)
        iobjs = _CasObjects(get_return=invite, wins=wins)
        sobjs = _CasObjects()
        with mock.patch('send.models.PhoneInvite.objects', iobjs), \
             mock.patch('send.models.SendTransaction.objects', sobjs), \
             mock.patch('blockchain.models.SponsoredBatch.objects',
                        _CasObjects(get_return=batch)), \
             mock.patch('send.invite_tasks._claim_if_recipient_already_joined'):
            invite_tasks.confirm_bsc_invite_create(3, 9)
        return iobjs, send_tx

    def test_confirmed_funds_the_invite(self):
        iobjs, send_tx = self._run('confirmed')
        self.assertIn('pending', iobjs.statuses_written())
        self.assertEqual(send_tx.status, 'CONFIRMED')

    def test_expiry_is_dated_from_the_confirmation(self):
        """The contract starts its 7-day window at mining, so dating the
        off-chain clock from the broadcast exposed a reclaim button the escrow
        rejects as 'not expired'."""
        iobjs, send_tx = self._run('confirmed')
        _criteria, values = iobjs.updates[0]
        self.assertIsNotNone(values.get('expires_at'))
        self.assertIsNotNone(send_tx.invitation_expires_at)

    def test_history_is_saved_not_bulk_updated(self):
        """The unified history row is maintained by a post_save signal that a
        queryset update() does not fire."""
        _iobjs, send_tx = self._run('confirmed')
        send_tx.save.assert_called()

    def test_confirmed_transitions_only_from_creating(self):
        """CAS, not a blind write: the UPDATE must name the state it expects."""
        iobjs, _ = self._run('confirmed')
        criteria, _values = iobjs.updates[0]
        self.assertEqual(criteria.get('status'), 'creating')

    def test_reverted_marks_failed_not_reclaimed(self):
        """Nothing was ever returned to the inviter, so 'reclaimed' would be a
        lie — and it is the word the app renders as 'funds came back'."""
        iobjs, send_tx = self._run('reverted')
        self.assertIn('failed', iobjs.statuses_written())
        self.assertNotIn('reclaimed', iobjs.statuses_written())
        self.assertEqual(send_tx.status, 'FAILED')

    def test_losing_the_cas_touches_nothing_downstream(self):
        """Another worker already settled it — this task must not also write
        the send row."""
        _iobjs, send_tx = self._run('confirmed', wins=False)
        send_tx.save.assert_not_called()

    def test_foreign_batch_refuses_to_settle(self):
        iobjs, _ = self._run('confirmed', source_id=999)
        self.assertEqual(iobjs.updates, [])

    def test_wrong_kind_refuses_to_settle(self):
        iobjs, _ = self._run('confirmed', kind='send_cusd_plus')
        self.assertEqual(iobjs.updates, [])

    def test_already_resolved_is_a_noop(self):
        iobjs, _ = self._run('confirmed', status='pending')
        self.assertEqual(iobjs.updates, [])


class ClaimConfirmTests(SimpleTestCase):
    """confirm_bsc_invite_claim settles a claim from its RECEIPT. A claim is a
    plain KMS tx with no SponsoredBatch, so the receipt is the only evidence —
    and booking 'claimed' off the broadcast is how a dropped claim leaves the
    invitee with nothing and the inviter unable to reclaim."""

    TX = '0x' + 'cd' * 32

    def _run(self, receipt, status='claiming'):
        from send import invite_tasks
        send_tx = SimpleNamespace(pk=7, invitation_claimed=False, save=mock.Mock())
        invite = SimpleNamespace(pk=3, status=status, send_transaction_id=7,
                                 send_transaction=send_tx)
        iobjs = _CasObjects(get_return=invite)

        # The claim only settles on a FINALIZED, still-canonical block, so the
        # RPC stub has to answer the finality questions too.
        def _rpc(method, params):
            if method == 'eth_getTransactionReceipt':
                return receipt
            if method == 'eth_getTransactionByHash':
                return {'hash': self.TX}
            if method == 'eth_getBlockByNumber':
                return {'hash': '0xbb'}
            raise AssertionError(method)

        with mock.patch('send.models.PhoneInvite.objects', iobjs), \
             mock.patch('cusd_plus.sponsor_7702._rpc', side_effect=_rpc), \
             mock.patch('cusd_plus.tasks._finalized_block_number', return_value=0x999):
            invite_tasks.confirm_bsc_invite_claim(3, self.TX)
        return iobjs, send_tx

    def test_successful_receipt_claims(self):
        iobjs, send_tx = self._run({'status': '0x1', 'blockNumber': '0x64', 'blockHash': '0xbb'})
        self.assertIn('claimed', iobjs.statuses_written())
        self.assertTrue(send_tx.invitation_claimed)

    def test_reverted_receipt_returns_to_pending(self):
        iobjs, send_tx = self._run({'status': '0x0', 'blockNumber': '0x64', 'blockHash': '0xbb'})
        self.assertIn('pending', iobjs.statuses_written())
        self.assertNotIn('claimed', iobjs.statuses_written())
        # The history row must NOT say claimed — the invitee got nothing.
        self.assertFalse(send_tx.invitation_claimed)
        send_tx.save.assert_not_called()

    def test_reverted_receipt_clears_the_claimant(self):
        """Leaving claimed_by set on a reverted claim would show the inviter a
        recipient who never received anything."""
        iobjs, _ = self._run({'status': '0x0', 'blockNumber': '0x64', 'blockHash': '0xbb'})
        _criteria, values = iobjs.updates[0]
        self.assertIsNone(values.get('claimed_by'))

    def test_already_resolved_is_a_noop(self):
        iobjs, send_tx = self._run({'status': '0x1', 'blockNumber': '0x64', 'blockHash': '0xbb'}, status='claimed')
        self.assertEqual(iobjs.updates, [])
        send_tx.save.assert_not_called()


class ReclaimConfirmTests(SimpleTestCase):
    """confirm_bsc_invite_reclaim finalizes 'reclaiming' only on a confirmed
    batch; a failed reclaim returns the invite to 'pending' (audit P3)."""

    def _run(self, batch_status, kind='invite_reclaim', source_id=3, wins=True):
        from send import invite_tasks
        send_tx = SimpleNamespace(invitation_reverted=False, save=mock.Mock())
        invite = SimpleNamespace(pk=3, status='reclaiming', send_transaction=send_tx)
        batch = SimpleNamespace(id=9, status=batch_status, kind=kind,
                                source_id=source_id, tx_hash='0x' + 'ab' * 32)
        iobjs = _CasObjects(get_return=invite, wins=wins)
        with mock.patch('send.models.PhoneInvite.objects', iobjs), \
             mock.patch('blockchain.models.SponsoredBatch.objects',
                        _CasObjects(get_return=batch)):
            invite_tasks.confirm_bsc_invite_reclaim(3, 9)
        return iobjs, send_tx

    def test_confirmed_marks_reclaimed(self):
        iobjs, send_tx = self._run('confirmed')
        self.assertIn('reclaimed', iobjs.statuses_written())
        self.assertTrue(send_tx.invitation_reverted)

    def test_reverted_returns_to_pending(self):
        iobjs, _ = self._run('reverted')
        self.assertIn('pending', iobjs.statuses_written())

    def test_dropped_returns_to_pending(self):
        iobjs, _ = self._run('dropped')
        self.assertIn('pending', iobjs.statuses_written())

    def test_losing_to_a_claim_does_not_report_funds_returned(self):
        """A claim confirmer got there first. Writing 'reclaimed' over it would
        tell the inviter their money came back while the invitee holds it."""
        _iobjs, send_tx = self._run('confirmed', wins=False)
        self.assertFalse(send_tx.invitation_reverted)
        send_tx.save.assert_not_called()

    def test_wrong_source_refuses_to_settle(self):
        iobjs, _ = self._run('confirmed', source_id=999)
        self.assertEqual(iobjs.updates, [])


class RailDiscriminationTests(SimpleTestCase):
    """Two invite rails share the PhoneInvite table. Each side must select its
    own rows by the STATED rail — token_type cannot do it, because CONFIO
    exists on both (Codex audit 2026-08-02 P2)."""

    def test_bsc_autoclaim_filters_on_rail(self):
        from send import invite_bsc_flow
        captured = {}

        class _QS(list):
            def exclude(self, **kw):
                captured['exclude'] = kw
                return self

        def _filter(**kw):
            captured['filter'] = kw
            return _QS()

        with mock.patch('send.models.PhoneInvite.objects') as objs, \
             mock.patch.object(invite_bsc_flow, '_enabled', return_value=True):
            objs.filter.side_effect = _filter
            invite_bsc_flow.claim_pending_bsc_invites(SimpleNamespace(pk=1), '58:412555')
        self.assertEqual(captured['filter'].get('rail'), 'bsc')
        # Second, independent condition: one mislabelled field must not be
        # enough to hand a row to the wrong sponsor.
        self.assertEqual(captured['exclude'], {'inviter_address': ''})

    def test_algorand_lookups_filter_on_rail(self):
        """The Algorand fallback used to select on phone_key alone, so it could
        pick up a BSC row and pass its 64-hex escrow id to the box API."""
        import pathlib
        import re
        src = pathlib.Path('blockchain/invite_send_mutations.py').read_text()
        for match in re.finditer(r'PhoneInvite\.objects\.filter\((.*?)\)', src, re.S):
            body = match.group(1)
            if 'phone_key' in body:
                self.assertIn("rail='algorand'", body,
                              'a phone_key lookup that does not state its rail')


class ClaimRetryTests(SimpleTestCase):
    """A one-shot auto-claim left money escrowed for a week whenever the
    sponsor happened to be busy at the moment the invitee verified."""

    def _schedule(self, error):
        from send import invite_bsc_flow
        with mock.patch('send.invite_tasks.retry_bsc_invite_claim') as task:
            invite_bsc_flow._retry_claim_later(
                SimpleNamespace(pk=3, invitation_id='ab' * 32),
                SimpleNamespace(pk=7), error)
            return task.apply_async.called

    def test_transient_failures_are_retried(self):
        for err in ('sponsor_busy', 'gas_price_too_high', 'exception'):
            with self.subTest(err=err):
                self.assertTrue(self._schedule(err))

    def test_unmined_create_is_retried(self):
        """simulation_reverted usually means the create has not landed yet —
        the one case that fixes itself."""
        self.assertTrue(self._schedule('simulation_reverted'))

    def test_permanent_failures_are_not_retried(self):
        for err in ('recipient_is_inviter', 'missing_bsc_address',
                    'bsc_invite_disabled', 'invite_not_pending'):
            with self.subTest(err=err):
                self.assertFalse(self._schedule(err))


@override_settings(
    BSC_INVITE_ESCROW_ADDRESS=ESCROW,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    BSC_CONFIO_TOKEN_ADDRESS=CONFIO,
    BSC_INVITE_ENABLED=True,
    BSC_CHAIN_ID=56,
)
class SubmitDoesNotStrandTheRowTests(SimpleTestCase):
    """No submit path may take the row and then return without releasing it.

    'authorization_required' is not an edge case — it is what EVERY first-ever
    invite gets, so the client can attach its 7702 authorization and retry.
    Taking the row before that return abandoned it: create broke first-use
    invites outright, and reclaim stranded FUNDED escrow with no batch and no
    confirmer (Codex follow-up audit 2026-08-02 P1).
    """

    def _invite(self, status):
        return SimpleNamespace(
            pk=3, inviter_user_id=1, status=status,
            inviter_address=INVITER, invitation_id='ab' * 32,
            amount=Decimal('5'), token_type='CUSD_PLUS',
            send_transaction=SimpleNamespace(
                pk=7, status='PENDING', save=mock.Mock()),
            send_transaction_id=7, save=mock.Mock())

    def _submit(self, which, delegated, authorization, signer_addr=INVITER):
        from send import invite_bsc_flow as flow
        invite = self._invite('draft' if which == 'create' else 'pending')
        objs = _CasObjects()
        deadline = str(int(time.time()) + 600)
        with mock.patch('send.models.PhoneInvite.objects', objs), \
             mock.patch('cusd_plus.sponsor_7702.intent_id_for', return_value='0x' + '00' * 32), \
             mock.patch('cusd_plus.sponsor_7702.intent_digest', return_value=b'\x00' * 32), \
             mock.patch('cusd_plus.sponsor_7702.recover_intent_signer', return_value=signer_addr), \
             mock.patch('cusd_plus.sponsor_7702.is_delegated', return_value=delegated), \
             mock.patch('cusd_plus.sponsor_7702.send_sponsored_batch') as send_batch:
            send_batch.side_effect = AssertionError('must not broadcast')
            fn = flow.submit_create if which == 'create' else flow.submit_reclaim
            res = fn(SimpleNamespace(id=1), invite, '0', deadline, '0xsig',
                     authorization)
        return res, objs

    def test_create_authorization_required_leaves_the_row_alone(self):
        res, objs = self._submit('create', delegated=False, authorization=None)
        self.assertTrue(res.get('authorization_required'))
        self.assertEqual(objs.statuses_written(), [],
                         'the row must still be draft for the retry to find it')

    def test_reclaim_authorization_required_leaves_the_row_alone(self):
        res, objs = self._submit('reclaim', delegated=False, authorization=None)
        self.assertTrue(res.get('authorization_required'))
        self.assertEqual(objs.statuses_written(), [],
                         'a funded escrow must not be stranded in reclaiming')

    def test_create_bad_signature_leaves_the_row_alone(self):
        res, objs = self._submit('create', delegated=True, authorization=None,
                                 signer_addr='0x' + 'ff' * 20)
        self.assertEqual(res.get('error'), 'bad_intent_signature')
        self.assertEqual(objs.statuses_written(), [])

    def test_reclaim_bad_signature_leaves_the_row_alone(self):
        res, objs = self._submit('reclaim', delegated=True, authorization=None,
                                 signer_addr='0x' + 'ff' * 20)
        self.assertEqual(res.get('error'), 'bad_intent_signature')
        self.assertEqual(objs.statuses_written(), [])


class RecycleFailedInviteTests(SimpleTestCase):
    """A create that never executed leaves the escrow's mapping slot EMPTY, so
    its deterministic id is still usable. Only claimed/reclaimed are spent."""

    def test_only_settled_states_are_spent(self):
        from send import invite_bsc_flow as flow
        import inspect
        src = inspect.getsource(flow.prepare_create)
        self.assertIn("not in ('draft', 'failed')", src)
        self.assertIn("in ('claimed', 'reclaimed')", src)
        self.assertNotIn("'claimed', 'reclaimed', 'failed'", src)


class NonceLockOwnershipTests(SimpleTestCase):
    """release_sponsor_nonce_lock() with no token is the legacy unconditional
    delete: a holder whose 15s TTL lapsed can drop a NEWER holder's lock and
    let two sponsor transactions sign the same nonce."""

    def test_claim_passes_its_ownership_token(self):
        from send import invite_bsc_flow as flow
        import inspect
        src = inspect.getsource(flow.claim_for_recipient)
        self.assertIn('lock_token = acquire_sponsor_nonce_lock()', src)
        self.assertIn('release_sponsor_nonce_lock(lock_token)', src)


class ClaimRevalidatesPhoneOwnershipTests(SimpleTestCase):
    """Claims run asynchronously (post-create, retry task), and a phone can move
    between accounts in between. Ownership is rechecked at signing time."""

    def test_changed_phone_is_refused(self):
        from send import invite_bsc_flow as flow
        invite = SimpleNamespace(pk=3, status='pending', phone_key='58:412555',
                                 inviter_address=INVITER, invitation_id='ab' * 32)
        recipient = SimpleNamespace(pk=9, phone_key='58:999999')
        with mock.patch.object(flow, '_enabled', return_value=True):
            res = flow.claim_for_recipient(invite, recipient)
        self.assertEqual(res.get('error'), 'recipient_phone_changed')


@override_settings(BSC_INVITE_RECONCILE_GRACE_MIN=5)
class ReconcileBscInvitesTests(SimpleTestCase):
    """Every leg takes its row before broadcasting, so a process that dies
    between the take and the enqueue leaves a row nobody is watching. The
    reconciler is the second chance — it never decides an outcome itself."""

    def _run(self, invites_by_status, batch=None):
        from send import invite_tasks

        def _invite_filter(**kw):
            return list(invites_by_status.get(kw.get('status'), []))

        objs = mock.Mock()
        objs.filter.side_effect = lambda **kw: mock.Mock(
            order_by=lambda *a: _Sliceable(_invite_filter(**kw)))
        bobjs = mock.Mock()
        bobjs.filter.return_value.order_by.return_value.first.return_value = batch
        with mock.patch('send.models.PhoneInvite.objects', objs), \
             mock.patch('blockchain.models.SponsoredBatch.objects', bobjs), \
             mock.patch('send.invite_tasks._release_stuck') as release, \
             mock.patch.object(invite_tasks.confirm_bsc_invite_create, 'apply_async') as c_create, \
             mock.patch.object(invite_tasks.confirm_bsc_invite_reclaim, 'apply_async') as c_reclaim, \
             mock.patch.object(invite_tasks.confirm_bsc_invite_claim, 'apply_async') as c_claim:
            out = invite_tasks.reconcile_bsc_invites()
        return out, release, c_create, c_reclaim, c_claim

    def test_create_with_no_batch_is_released(self):
        """send_sponsored_batch writes its row BEFORE broadcasting, so no row
        means nothing was ever signed."""
        inv = SimpleNamespace(pk=3, claimed_txid='', send_transaction_id=7)
        out, release, *_ = self._run({'creating': [inv]}, batch=None)
        release.assert_called_once()
        self.assertEqual(out['released'], 1)

    def test_create_with_live_batch_is_left_alone(self):
        """reconcile_signed_batches and the receipt task own an in-flight batch."""
        inv = SimpleNamespace(pk=3, claimed_txid='', send_transaction_id=7)
        batch = SimpleNamespace(id=9, status='sent')
        out, release, c_create, *_ = self._run({'creating': [inv]}, batch=batch)
        release.assert_not_called()
        c_create.assert_not_called()
        self.assertEqual(out, {'redriven': 0, 'released': 0})

    def test_terminal_batch_redrives_the_confirmer(self):
        """A settled batch with an unsettled row means the domain confirm never
        ran or never finished."""
        inv = SimpleNamespace(pk=3, claimed_txid='', send_transaction_id=7)
        batch = SimpleNamespace(id=9, status='confirmed')
        out, _release, c_create, *_ = self._run({'creating': [inv]}, batch=batch)
        c_create.assert_called_once()
        self.assertEqual(c_create.call_args.kwargs['args'], [3, 9])
        self.assertEqual(out['redriven'], 1)

    def test_reclaiming_redrives_its_own_confirmer(self):
        inv = SimpleNamespace(pk=4, claimed_txid='', send_transaction_id=8)
        batch = SimpleNamespace(id=11, status='reverted')
        out, _r, c_create, c_reclaim, _c = self._run({'reclaiming': [inv]}, batch=batch)
        c_reclaim.assert_called_once()
        c_create.assert_not_called()
        self.assertEqual(out['redriven'], 1)

    def test_claim_without_a_hash_is_released(self):
        """The hash is written right after signing and before broadcasting, so
        no hash means nothing was signed."""
        inv = SimpleNamespace(pk=5, claimed_txid='', send_transaction_id=9)
        out, release, *_ = self._run({'claiming': [inv]})
        release.assert_called_once()
        self.assertEqual(out['released'], 1)

    def test_claim_with_a_hash_is_redriven_never_released(self):
        """A signed claim may still mine. Releasing the slot would let it be
        claimed or reclaimed twice."""
        inv = SimpleNamespace(pk=5, claimed_txid='0x' + 'cd' * 32, send_transaction_id=9)
        out, release, _cc, _cr, c_claim = self._run({'claiming': [inv]})
        release.assert_not_called()
        c_claim.assert_called_once()
        self.assertEqual(out['redriven'], 1)

    def test_release_targets_are_the_resting_states(self):
        from send.invite_tasks import _RELEASE_TARGET
        self.assertEqual(_RELEASE_TARGET,
                         {'creating': 'draft', 'claiming': 'pending',
                          'reclaiming': 'pending'})


class _Sliceable(list):
    def __getitem__(self, item):
        res = list.__getitem__(self, item)
        return _Sliceable(res) if isinstance(item, slice) else res


class ClaimFinalityTests(SimpleTestCase):
    """A receipt is not a settlement. Booking 'claimed' before finality lets a
    reorg leave the DB paid while the escrow is still funded."""

    TX = '0x' + 'cd' * 32

    def _run(self, receipt, finalized=None, head=None, canonical_hash='0xbb',
             known=True):
        from send import invite_tasks
        invite = SimpleNamespace(pk=3, status='claiming', send_transaction_id=7,
                                 send_transaction=SimpleNamespace(
                                     invitation_claimed=False, save=mock.Mock()))
        iobjs = _CasObjects(get_return=invite)

        def _rpc(method, params):
            if method == 'eth_getTransactionReceipt':
                return receipt
            if method == 'eth_getTransactionByHash':
                return {'hash': self.TX} if known else None
            if method == 'eth_blockNumber':
                return hex(head or 0)
            if method == 'eth_getBlockByNumber':
                return {'hash': canonical_hash}
            raise AssertionError(method)

        with mock.patch('send.models.PhoneInvite.objects', iobjs), \
             mock.patch('cusd_plus.sponsor_7702._rpc', side_effect=_rpc), \
             mock.patch('cusd_plus.tasks._finalized_block_number', return_value=finalized), \
             mock.patch('cusd_plus.tasks._finality_depth', return_value=15):
            try:
                invite_tasks.confirm_bsc_invite_claim(3, self.TX)
            except Exception as exc:  # Retry is raised as an exception
                return iobjs, type(exc).__name__
        return iobjs, None

    def test_unfinalized_block_does_not_settle(self):
        receipt = {'status': '0x1', 'blockNumber': '0x64', 'blockHash': '0xbb'}
        iobjs, raised = self._run(receipt, finalized=0x50)
        self.assertEqual(iobjs.statuses_written(), [])
        self.assertEqual(raised, 'Retry')

    def test_finalized_block_settles(self):
        receipt = {'status': '0x1', 'blockNumber': '0x64', 'blockHash': '0xbb'}
        iobjs, _ = self._run(receipt, finalized=0x70)
        self.assertIn('claimed', iobjs.statuses_written())

    def test_reorged_block_does_not_settle(self):
        """The receipt's block is no longer canonical at that height."""
        receipt = {'status': '0x1', 'blockNumber': '0x64', 'blockHash': '0xbb'}
        iobjs, raised = self._run(receipt, finalized=0x70, canonical_hash='0xdead')
        self.assertEqual(iobjs.statuses_written(), [])
        self.assertEqual(raised, 'Retry')

    def test_depth_fallback_when_no_finalized_tag(self):
        receipt = {'status': '0x1', 'blockNumber': '0x64', 'blockHash': '0xbb'}
        shallow, _ = self._run(receipt, finalized=None, head=0x66)
        self.assertEqual(shallow.statuses_written(), [])
        deep, _ = self._run(receipt, finalized=None, head=0x100)
        self.assertIn('claimed', deep.statuses_written())

    def test_reverted_receipt_releases_immediately(self):
        receipt = {'status': '0x0', 'blockNumber': '0x64', 'blockHash': '0xbb'}
        iobjs, _ = self._run(receipt)
        self.assertIn('pending', iobjs.statuses_written())
