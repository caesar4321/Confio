"""No live signing or funds: route binding, crash recovery and chain proofs."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock
import time
import uuid

from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from eth_account import Account as EthAccount
from eth_utils import keccak

from payment_accounts import bridge_chain as chain
from payment_accounts.bridge_binding import deposit_call, validate_binding
from payment_accounts.bridge_execution import prepare_bridge, submit_bridge, reconcile_bridge, funding_calls
from payment_accounts.allbridge_next import TOKENS, NextError
from payment_accounts.models import PaymentBridgeTransfer
from .test_bridge import BridgeQuoteTests
from .test_allbridge_next import SOURCE, DESTINATION

DEPOSIT = '0x' + '33' * 20
SOURCE_HASH = '0x' + '44' * 32
DEST_HASH = '0x' + '55' * 32


def binding(q, deposit=DEPOSIT):
    deadline = (timezone.now() + timedelta(hours=2)).isoformat()
    return {'status': 'PENDING_DEPOSIT', 'quoteResponse': {
        'quoteRequest': {'dry': False, 'swapType': 'EXACT_INPUT', 'depositType': 'ORIGIN_CHAIN',
            'recipientType': 'DESTINATION_CHAIN', 'refundType': 'ORIGIN_CHAIN',
            'recipient': q.destination_address, 'refundTo': q.source_address, 'amount': q.amount_units,
            'originAsset': q.source_token_id, 'destinationAsset': q.destination_token_id, 'deadline': deadline},
        'quote': {'amountIn': q.amount_units, 'amountOut': '9900000', 'minAmountOut': '9800000',
                  'depositAddress': deposit, 'deadline': deadline}}}


def tokens():
    return [dict(assetId=k, contractAddress=v[0], decimals=v[1], blockchain=k.split(':')[0].lower()) for k,v in TOKENS.items()]


def build(q):
    return {'amountOut': '9900000', 'amountOutMin': '9800000', 'tx': {
        'contractAddress': TOKENS[q.source_token_id][0], 'value': '0',
        'tx': 'a9059cbb' + DEPOSIT[2:].rjust(64, '0') + f'{int(q.amount_units):064x}'}}


def receipt(token, recipient, amount, sender=SOURCE):
    return {'status': '0x1', 'logs': [{'address': TOKENS[token][0], 'topics': [chain.TRANSFER_TOPIC,
        '0x' + sender[2:].rjust(64, '0'), '0x' + recipient[2:].rjust(64, '0')], 'data': f'0x{amount:064x}'}]}


@override_settings(PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True,
                   PAYMENT_BRIDGE_POLYGON_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True, CUSD_PLUS_7702_ENABLED=True)
class BridgeExecutionTests(TestCase):
    setUp = BridgeQuoteTests.setUp
    quote = BridgeQuoteTests.quote

    def prepared(self, direction='to_provider'):
        q = self.quote(direction=direction)
        q.routes = [dict(q.routes[0], messenger='near-intents', amountOutMin='9700000')]
        q.save()
        self.client.build.return_value = build(q)
        intents = mock.Mock()
        intents.status.return_value, intents.tokens.return_value = binding(q), tokens()
        with mock.patch.object(chain, 'require_chain'), mock.patch('payment_accounts.bridge_execution.funding_calls', return_value=([], {})), \
             mock.patch.object(chain, 'token_balance', return_value=10**25), mock.patch.object(chain, 'rpc', return_value='0x'+chain.authorization_domain().hex()):
            t = prepare_bridge(self.owner, q.internal_id, client=self.client, intents=intents)
        return t, intents

    def test_prepared_transfer_recovers_after_pricing_quote_expiry(self):
        t, _ = self.prepared()
        t.quote.expires_at = timezone.now() - timedelta(seconds=1)
        t.quote.save()
        self.assertEqual(self.quote().pk, t.quote_id)
        self.assertEqual(prepare_bridge(self.owner, t.quote.internal_id).pk, t.pk)
        self.client.quote.assert_called_once()

    def test_split_provider_delivery_cannot_credit_only_first_installment(self):
        t, intents = self.prepared()
        t.source_tx_hash, t.status = SOURCE_HASH, 'submitted'; t.save()
        intents.status.return_value = dict(quoteResponse=t.binding['quoteResponse'], status='SUCCESS', swapDetails={
            'originChainTxHashes': [{'hash': SOURCE_HASH}],
            'destinationChainTxHashes': [{'hash': DEST_HASH}, {'hash': '0x'+'66'*32}], 'amountOut': '9850000'})
        with mock.patch.object(chain, 'final_receipt', return_value=receipt('BSC:USDT', DEPOSIT, 10**19)):
            reconcile_bridge(t, intents=intents)
        t.refresh_from_db()
        self.assertEqual(t.status, 'needs_review')
        self.assertEqual(t.failure_code, 'split_provider_delivery')
        self.assertIsNone(t.provider_credit_id)

    def test_prepare_is_idempotent_and_has_only_exact_deposit(self):
        t, intents = self.prepared()
        again = prepare_bridge(self.owner, t.quote.internal_id, client=self.client, intents=intents)
        self.assertEqual(t.pk, again.pk)
        self.client.build.assert_called_once()
        self.assertEqual(len(t.calls), 1)
        self.assertFalse(t.source_tx_hash)

    def test_polygon_preparation_checks_domain_and_balance(self):
        t, _ = self.prepared('to_wallet')
        self.assertEqual(t.quote.destination_address, SOURCE)
        self.assertEqual(t.quote.source_token_id, 'POL:USDC')

    def test_recovery_never_signs_again_after_uncertain_submission(self):
        t, _ = self.prepared()
        t.source_tx_hash, t.status = SOURCE_HASH, 'submitted'
        t.save()
        with mock.patch('cusd_plus.sponsor_7702.send_sponsored_batch') as send:
            again = submit_bridge(self.owner, t.internal_id, 'not a signature')
        send.assert_not_called()
        self.assertEqual(again.source_tx_hash, SOURCE_HASH)

    def test_worker_rebroadcasts_same_bytes_on_correct_chain(self):
        t, intents = self.prepared()
        t.source_tx_hash, t.signed_raw_tx, t.status = SOURCE_HASH, '0x1234', 'submitted'
        t.save()
        with mock.patch.object(chain, 'final_receipt', return_value=None), mock.patch.object(chain, 'rpc') as rpc:
            reconcile_bridge(t, intents=intents)
        rpc.assert_called_once_with('BSC', 'eth_sendRawTransaction', ['0x1234'])
        intents.status.assert_called_once()  # preparation only

    def test_final_delivery_does_not_claim_provider_credit(self):
        t, intents = self.prepared()
        t.source_tx_hash, t.status = SOURCE_HASH, 'submitted'; t.save()
        intents.status.return_value = dict(quoteResponse=t.binding['quoteResponse'], status='SUCCESS', swapDetails={
            'originChainTxHashes': [{'hash': SOURCE_HASH}], 'destinationChainTxHashes': [{'hash': DEST_HASH}], 'amountOut': '9850000'})
        with mock.patch.object(chain, 'final_receipt', side_effect=[receipt('BSC:USDT', DEPOSIT, 10**19), receipt('POL:USDC', DESTINATION, 9850000)]):
            reconcile_bridge(t, intents=intents)
        t.refresh_from_db(); t.quote.money_flow.refresh_from_db()
        self.assertEqual(t.status, 'delivered')
        self.assertEqual(t.actual_out_units, '9850000')
        self.assertEqual(t.quote.money_flow.status, 'processing')

    def test_refund_status_is_not_refund_proof(self):
        t, intents = self.prepared()
        t.source_tx_hash = SOURCE_HASH; t.save()
        intents.status.return_value = dict(quoteResponse=t.binding['quoteResponse'], status='REFUNDED')
        with mock.patch.object(chain, 'final_receipt', return_value=receipt('BSC:USDT', DEPOSIT, 10**19)):
            reconcile_bridge(t, intents=intents)
        t.refresh_from_db()
        self.assertEqual(t.status, 'needs_review')

    def test_expiry_without_submission_fails_flow(self):
        t, intents = self.prepared()
        t.deadline = int(time.time()) - 1; t.save()
        reconcile_bridge(t, intents=intents)
        t.refresh_from_db(); t.quote.money_flow.refresh_from_db()
        self.assertEqual(t.status, 'expired')
        self.assertEqual(t.quote.money_flow.status, 'failed')

    def test_wrong_source_amount_never_polls_next(self):
        t, intents = self.prepared()
        t.source_tx_hash = SOURCE_HASH; t.save()
        with mock.patch.object(chain, 'final_receipt', return_value=receipt('BSC:USDT', DEPOSIT, 1)):
            reconcile_bridge(t, intents=intents)
        self.assertEqual(t.status, 'needs_review')
        intents.status.assert_called_once()

    def test_destination_must_be_finalized(self):
        t, intents = self.prepared()
        t.source_tx_hash, t.status = SOURCE_HASH, 'submitted'; t.save()
        intents.status.return_value = dict(quoteResponse=t.binding['quoteResponse'], status='SUCCESS', swapDetails={
            'originChainTxHashes': [{'hash': SOURCE_HASH}], 'destinationChainTxHashes': [{'hash': DEST_HASH}], 'amountOut': '9850000'})
        with mock.patch.object(chain, 'final_receipt', side_effect=[receipt('BSC:USDT', DEPOSIT, 10**19), None]):
            reconcile_bridge(t, intents=intents)
        t.refresh_from_db()
        self.assertNotEqual(t.status, 'delivered')


class BindingTests(SimpleTestCase):
    def setUp(self):
        self.q = SimpleNamespace(source_address=SOURCE, destination_address=DESTINATION,
            source_token_id='BSC:USDT', destination_token_id='POL:USDC', amount_units=str(10**19))

    def test_live_next_hex_format_decodes_exact_transfer(self):
        deposit, call = deposit_call(build(self.q), 'BSC:USDT', self.q.amount_units)
        self.assertEqual(deposit, DEPOSIT)
        self.assertTrue(call['data'].startswith('0xa9059cbb'))

    def test_changed_calldata_or_token_is_rejected(self):
        for path, value in [('contractAddress', DESTINATION), ('value', '1'), ('tx', '0x095ea7b3' + '0'*128)]:
            b = build(self.q); b['tx'][path] = value
            with self.subTest(path=path), self.assertRaises(NextError):
                deposit_call(b, 'BSC:USDT', self.q.amount_units)

    def test_binding_rejects_recipient_refund_amount_chain_and_asset_changes(self):
        good = binding(self.q)
        validate_binding(good, tokens(), self.q, DEPOSIT, minimum='9800000', now=int(time.time()))
        for key, value in [('recipient', SOURCE), ('refundTo', DESTINATION), ('amount', '1'), ('originAsset', 'fake'), ('recipientType', 'INTENTS')]:
            changed = deepcopy(good); changed['quoteResponse']['quoteRequest'][key] = value
            with self.subTest(key=key), self.assertRaises(NextError):
                validate_binding(changed, tokens(), self.q, DEPOSIT, minimum='9800000', now=int(time.time()))
        wrong_tokens = tokens(); wrong_tokens[0]['decimals'] = 6
        with self.assertRaises(NextError):
            validate_binding(good, wrong_tokens, self.q, DEPOSIT, minimum='9800000', now=int(time.time()))

    def test_wrong_chain_and_reorg_are_not_final(self):
        with mock.patch.object(chain, 'rpc', return_value='0x1'):
            with self.assertRaisesRegex(NextError, 'chain mismatch'):
                chain.final_receipt('POL', SOURCE_HASH)
        r = dict(blockNumber='0x10', blockHash=SOURCE_HASH, transactionHash=SOURCE_HASH)
        with mock.patch.object(chain, 'rpc', side_effect=['0x89', r, {'number': '0x11'}, {'hash': DEST_HASH}]):
            self.assertIsNone(chain.final_receipt('POL', SOURCE_HASH))

    def test_authorization_is_bound_to_amount_nonce_chain_and_recipient(self):
        private = '0x' + '01'*32
        self.q.source_address = EthAccount.from_key(private).address.lower()
        t = SimpleNamespace(quote=self.q, internal_id=uuid.UUID(int=1), deposit_address=DEPOSIT, deadline=2000000000)
        digest = chain.authorization_digest(t)
        signature = EthAccount._sign_hash(digest, private).signature.hex()
        data = chain.authorization_calldata(t, signature)
        self.assertTrue(data.startswith('0xe3ee160e'))
        self.q.amount_units = '1'
        with self.assertRaises(NextError):
            chain.authorization_calldata(t, signature)

    @mock.patch('cusd_plus.vault.reserved_usdt_wei', return_value=10**18)
    @mock.patch.object(chain, 'token_balance', return_value=3*10**18)
    def test_wallet_funding_respects_existing_reservations(self, balance, reserved):
        calls, fees = funding_calls(SimpleNamespace(user=object(), bsc_address=SOURCE), 2*10**18)
        self.assertEqual(calls, [])
        self.assertEqual(fees['wallet_usdt_units'], str(2*10**18))


@override_settings(PAYMENT_BRIDGE_QUOTES_ENABLED=True, PAYMENT_BRIDGE_BSC_ENABLED=True,
                   PAYMENT_BRIDGE_POLYGON_ENABLED=True, INFINIA_PAYMENT_ACCOUNTS_ENABLED=True, CUSD_PLUS_7702_ENABLED=True)
class BridgeRecoveryTests(BridgeExecutionTests):
    # Inherited coverage also exercises these paths with the same real DB fixtures.
    def test_second_preparation_for_pending_wallet_is_rejected(self):
        self.prepared()
        self.request_id = uuid.uuid4()
        with self.assertRaisesRegex(NextError, 'existing bridge'):
            self.prepared()

    def test_polygon_signed_bytes_survive_failed_broadcast_and_retry(self):
        from payment_accounts.bridge_execution import _submit_polygon
        t, _ = self.prepared('to_wallet')
        raw = '0x12345678'; txhash = '0x' + keccak(bytes.fromhex(raw[2:])).hex()
        signer = mock.Mock(address=SOURCE)
        signer.sign_typed_transaction.return_value = (raw, txhash)
        def rpc(_, method, args):
            if method == 'eth_getTransactionCount': return '0x0'
            if method == 'eth_gasPrice': return hex(30*10**9)
            if method == 'eth_sendRawTransaction':
                stored = PaymentBridgeTransfer.objects.get(pk=t.pk)
                self.assertEqual(stored.signed_raw_tx, raw)
                self.assertEqual(stored.source_tx_hash, txhash)
                raise RuntimeError('connection lost after broadcast')
            return '0x'
        with mock.patch.object(chain, 'authorization_calldata', return_value='0x1234'), \
             mock.patch.object(chain, 'require_chain'), mock.patch.object(chain, 'rpc', side_effect=rpc), \
             mock.patch('blockchain.evm_kms_signer.get_bsc_sponsor_signer_from_settings', return_value=signer):
            _submit_polygon(t, 'signature')
            _submit_polygon(t, 'signature')
        signer.sign_typed_transaction.assert_called_once()
        t.refresh_from_db()
        self.assertEqual(t.status, 'submitted')
        self.assertEqual(t.sponsor_nonce, 0)

    def test_bsc_domain_callback_failure_never_broadcasts(self):
        from cusd_plus import sponsor_7702 as sponsor
        from blockchain.models import SponsoredBatch
        t, _ = self.prepared()
        signer = mock.Mock(address=SOURCE)
        signer.sign_typed_transaction.return_value = ('0x1234', SOURCE_HASH)
        def rpc(method, args):
            if method == 'eth_gasPrice': return hex(10**8)
            if method == 'eth_getTransactionCount': return '0x0'
            if method == 'eth_getBalance': return hex(10**20)
            return '0x'
        with mock.patch.object(sponsor, 'simulate'), mock.patch.object(sponsor, 'execute_calldata', return_value='0x1234'), \
             mock.patch.object(sponsor, 'acquire_sponsor_nonce_lock', return_value=mock.Mock()), \
             mock.patch.object(sponsor, '_rpc', side_effect=rpc) as calls, \
             mock.patch('blockchain.evm_kms_signer.get_bsc_sponsor_signer_from_settings', return_value=signer):
            with self.assertRaisesRegex(RuntimeError, 'persist failed'):
                sponsor.send_sponsored_batch(self.user, SOURCE, t.calls, 0, t.deadline, 'signature', None,
                    'payment_bridge', client_request_id='bridge:'+str(t.internal_id),
                    persist_signed=mock.Mock(side_effect=RuntimeError('persist failed')))
        self.assertFalse(SponsoredBatch.objects.exists())
        self.assertFalse(any(call.args[0] == 'eth_sendRawTransaction' for call in calls.call_args_list))

    def test_cobre_credit_requires_chain_reference_and_exact_account(self):
        from payment_accounts.bridge_execution import reconcile_provider_credit
        from payment_accounts.models import LedgerEntry
        t, _ = self.prepared()
        t.status, t.destination_tx_hash, t.actual_out_units = 'delivered', DEST_HASH, '9850000'; t.save()
        account = t.quote.funding_instruction.financial_account
        profile = account.provider_profile; profile.provider = 'cobre'; profile.save()
        entry = LedgerEntry.objects.create(provider='cobre', financial_account=account, provider_entry_id='credit-1',
            direction='credit', amount='9.85', asset='USD_STABLE', occurred_at=timezone.now(), provider_data={
                'content': {'type': 'global_credit', 'credit_debit_type': 'credit', 'metadata': {
                    'chain': 'polygon', 'token': 'usdc', 'tracking_key': SOURCE_HASH,
                    'beneficiary_wallet_address': DESTINATION}}})
        reconcile_provider_credit(t)
        t.refresh_from_db(); self.assertIsNone(t.provider_credit_id)
        entry.provider_data['content']['metadata']['tracking_key'] = DEST_HASH; entry.save()
        reconcile_provider_credit(t); reconcile_provider_credit(t)
        t.refresh_from_db(); t.quote.money_flow.refresh_from_db()
        self.assertEqual(t.provider_credit_id, entry.pk)
        self.assertEqual(t.quote.money_flow.status, 'succeeded')
        self.assertEqual(t.quote.money_flow.metadata['provider_credit_asset'], 'USD_STABLE')

    def test_expired_polygon_raw_can_clear_its_sponsor_nonce_without_resigning(self):
        t, intents = self.prepared('to_wallet')
        t.source_tx_hash, t.signed_raw_tx, t.status = SOURCE_HASH, '0x1234', 'submitted'
        t.deadline = int(time.time()) - 1; t.save()
        with mock.patch.object(chain, 'final_receipt', return_value=None), mock.patch.object(chain, 'rpc') as rpc:
            reconcile_bridge(t, intents=intents)
        rpc.assert_called_once_with('POL', 'eth_sendRawTransaction', ['0x1234'])

    @override_settings(CUSD_PLUS_7702_ENABLED=False)
    def test_sponsor_kill_switch_blocks_new_bridge_preparation(self):
        from payment_accounts.services import PaymentAccountError
        with self.assertRaisesRegex(PaymentAccountError, 'sponsorship'):
            self.prepared()

    def test_savings_topup_charges_perimeter_only_on_missing_usdt(self):
        from cusd_plus.cusd_vault import ConversionPreview
        from eth_abi import decode
        owner = SimpleNamespace(user=self.user, bsc_address=SOURCE)
        cusd, plus = '0x' + '66'*20, '0x' + '77'*20
        amount, wallet = 10*10**18, 95*10**17
        missing = amount - wallet
        def preview(gross):
            fee = gross * 90 // 10000
            return ConversionPreview(gross_wei=gross, net_wei=gross-fee, fee_wei=fee, fee_bps=90)
        with mock.patch.object(chain, 'token_balance', return_value=wallet), \
             mock.patch('cusd_plus.vault.reserved_usdt_wei', return_value=0), \
             mock.patch('cusd_plus.cusd_vault.require_operational'), \
             mock.patch('cusd_plus.cusd_vault.current_fee_bps', return_value=90), \
             mock.patch('cusd_plus.cusd_vault.preview_redeem_wei', side_effect=preview), \
             mock.patch('cusd_plus.cusd_vault.vault_address', return_value=cusd), \
             mock.patch('cusd_plus.vault.vault_address', return_value=plus), \
             mock.patch('cusd_plus.vault.erc20_balance_raw', side_effect=[0, 10**19]), \
             mock.patch('cusd_plus.vault.p_plus_wad', return_value=10**18), \
             mock.patch('cusd_plus.vault.current_oracle_price_wad', return_value=10**18):
            calls, funding = funding_calls(owner, amount)
        self.assertEqual(len(calls), 2)
        shares, minimum_cusd, recipient = decode(['uint256', 'uint256', 'address'], bytes.fromhex(calls[0]['data'][10:]))
        gross, minimum_usdt, recipient = decode(['uint256', 'uint256', 'address'], bytes.fromhex(calls[1]['data'][10:]))
        self.assertEqual(recipient, SOURCE)
        self.assertEqual(minimum_usdt, missing)
        self.assertEqual(funding['wallet_usdt_units'], str(wallet))
        self.assertEqual(funding['fee_units'], str(preview(gross).fee_wei))
        self.assertGreaterEqual(preview(gross).net_wei, missing)
        self.assertEqual(shares, 10**18)  # Redeem the minimum; leave excess cUSD.
        self.assertEqual(minimum_cusd, gross)
