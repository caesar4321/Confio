"""An ordinary wallet-funded CLABE / Pix send, signed by the owner, through
the code the contract-funded path shares (bridge, settlement, journey).
Runs the same with or without that path."""
import uuid
from decimal import Decimal

from django.test import override_settings

from payment_accounts import bridge_execution, infinia_journeys
from payment_accounts.bridge import quote_provider_funding
from payment_accounts.models import InfiniaJourney, PaymentBridgeTransfer

from . import infinia_world as w
from .infinia_base import InfiniaPayoutCase


@override_settings(RELAY_API_KEY='')    # a manual send needs no key and no /requests/v3
class WalletFundedSendTests(InfiniaPayoutCase):
    def prepared(self):
        self.world.balances[(w.USDT, self.wallet)] = 100 * w.WAD
        quote = quote_provider_funding(confio_account=self.personal,
                                       funding_instruction_id=self.instruction.internal_id, amount='20',
                                       request_id=uuid.uuid4(), destination_id=self.destination.internal_id)
        bridge = bridge_execution.prepare_bridge(self.personal, quote.internal_id)
        journey = infinia_journeys.create_journey(
            owner=self.personal, local_account=self.local, crypto_account=self.crypto, request_id=uuid.uuid4(),
            minimum_fx_output='1', direction='to_bank', bridge=bridge, destination=self.destination)
        return bridge, journey

    def signed(self, bridge):
        tx = self.world.new_hash()
        self.world.mine('BSC', tx, [w.transfer_log(w.USDT, self.wallet, bridge.deposit_address,
                                                   int(bridge.quote.amount_units))])
        PaymentBridgeTransfer.objects.filter(pk=bridge.pk).update(status='submitted', source_tx_hash=tx)
        self.bridges()

    def test_prepared_authorized_and_paid_as_before(self):
        bridge, journey = self.prepared()
        self.assertEqual((bridge.funding_mode, bridge.status, len(bridge.calls)), ('wallet', 'prepared', 1))
        self.assertEqual((bridge.quote.source_address, journey.wallet_address), (self.wallet, self.wallet))
        self.assertNotIn('strict', self.world.orders[-1]['body'])
        self.assertEqual(self.face.call_count, 1)           # its own Face grant
        self.signed(bridge)
        fill, units = self.world.relay_fills()
        self.bridges()
        self.credit_usdc(fill, units)
        self.bridges()
        self.journeys()
        self.credit_conversion()
        self.journeys()
        self.journeys()
        self.assertEqual(InfiniaJourney.objects.get().stage, 'completed')
        self.assertEqual(len(self.world.payouts), 1)
        self.assertEqual(self.world.count('relay', '/requests/v3'), 0)

    def test_expiry_as_before(self):
        bridge, _journey = self.prepared()
        PaymentBridgeTransfer.objects.filter(pk=bridge.pk).update(deadline=1)
        self.bridges()
        self.journeys()
        self.assertEqual(PaymentBridgeTransfer.objects.get().status, 'expired')
        self.assertEqual(InfiniaJourney.objects.get().stage, 'failed')

    def test_refund_to_the_wallet_as_before(self):
        bridge, _journey = self.prepared()
        self.signed(bridge)
        self.world.relay_refunds()
        self.bridges()
        self.journeys()
        row = PaymentBridgeTransfer.objects.get()
        evidence = row.binding['settlement_evidence']
        self.assertEqual((row.status, evidence['recipient']), ('refunded', self.wallet))
        self.assertNotIn('request_id', evidence)

    def test_relay_failure_still_goes_to_review_at_once(self):
        bridge, _journey = self.prepared()
        self.signed(bridge)
        self.world.relay_fails()
        self.bridges()
        row = PaymentBridgeTransfer.objects.get()
        self.assertEqual((row.status, row.failure_code), ('needs_review', 'relay_failure'))

    def test_a_wallet_change_still_stops_it(self):
        self.prepared()
        type(self.personal).objects.filter(pk=self.personal.pk).update(bsc_address='0x' + '88' * 20)
        self.journeys()
        self.assertEqual(InfiniaJourney.objects.get().failure_code, 'wallet_changed')

    def test_submit_still_takes_only_the_owners_signature(self):
        bridge, _journey = self.prepared()
        with self.assertRaises(Exception) as raised:
            bridge_execution.submit_bridge(self.personal, bridge.internal_id, '0x' + '00' * 65)
        self.assertNotIn('Cuenta inteligente', str(raised.exception))
        self.assertEqual(PaymentBridgeTransfer.objects.get().status, 'prepared')
