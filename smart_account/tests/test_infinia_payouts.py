"""CLABE and Pix payment rules end to end, each from cUSD and from cUSD+:
the real adapter, bridge, journey, workers, event mirror and payout mirror,
with the chain, Relay and Infinia faked at HTTP (infinia_world).
Fake accounts, keys and names only."""
from decimal import ROUND_DOWN, Decimal
from unittest import mock

from eth_abi import decode as abi_decode

from payment_accounts.models import InfiniaJourney, PaymentBridgeTransfer
from smart_account import abi, payouts
from smart_account.models import SmartAccountPayout

from . import infinia_world as w
from .infinia_base import RAILS, InfiniaPayoutCase


class EndToEnd:
    """The same assertions for each rail x each dollar."""

    def test_due_slot_to_paid(self):
        rule = self.make_rule()
        authorization = rule.standing_authorization
        asset = RAILS[self.rail]['asset']
        self.assertAlmostEqual(authorization.reference_fx_rate, self.world.rates[asset], places=1)
        quotes_at_prepare = len(self.world.orders)

        payout = self.send_run()

        # One order for the run: one-time, from and back to the CONTRACT.
        self.assertEqual(len(self.world.orders), quotes_at_prepare + 1)
        order = self.world.orders[-1]
        self.assertIs(order['body']['strict'], True)
        self.assertIs(order['body']['useDepositAddress'], True)
        self.assertEqual(order['body']['tradeType'], 'EXACT_INPUT')
        self.assertEqual(order['body']['user'], self.contract)
        self.assertEqual(order['body']['refundTo'], self.contract)
        self.assertEqual(order['body']['recipient'], w.OWNER_INFINIA)

        # The calldata exits exactly what the bridge was quoted for.
        (_hash, tx), = self.world.signed.values()
        self.assertEqual(tx['to'].lower(), self.contract)
        _name, args = abi.decode_call(tx['data'])
        amount = int(Decimal(self.amount) * w.WAD)
        if self.token == w.VAULT:
            deposit, exact, gross = abi_decode(['address', 'uint256', 'uint256'], bytes(args[1]))
            self.assertEqual(exact, gross - self.world.fee(gross))
            self.assertLessEqual(gross + gross * 5 // 10_000, amount)
        else:
            deposit, exact = abi_decode(['address', 'uint256'], bytes(args[1]))
            self.assertEqual(exact, amount - self.world.fee(amount))
        self.assertEqual((deposit.lower(), exact), (order['deposit'], order['amount']))
        self.assertEqual(self.world.deposited(order['deposit']), exact)

        bridge, journey = self.bridge(), self.journey()
        self.assertEqual((bridge.calls, bridge.batch_id, bridge.funding_mode), ([], None, 'contract'))
        self.assertNotEqual(bridge.status, 'prepared')   # never "waiting for your signature"
        self.assertEqual((bridge.quote.source_address, bridge.quote.destination_address),
                         (self.contract, w.OWNER_INFINIA))
        self.assertEqual(bridge.quote.amount_units, str(exact))
        self.assertEqual((payout.journey_id, payout.deposit_address, payout.status, payout.usdt_amount),
                         (journey.pk, order['deposit'], 'onchain_sent', str(exact)))
        self.assertEqual(journey.bridge_id, bridge.pk)
        self.assertEqual(journey.wallet_address, self.contract)
        bound = journey.money_flow.metadata['contract_funding']
        self.assertEqual(
            (bound['authorization'], bound['run'], bound['destination'], bound['amount'], bound['units']),
            (str(authorization.internal_id), self.last_run().pk, str(self.destination.internal_id),
             self.amount, str(exact)))
        self.assertEqual(bridge.binding['contract_funding']['reported'], [self.last_run().tx_hash])
        self.assertEqual(bridge.source_tx_hash, '')      # reported is not proven

        with mock.patch('smart_account.notifications.payout_delivered') as delivered:
            self.bridges()
            self.mirror()
            self.assertEqual(self.bridge().source_tx_hash, self.last_run().tx_hash)
            self.assertEqual(self.payout().status, 'funded')
            self.journeys()
            self.assertEqual(self.world.transfers, [])   # nothing before Infinia's credit
            paid = self.to_paid()
            for _ in range(3):                           # every worker again: nothing new
                self.run_rules()
                self.mirror_chain()
                self.workers()

        (transfer,), (sent,) = self.world.transfers, self.world.payouts
        converted = (Decimal(order['out']) / 10 ** 6).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        fiat = (converted * self.world.rates[asset]).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        self.assertEqual(Decimal(str(transfer['source_amount'])), converted)
        self.assertEqual(Decimal(str(sent['amount'])), fiat)
        self.assertEqual(sent['sourceAccountId'], self.local.provider_account_id)
        self.assertEqual(sent['destinationAccount']['currency'], asset)
        self.assertEqual(sent['destinationAccount']['country'], {'MXN': 'MEXICO', 'BRL': 'BRAZIL'}[asset])
        self.assertEqual(sent['destinationAccount']['destinationType'], RAILS[self.rail]['details'])
        self.assertEqual((paid.status, paid.fiat_amount, paid.fiat_currency), ('paid', fiat, asset))
        self.assertEqual(self.journey().stage, 'completed')
        delivered.assert_called_once()
        self.assertEqual(delivered.call_args.args[2], asset)
        self.assertEqual(delivered.call_args.args[1],
                         f'{fiat:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.'))
        self.assertEqual((PaymentBridgeTransfer.objects.count(), InfiniaJourney.objects.count(),
                          SmartAccountPayout.objects.count(), len(self.world.signed)), (1, 1, 1, 1))
        # No Face and no owner signature after the rule was signed.
        self.assertEqual(self.face.call_count, self.face_at_prepare)
        self.alerts.assert_not_called()
        self.assertEqual(self.last_run().status, 'ok')
        # The owner's history has it as one transfer.
        self.assertEqual(self.journey().money_flow.unified_transaction.status, 'CONFIRMED')

    def test_refund_returns_to_the_contract_and_is_verified(self):
        self.make_rule()
        self.send_run()
        self.bridges()
        self.world.relay_refunds()
        self.workers()
        self.mirror()
        bridge = self.bridge()
        evidence = bridge.binding['settlement_evidence']
        self.assertEqual((bridge.status, evidence['recipient'], evidence['token_id']),
                         ('refunded', self.contract, 'BSC:USDT'))
        self.assertEqual((self.payout().status, self.journey().stage), ('refunded', 'failed'))
        self.assertEqual((self.world.transfers, self.world.payouts), ([], []))
        self.assertIn('devuelto', self.alert_text())
        # The returned USDT is this payout's, never "an external deposit".
        from payment_accounts.activity import arrival_owned
        self.assertTrue(arrival_owned(evidence['transaction_hashes'][0], self.contract))

    def test_retry_after_a_reverted_call_reuses_the_same_order(self):
        self.make_rule()
        self.world.revert_mined = True
        self.assertEqual(self.run_rules()['sent'], 1)
        self.mirror_chain()
        self.assertEqual(self.last_run().status, 'failed')
        first, quoted = self.bridge(), len(self.world.orders)
        self.world.revert_mined = False

        self.send_run()

        self.assertEqual((self.bridge().pk, len(self.world.orders)), (first.pk, quoted))
        calls = [bytes(abi.decode_call(tx['data'])[1][1]) for _h, tx in self.world.signed.values()]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][:64], calls[1][:64])   # same deposit, same USDT
        self.assertEqual(self.to_paid().status, 'paid')
        self.assertEqual(len(self.world.payouts), 1)


class ClabeFromCusd(EndToEnd, InfiniaPayoutCase):
    rail, token = 'mx_clabe', w.CUSD


class ClabeFromCusdPlus(EndToEnd, InfiniaPayoutCase):
    rail, token = 'mx_clabe', w.VAULT


class PixFromCusd(EndToEnd, InfiniaPayoutCase):
    rail, token = 'br_pix', w.CUSD


class PixFromCusdPlus(EndToEnd, InfiniaPayoutCase):
    rail, token = 'br_pix', w.VAULT

    def test_a_share_price_above_one_still_exits_exactly(self):
        self.world.p_plus = 1_047_300_000_000_000_000
        self.make_rule()
        self.send_run()
        self.assertEqual(self.to_paid().status, 'paid')


class DataFormTests(InfiniaPayoutCase):
    def test_the_adapters(self):
        self.assertIsInstance(payouts.adapter('mx_clabe'), payouts.InfiniaAdapter)
        self.assertIsInstance(payouts.adapter('br_pix'), payouts.InfiniaAdapter)
        for rail in ('co_breb', 'ar_cvu', 'br_qr', 'co_qr', ''):
            adapter = payouts.adapter(rail)
            self.assertIs(type(adapter), payouts.ProviderAdapter, rail)
            with self.assertRaises(payouts.PayoutSkip) as raised:
                adapter.open(None, None, 1)
            self.assertEqual(raised.exception.code, 'provider_path_unverified')
