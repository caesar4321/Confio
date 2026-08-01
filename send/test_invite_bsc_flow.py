"""
BSC invite escrow flow (send/invite_bsc_flow.py) — batch shape + validator.
RPC/KMS mocked, house style.

    myvenv/bin/python manage.py test send.test_invite_bsc_flow
"""
from decimal import Decimal

from django.test import SimpleTestCase, override_settings

from cusd_plus.sponsor_7702 import PolicyError, SEL_APPROVE
from send import invite_bsc_flow as f

ESCROW = '0x' + 'ee' * 20
VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'
CONFIO = '0xCcEb3F6127FA9160a26A1B85857Ca4C9D56B3fa8'
WAD = 10 ** 18


@override_settings(
    BSC_INVITE_ESCROW_ADDRESS=ESCROW,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    BSC_CONFIO_TOKEN_ADDRESS=CONFIO,
    BSC_INVITE_ENABLED=True,
)
class InviteBatchTests(SimpleTestCase):
    def test_invite_id_is_deterministic(self):
        a = f.invite_id_bytes32('58:412555')
        b = f.invite_id_bytes32('58:412555')
        c = f.invite_id_bytes32('57:300111')
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.startswith('0x') and len(a) == 66)

    def test_create_batch_shape_cusd_plus(self):
        inv = f.invite_id_bytes32('58:412555')
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
        inv = f.invite_id_bytes32('58:412555')
        calls = f.build_create_calls('CONFIO', 20 * WAD, inv)
        self.assertEqual(calls[0]['to'], CONFIO.lower())
        self.assertEqual(calls[1]['data'][74:138], CONFIO[2:].lower().rjust(64, '0'))

    def test_validator_accepts_matching_batch(self):
        inv = f.invite_id_bytes32('58:412555')
        calls = f.build_create_calls('CUSD_PLUS', 5 * WAD, inv)
        f._validate_create_batch(calls, 'CUSD_PLUS', inv)

    def test_validator_rejects_amount_mismatch(self):
        inv = f.invite_id_bytes32('58:412555')
        calls = f.build_create_calls('CUSD_PLUS', 5 * WAD, inv)
        # approve 5, but create 6 → residual allowance; reject
        bad = f.build_create_calls('CUSD_PLUS', 6 * WAD, inv)
        mixed = [calls[0], bad[1]]
        with self.assertRaises(PolicyError):
            f._validate_create_batch(mixed, 'CUSD_PLUS', inv)

    def test_validator_rejects_wrong_invite_id(self):
        inv = f.invite_id_bytes32('58:412555')
        other = f.invite_id_bytes32('57:300111')
        calls = f.build_create_calls('CUSD_PLUS', 5 * WAD, inv)
        with self.assertRaises(PolicyError):
            f._validate_create_batch(calls, 'CUSD_PLUS', other)

    def test_validator_rejects_foreign_token(self):
        inv = f.invite_id_bytes32('58:412555')
        calls = f.build_create_calls('CUSD_PLUS', 5 * WAD, inv)
        alien = '0x' + 'ab' * 20
        calls[0]['to'] = alien
        calls[1]['data'] = ('0x' + calls[1]['data'][2:74]
                            + alien[2:].rjust(64, '0') + calls[1]['data'][138:])
        with self.assertRaises(PolicyError):
            f._validate_create_batch(calls, 'CUSD_PLUS', inv)

    def test_reclaim_batch_shape(self):
        inv = f.invite_id_bytes32('58:412555')
        calls = f.build_reclaim_calls(inv)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['to'], ESCROW.lower())
        self.assertEqual(calls[0]['data'][2:10], f.SEL_RECLAIM)
        self.assertEqual(calls[0]['data'][10:74], inv[2:])

    def test_unescrowable_token_rejected(self):
        with self.assertRaises(ValueError):
            f.build_create_calls('USDT', 5 * WAD, f.invite_id_bytes32('58:1'))

    @override_settings(BSC_INVITE_ENABLED=False)
    def test_disabled_flag(self):
        self.assertFalse(f._enabled())


from types import SimpleNamespace
from unittest import mock


class ReclaimConfirmTests(SimpleTestCase):
    """confirm_bsc_invite_reclaim finalizes 'reclaiming' only on a confirmed
    batch; a failed reclaim returns the invite to 'pending' (audit P3)."""

    def _run(self, batch_status, kind='invite_reclaim', source_id=3):
        from send import invite_tasks
        invite = SimpleNamespace(pk=3, status='reclaiming', save=mock.Mock())
        batch = SimpleNamespace(id=9, status=batch_status, kind=kind,
                                source_id=source_id, tx_hash='0x' + 'ab' * 32)
        with mock.patch('send.models.PhoneInvite.objects') as iobjs, \
             mock.patch('blockchain.models.SponsoredBatch.objects') as bobjs:
            iobjs.get.return_value = invite
            bobjs.get.return_value = batch
            invite_tasks.confirm_bsc_invite_reclaim(3, 9)
        return invite

    def test_confirmed_marks_reclaimed(self):
        invite = self._run('confirmed')
        self.assertEqual(invite.status, 'reclaimed')

    def test_reverted_returns_to_pending(self):
        invite = self._run('reverted')
        self.assertEqual(invite.status, 'pending')

    def test_dropped_returns_to_pending(self):
        invite = self._run('dropped')
        self.assertEqual(invite.status, 'pending')

    def test_wrong_source_refuses_to_settle(self):
        invite = self._run('confirmed', source_id=999)
        self.assertEqual(invite.status, 'reclaiming')  # untouched
        invite.save.assert_not_called()
