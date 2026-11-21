"""Review round 6: a previous owner whose account passed to the heir is never
offered a subscribe batch that can only revert (spec 6.5, invariant 17:
factory.accountOf is never reset)."""
from unittest import mock

from smart_account import offer, schema, services
from smart_account.models import SmartAccount, SmartAccountPreparedAction

from .base import BUILD, VAULT, SmartAccountTestCase, WAD

MESSAGE = ('La Cuenta inteligente de esta billetera pasó a tu beneficiario. '
           'Con esta billetera no se puede abrir otra.')


class InheritedWalletSubscribeTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.previous = self.make_user('previous')
        self.heir = self.make_user('heir')
        self.fund(VAULT, self.previous.wallet, 500 * WAD)
        # What _claim_executed leaves behind: the row now belongs to the heir,
        # and the factory still maps the previous owner's signer to the clone.
        self.clone = self.make_account(self.heir, status='inherited', index=1)
        self.chain.accounts[self.previous.wallet] = self.clone.contract_address
        self.offer_patch = mock.patch('smart_account.offer.crypto_investing_enabled', return_value=False)
        self.offer_patch.start()
        self.addCleanup(self.offer_patch.stop)

    def prepare(self):
        return services.prepare_subscribe(self.viewer(self.previous), 'annual',
                                          [{'asset_key': 'cusd_plus', 'units': str(200 * WAD)}], True)

    def test_prepare_subscribe_refuses_and_registers_nothing(self):
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, 'wallet_account_inherited')
        self.assertEqual(raised.exception.message, MESSAGE)
        self.assertFalse(SmartAccountPreparedAction.objects.exists())

    def test_offer_does_not_offer_subscribe_and_carries_the_message(self):
        self.assertEqual(offer.subscribe_block(self.previous, personal_context=True, meta=BUILD),
                         'wallet_account_inherited')
        result = schema.Query.resolve_smart_account_offer(None, self.info(self.previous))
        self.assertFalse(result.can_subscribe)
        self.assertEqual(result.blocked_code, 'wallet_account_inherited')
        self.assertEqual(result.blocked_reason, MESSAGE)

    def test_claimed_by_an_unknown_wallet_still_blocks(self):
        # The unknown-wallet branch of _claim_executed keeps the previous owner
        # on the row and only marks it inherited.
        self.clone.owner_user = self.previous
        self.clone.save(update_fields=['owner_user'])
        self.assertEqual(offer.subscribe_block(self.previous, personal_context=True, meta=BUILD),
                         'wallet_account_inherited')

    def test_unreadable_factory_fails_closed(self):
        self.chain.fail.add('account_of')
        self.assertEqual(offer.subscribe_block(self.previous, personal_context=True, meta=BUILD),
                         'chain_unavailable')
        result = schema.Query.resolve_smart_account_offer(None, self.info(self.previous))
        self.assertFalse(result.can_subscribe)
        self.assertEqual(result.blocked_code, 'chain_unavailable')
        self.assertTrue(result.blocked_reason)
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, 'chain_unavailable')

    def test_a_clone_not_reconciled_yet_still_subscribes(self):
        fresh = self.make_user('fresh')
        self.fund(VAULT, fresh.wallet, 500 * WAD)
        unmirrored = '0x' + 'cd' * 20
        self.chain.accounts[fresh.wallet] = unmirrored
        self.chain.views[(unmirrored, 'owner')] = fresh.wallet  # chain: still the signer's
        self.assertIsNone(offer.subscribe_block(fresh, personal_context=True, meta=BUILD))
        batch = services.prepare_subscribe(self.viewer(fresh), 'annual',
                                           [{'asset_key': 'cusd_plus', 'units': str(200 * WAD)}], True)
        self.assertEqual(batch.calls[-1]['to'], unmirrored)

    def test_the_heir_and_a_new_wallet_are_unaffected(self):
        self.assertIsNone(offer.subscribe_block(self.heir, personal_context=True, meta=BUILD))
        self.assertTrue(schema.Query.resolve_smart_account_offer(None, self.info(self.heir)).can_subscribe)
        newcomer = self.make_user('newcomer')
        self.assertTrue(schema.Query.resolve_smart_account_offer(None, self.info(newcomer)).can_subscribe)
        # An owner with their own row is never checked against the factory.
        own = self.make_account(newcomer, status='none')
        self.chain.fail.add('account_of')
        self.assertIsNone(offer.subscribe_block(newcomer, personal_context=True, meta=BUILD))
        self.assertTrue(SmartAccount.objects.filter(pk=own.pk, owner_user=newcomer).exists())
