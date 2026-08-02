import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from django.contrib.auth import get_user_model

from presale.models import PresalePhase, PresalePurchase, PresaleSettings, PresaleMigrationCredit
from presale.tasks import (
    sync_presale_migration_credits,
    build_presale_credit_batch,
    verify_presale_migration_credits,
    CREDIT_MIGRATED_SELECTOR,
)
from users.models import Account

User = get_user_model()

VAULT = '0x00000000000000000000000000000000000000AA'
BSC_ADDR = '0xF29A418744E793973BF4eEc676F8a30B2793b623'


def _mk_user(username, bsc_address=None):
    user = User.objects.create(username=username, firebase_uid=f'uid-{username}')
    Account.objects.create(
        user=user,
        account_type='personal',
        account_index=0,
        bsc_address=bsc_address,
    )
    return user


class PresaleMigrationCreditPipelineTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.phase = PresalePhase.objects.create(
            phase_number=1,
            name='Fase 1',
            description='x',
            price_per_token=Decimal('0.2'),
            goal_amount=Decimal('1000000'),
        )

    def _purchase(self, user, confio, status='completed'):
        return PresalePurchase.objects.create(
            user=user,
            phase=self.phase,
            cusd_amount=Decimal('10'),
            confio_amount=Decimal(confio),
            price_per_token=Decimal('0.2'),
            status=status,
        )

    def test_sync_creates_rows_only_for_linked_users_and_sums(self):
        linked = _mk_user('linked', BSC_ADDR)
        unlinked = _mk_user('unlinked')
        self._purchase(linked, '100.5')
        self._purchase(linked, '49.5')
        self._purchase(linked, '999', status='failed')  # ignored
        self._purchase(unlinked, '77')

        res = sync_presale_migration_credits()
        self.assertEqual(res['created'], 1)
        self.assertEqual(res['awaiting_bsc_address'], 1)

        row = PresaleMigrationCredit.objects.get(user=linked)
        self.assertEqual(row.confio_amount, Decimal('150'))
        self.assertEqual(row.bsc_address, BSC_ADDR)
        self.assertEqual(row.status, 'pending')
        self.assertEqual(row.confio_base_units, 150 * 10**18)

        # idempotent: second run creates nothing new
        res2 = sync_presale_migration_credits()
        self.assertEqual(res2['created'], 0)
        self.assertEqual(PresaleMigrationCredit.objects.count(), 1)

        # user links later → picked up on next sync
        acct = unlinked.accounts.get(account_type='personal')
        acct.bsc_address = '0x' + 'b' * 40
        acct.save(update_fields=['bsc_address'])
        res3 = sync_presale_migration_credits()
        self.assertEqual(res3['created'], 1)

    @override_settings(BSC_PRESALE_VAULT_ADDRESS=VAULT)
    def test_batch_queues_rows_and_encodes_calldata(self):
        linked = _mk_user('linked', BSC_ADDR)
        self._purchase(linked, '150')
        sync_presale_migration_credits()

        res = build_presale_credit_batch()
        self.assertEqual(res['count'], 1)
        self.assertEqual(res['to'], VAULT)
        self.assertEqual(res['total_confio'], '150.000000')
        data = bytes.fromhex(res['data'][2:])
        self.assertEqual(data[:4], CREDIT_MIGRATED_SELECTOR)
        # address and 150e18 appear in the encoded tail
        self.assertIn(bytes.fromhex(BSC_ADDR[2:].lower()), data)
        self.assertIn((150 * 10**18).to_bytes(32, 'big'), data)

        row = PresaleMigrationCredit.objects.get(user=linked)
        self.assertEqual(row.status, 'queued')
        self.assertEqual(row.batch_id, res['batch_id'])

        # reprint is idempotent and does not re-queue
        reprint = build_presale_credit_batch(batch_id=res['batch_id'])
        self.assertEqual(reprint['data'], res['data'])

        # nothing pending left
        empty = build_presale_credit_batch()
        self.assertEqual(empty['count'], 0)

    def test_batch_requires_vault_setting(self):
        with override_settings(BSC_PRESALE_VAULT_ADDRESS=None):
            with self.assertRaises(RuntimeError):
                build_presale_credit_batch()

    @override_settings(BSC_PRESALE_VAULT_ADDRESS=VAULT)
    def test_verify_flips_to_credited_only_when_chain_confirms(self):
        linked = _mk_user('linked', BSC_ADDR)
        self._purchase(linked, '150')
        sync_presale_migration_credits()
        build_presale_credit_batch()

        # chain shows nothing yet (Safe hasn't executed)
        with mock.patch('cusd_plus.tasks._rpc', return_value='0x0'):
            res = verify_presale_migration_credits()
        self.assertEqual(res, {'verified': 0, 'still_pending': 1})
        self.assertEqual(PresaleMigrationCredit.objects.get(user=linked).status, 'queued')

        # chain confirms the full credit
        onchain = hex(150 * 10**18)
        with mock.patch('cusd_plus.tasks._rpc', return_value=onchain) as rpc:
            res = verify_presale_migration_credits()
            call_obj = rpc.call_args[0][1][0]
            self.assertEqual(call_obj['to'], VAULT)
        self.assertEqual(res['verified'], 1)
        row = PresaleMigrationCredit.objects.get(user=linked)
        self.assertEqual(row.status, 'credited')
        self.assertIsNotNone(row.credited_at)


@override_settings(BSC_PRESALE_VAULT_ADDRESS=VAULT, PRESALE_CHAIN='bsc')
class BscPurchaseFlowTest(TestCase):
    """presale/bsc_flow.py with the chain mocked (RPC-free).
    Run: myvenv/bin/python manage.py test presale.tests.BscPurchaseFlowTest
    (needs a Postgres with pgvector — EC2/prod tooling, not the laptop)."""

    @classmethod
    def setUpTestData(cls):
        PresaleSettings.get_settings()
        PresaleSettings.objects.update(is_presale_active=True)
        cls.phase = PresalePhase.objects.create(
            phase_number=1, name='Fase 1', description='x',
            price_per_token=Decimal('0.2'), goal_amount=Decimal('1000000'),
            status='active',
        )

    def setUp(self):
        self.user = _mk_user('buyer', BSC_ADDR)
        self.account = self.user.accounts.get(account_type='personal')

    def _prepare(self, amount='100', **kwargs):
        from presale import bsc_flow
        defaults = dict(accepted_terms=True, not_us_attestation=True)
        defaults.update(kwargs)
        # quoteTokens → 500 CONFIO, quoteCost → 99.99, balanceOf → 1000 USDT
        answers = {
            bsc_flow.SEL_QUOTE_TOKENS[2:]: 500 * 10**18,
            bsc_flow.SEL_QUOTE_COST[2:]: 99_990_000_000_000_000_000,
            bsc_flow.SEL_BALANCE_OF[2:]: 1000 * 10**18,
        }
        def fake_call(to, data):
            return answers[data[2:10]]
        with mock.patch.object(bsc_flow, '_eth_call', side_effect=fake_call):
            return bsc_flow.prepare_purchase(self.user, self.account, amount, **defaults)

    def test_prepare_gates(self):
        res = self._prepare(accepted_terms=False)
        self.assertEqual(res['error'], 'terms_acceptance_required')
        res = self._prepare(not_us_attestation=False)
        self.assertEqual(res['error'], 'not_us_attestation_required')
        res = self._prepare(ip_country_hint='US')
        self.assertIn('Estados Unidos', res['error'])
        res = self._prepare(amount='1')
        self.assertEqual(res['error'], 'below_minimum')
        self.account.bsc_address = None
        self.account.save(update_fields=['bsc_address'])
        res = self._prepare()
        self.assertEqual(res['error'], 'no_bsc_address')

    def test_prepare_records_and_builds_exact_batch(self):
        from cusd_plus.sponsor_7702 import SEL_APPROVE, SEL_PRESALE_BUY, USDT_BSC
        res = self._prepare()
        self.assertTrue(res['success'], res)
        self.assertEqual(res['confio_amount'], '500.000000')
        purchase = PresalePurchase.objects.get(internal_id=res['purchase_id'])
        self.assertEqual(purchase.funding_source, 'direct_cusd')
        self.assertEqual(purchase.status, 'processing')
        self.assertTrue(purchase.attested_not_us_resident)
        calls = res['calls']
        cap = 100 * 10**18
        self.assertEqual(calls[0]['to'], USDT_BSC)
        self.assertEqual(
            calls[0]['data'],
            '0x' + SEL_APPROVE + VAULT[2:].lower().rjust(64, '0') + format(cap, 'x').rjust(64, '0'))
        self.assertEqual(calls[1]['to'], VAULT.lower())
        self.assertEqual(
            calls[1]['data'],
            '0x' + SEL_PRESALE_BUY + format(500 * 10**18, 'x').rjust(64, '0') + format(cap, 'x').rjust(64, '0'))

    def test_submit_verifies_signature_and_policy(self):
        import time as _t
        from eth_keys import keys as eth_keys
        from cusd_plus import sponsor_7702
        from presale import bsc_flow

        res = self._prepare()
        purchase = PresalePurchase.objects.get(internal_id=res['purchase_id'])
        pk = eth_keys.PrivateKey(b'\x07' * 32)
        signer_addr = pk.public_key.to_checksum_address().lower()
        purchase.from_address = signer_addr
        purchase.save(update_fields=['from_address'])
        calls = json.loads(purchase.notes)['bsc_calls']
        deadline = int(_t.time()) + 600
        digest = sponsor_7702.intent_digest(calls, 0, deadline, signer_addr, 56)
        sig = pk.sign_msg_hash(digest)
        sig_hex = '0x' + sig.r.to_bytes(32, 'big').hex() + sig.s.to_bytes(32, 'big').hex() + bytes([27 + sig.v]).hex()

        # executed_early explicitly None: a bare Mock would auto-create the
        # attribute and feed a Mock object into the `execution` field, where
        # the real batch row carries 'executed' | 'reverted' | 'noop' | None.
        fake_batch = mock.Mock(id=1, executed_early=None)
        with mock.patch.object(sponsor_7702, 'is_delegated', return_value=True), \
             mock.patch.object(sponsor_7702, 'send_sponsored_batch',
                               return_value=('0x' + 'ab' * 32, fake_batch)) as sent, \
             mock.patch('presale.tasks.confirm_bsc_presale_purchase'):
            ok = bsc_flow.submit_purchase(self.user, purchase, 0, deadline, sig_hex)
        self.assertTrue(ok['success'], ok)
        self.assertEqual(sent.call_args.args[7], 'presale_buy')

        # wrong signer
        purchase.status = 'processing'
        purchase.save(update_fields=['status'])
        pk2 = eth_keys.PrivateKey(b'\x09' * 32)
        sig2 = pk2.sign_msg_hash(digest)
        bad = '0x' + sig2.r.to_bytes(32, 'big').hex() + sig2.s.to_bytes(32, 'big').hex() + bytes([27 + sig2.v]).hex()
        with mock.patch.object(sponsor_7702, 'is_delegated', return_value=True):
            rej = bsc_flow.submit_purchase(self.user, purchase, 0, deadline, bad)
        self.assertEqual(rej['error'], 'bad_intent_signature')

        # tampered stored calldata
        meta = json.loads(purchase.notes)
        meta['bsc_calls'][1]['data'] = meta['bsc_calls'][1]['data'][:-2] + 'ff'
        purchase.notes = json.dumps(meta)
        purchase.save(update_fields=['notes'])
        with mock.patch.object(sponsor_7702, 'is_delegated', return_value=True):
            rej2 = bsc_flow.submit_purchase(self.user, purchase, 0, deadline, sig_hex)
        self.assertEqual(rej2['error'], 'bad_calldata')
