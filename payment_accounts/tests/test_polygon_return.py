import copy
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from datetime import timedelta
from eth_account import Account as EthAccount
from eth_account.messages import encode_typed_data
from eth_utils import to_checksum_address

from payment_accounts import polygon_return as pr
from payment_accounts.models import PolygonReturn
from users.models import Account

User = get_user_model()
WALLET = EthAccount.create()
ADDR = WALLET.address.lower()
RECEIVER = pr.DEFAULT_RECEIVERS[0]
USDC = '0x3c499c542cef5e3811e1192ce70d8cc03d5c3359'
REQ = '0x' + 'ab' * 32
NONCE = '0x' + 'cd' * 32
OUT_HASH = '0x' + 'ef' * 32
IN_HASH = '0x' + '12' * 32


def permit_quote(amount=26_000_000, *, sender=ADDR, receiver=RECEIVER, valid_before=None, **step_overrides):
    valid_before = valid_before or int(time.time()) + 600
    quote = {
        'requestId': REQ,
        'steps': [{
            'id': 'authorize1', 'kind': 'signature', 'requestId': REQ,
            'items': [{'status': 'incomplete', 'data': {
                'sign': {
                    'signatureKind': 'eip712', 'primaryType': 'ReceiveWithAuthorization',
                    'types': {'ReceiveWithAuthorization': copy.deepcopy(pr.PERMIT_TYPE)},
                    'domain': {'name': 'USD Coin', 'version': '2', 'chainId': 137, 'verifyingContract': USDC},
                    'value': {'from': sender, 'to': receiver, 'value': str(amount), 'validAfter': 0,
                              'validBefore': valid_before, 'nonce': NONCE},
                },
                'post': {'endpoint': '/execute/permits', 'method': 'POST',
                         'body': {'kind': 'eip3009', 'requestId': REQ, 'api': 'swap'}},
            }}],
        }],
        'details': {'currencyOut': {'amount': str(25_930_000 * 10**12), 'minimumAmount': str(25_500_000 * 10**12)}},
    }
    quote['steps'][0].update(step_overrides)
    return quote


def sign(ret):
    """Sign with an independent EIP-712 implementation: proves the server's
    digest equals what any standard wallet (and the app) computes."""
    typed = {
        'types': {
            'EIP712Domain': [{'name': 'name', 'type': 'string'}, {'name': 'version', 'type': 'string'},
                             {'name': 'chainId', 'type': 'uint256'}, {'name': 'verifyingContract', 'type': 'address'}],
            'ReceiveWithAuthorization': pr.PERMIT_TYPE,
        },
        'primaryType': 'ReceiveWithAuthorization',
        'domain': {'name': 'USD Coin', 'version': '2', 'chainId': 137,
                   'verifyingContract': '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359'},
        'message': {'from': WALLET.address, 'to': to_checksum_address(ret.receiver),
                    'value': int(ret.amount_units), 'validAfter': 0, 'validBefore': int(ret.valid_before),
                    'nonce': bytes.fromhex(ret.nonce[2:])},
    }
    signed = EthAccount.sign_message(encode_typed_data(full_message=typed), WALLET.key)
    return '0x' + signed.signature.hex().removeprefix('0x')


@override_settings(POLYGON_RETURN_ENABLED=True)
class PolygonReturnTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='polygon-return', firebase_uid='polygon-return')
        self.owner = Account.objects.create(user=self.user, account_type='personal', bsc_address=WALLET.address)
        self.client_mock = mock.Mock()
        self.client_mock.quote.return_value = permit_quote()
        patcher = mock.patch('payment_accounts.bridge_chain.token_balance', return_value=26_000_000)
        self.balance = patcher.start()
        self.addCleanup(patcher.stop)

    def prepare(self):
        return pr.prepare(self.owner, client=self.client_mock)

    # ---------------------------------------------------------- state / prepare

    def test_state_shows_balance_above_minimum_only(self):
        self.assertEqual(pr.state(self.owner)['state'], 'available')
        cache.clear()
        self.balance.return_value = pr.MIN_UNITS - 1
        self.assertEqual(pr.state(self.owner)['state'], 'none')

    def test_unreadable_polygon_hides_the_card(self):
        self.balance.side_effect = RuntimeError('rpc down')
        self.assertEqual(pr.state(self.owner)['state'], 'none')

    def test_prepare_quotes_the_whole_balance_with_permit(self):
        ret = self.prepare()
        args, kwargs = self.client_mock.quote.call_args
        self.assertEqual(args, ('POL:USDC', 'BSC:USDT', '26000000'))
        self.assertTrue(kwargs['permit'])
        self.assertEqual(kwargs['source_address'], ADDR)
        self.assertEqual(kwargs['destination_address'], ADDR)
        self.assertEqual((ret.status, ret.receiver, ret.amount_units, ret.request_id), ('quoted', RECEIVER, '26000000', REQ))
        self.assertEqual(ret.post_body, {'kind': 'eip3009', 'requestId': REQ, 'api': 'swap'})

    def test_prepare_reuses_a_fresh_quote_for_the_same_amount(self):
        first = self.prepare()
        self.assertEqual(self.prepare().pk, first.pk)
        self.assertEqual(self.client_mock.quote.call_count, 1)

    def test_prepare_refuses_unknown_receiver(self):
        self.client_mock.quote.return_value = permit_quote(receiver='0x' + '9' * 40)
        with self.assertRaises(pr.PolygonReturnError):
            self.prepare()
        self.assertFalse(PolygonReturn.objects.exists())

    def test_prepare_refuses_other_sender_amount_or_long_window(self):
        for quote in (permit_quote(sender='0x' + '8' * 40), permit_quote(amount=1),
                      permit_quote(valid_before=int(time.time()) + 7200),
                      permit_quote(kind='transaction')):
            self.client_mock.quote.return_value = quote
            with self.assertRaises(pr.PolygonReturnError):
                self.prepare()
        self.assertFalse(PolygonReturn.objects.exists())

    def test_prepare_refuses_a_redirected_post(self):
        quote = permit_quote()
        quote['steps'][0]['items'][0]['data']['post']['endpoint'] = '/execute/swap'
        self.client_mock.quote.return_value = quote
        with self.assertRaises(pr.PolygonReturnError):
            self.prepare()

    def test_prepare_refuses_below_minimum(self):
        self.balance.return_value = pr.MIN_UNITS - 1
        with self.assertRaisesMessage(pr.PolygonReturnError, pr.NOTHING):
            self.prepare()

    # ---------------------------------------------------------- submit

    def test_submit_verifies_signature_and_forwards_it(self):
        ret = self.prepare()
        signature = sign(ret)
        ret = pr.submit(self.owner, ret.internal_id, signature, client=self.client_mock)
        self.assertEqual(ret.status, 'submitted')
        self.assertTrue(ret.post_accepted)
        self.client_mock.execute_permit.assert_called_once_with(
            {'kind': 'eip3009', 'requestId': REQ, 'api': 'swap'}, signature)
        self.assertEqual(pr.state(self.owner)['state'], 'in_progress')

    def test_submit_refuses_another_signer(self):
        ret = self.prepare()
        other = EthAccount.create()
        bad = '0x' + EthAccount.unsafe_sign_hash(pr.digest(ret), other.key).signature.hex().removeprefix('0x')
        with self.assertRaises(pr.PolygonReturnError):
            pr.submit(self.owner, ret.internal_id, bad, client=self.client_mock)
        self.client_mock.execute_permit.assert_not_called()
        ret.refresh_from_db()
        self.assertEqual(ret.status, 'quoted')

    def test_submit_refuses_an_expired_window(self):
        ret = self.prepare()
        PolygonReturn.objects.filter(pk=ret.pk).update(valid_before=int(time.time()) + 10)
        ret.refresh_from_db()
        with self.assertRaises(pr.PolygonReturnError):
            pr.submit(self.owner, ret.internal_id, sign(ret), client=self.client_mock)

    def test_submit_retry_is_idempotent_and_post_failure_is_retried(self):
        from payment_accounts.relay import RelayError
        ret = self.prepare()
        signature = sign(ret)
        self.client_mock.execute_permit.side_effect = RelayError('Relay is temporarily unavailable')
        ret = pr.submit(self.owner, ret.internal_id, signature, client=self.client_mock)
        self.assertEqual((ret.status, ret.post_accepted), ('submitted', False))
        self.client_mock.execute_permit.side_effect = None
        self.client_mock.status.return_value = {'status': 'waiting'}
        ret = pr.reconcile(ret, client=self.client_mock)
        self.assertTrue(ret.post_accepted)
        self.assertEqual(pr.submit(self.owner, ret.internal_id, signature, client=self.client_mock).pk, ret.pk)

    def test_new_prepare_waits_for_the_open_return(self):
        ret = self.prepare()
        pr.submit(self.owner, ret.internal_id, sign(ret), client=self.client_mock)
        with self.assertRaisesMessage(pr.PolygonReturnError, pr.BUSY):
            self.prepare()

    # ---------------------------------------------------------- reconcile

    def submitted(self):
        ret = self.prepare()
        return pr.submit(self.owner, ret.internal_id, sign(ret), client=self.client_mock)

    def test_success_needs_a_final_bsc_receipt_to_the_person(self):
        ret = self.submitted()
        self.client_mock.status.return_value = {'status': 'success', 'txHashes': [OUT_HASH], 'inTxHashes': [IN_HASH]}
        with mock.patch('payment_accounts.bridge_chain.final_receipt', return_value=None):
            self.assertEqual(pr.reconcile(ret, client=self.client_mock).status, 'submitted')
        with mock.patch('payment_accounts.bridge_chain.final_receipt', return_value={'status': '0x1'}), \
                mock.patch('payment_accounts.bridge_chain.received_units', return_value=25_930_000 * 10**12) as rec:
            ret = pr.reconcile(ret, client=self.client_mock)
        self.assertEqual(rec.call_args.args[1:], ('BSC:USDT', ADDR))
        self.assertEqual((ret.status, ret.destination_tx_hash, ret.source_tx_hash), ('delivered', OUT_HASH, IN_HASH))

    @mock.patch('config.ops_alerts.send_ops_alert', return_value=True)
    def test_short_delivery_goes_to_review(self, alert):
        ret = self.submitted()
        self.client_mock.status.return_value = {'status': 'success', 'txHashes': [OUT_HASH]}
        with mock.patch('payment_accounts.bridge_chain.final_receipt', return_value={'status': '0x1'}), \
                mock.patch('payment_accounts.bridge_chain.received_units', return_value=1):
            ret = pr.reconcile(ret, client=self.client_mock)
        self.assertEqual((ret.status, ret.failure_code), ('needs_review', 'delivery_below_minimum'))
        alert.assert_called_once()

    @mock.patch('config.ops_alerts.send_ops_alert', return_value=True)
    def test_refund_reopens_the_card(self, alert):
        ret = self.submitted()
        self.client_mock.status.return_value = {'status': 'refund'}
        self.assertEqual(pr.reconcile(ret, client=self.client_mock).status, 'refunded')
        self.assertEqual(pr.state(self.owner)['state'], 'available')

    def test_unused_signature_expires_after_its_window(self):
        ret = self.submitted()
        PolygonReturn.objects.filter(pk=ret.pk).update(valid_before=int(time.time()) - pr.EXPIRE_GRACE_SECONDS - 5)
        ret.refresh_from_db()
        self.client_mock.status.return_value = {'status': 'waiting'}
        with mock.patch.object(pr, 'authorization_used', return_value=True):
            self.assertEqual(pr.reconcile(ret, client=self.client_mock).status, 'submitted')
        with mock.patch.object(pr, 'authorization_used', return_value=None):
            self.assertEqual(pr.reconcile(ret, client=self.client_mock).status, 'submitted')
        with mock.patch.object(pr, 'authorization_used', return_value=False):
            self.assertEqual(pr.reconcile(ret, client=self.client_mock).status, 'expired')

    def test_unreadable_relay_still_expires_by_usdc_state(self):
        ret = self.submitted()
        PolygonReturn.objects.filter(pk=ret.pk).update(valid_before=int(time.time()) - pr.EXPIRE_GRACE_SECONDS - 5)
        ret.refresh_from_db()
        from payment_accounts.relay import RelayError
        self.client_mock.status.side_effect = RelayError('Relay request failed', status_code=404)
        with mock.patch.object(pr, 'authorization_used', return_value=False):
            self.assertEqual(pr.reconcile(ret, client=self.client_mock).status, 'expired')

    def test_relay_rejection_frees_the_money_at_once(self):
        from payment_accounts.relay import RelayError
        ret = self.prepare()
        self.client_mock.execute_permit.side_effect = RelayError('bad permit', status_code=400)
        with mock.patch.object(pr, 'authorization_used', return_value=False):
            ret = pr.submit(self.owner, ret.internal_id, sign(ret), client=self.client_mock)
        self.assertEqual((ret.status, ret.failure_code), ('failed', 'relay_rejected_400'))
        self.assertEqual(pr.state(self.owner)['state'], 'available')

    def test_rejected_repost_stays_submitted(self):
        from payment_accounts.relay import RelayError
        ret = self.prepare()
        self.client_mock.execute_permit.side_effect = RelayError('Relay is temporarily unavailable')
        ret = pr.submit(self.owner, ret.internal_id, sign(ret), client=self.client_mock)
        self.client_mock.execute_permit.side_effect = RelayError('duplicate', status_code=400)
        self.client_mock.status.return_value = {'status': 'waiting'}
        with mock.patch.object(pr, 'authorization_used', return_value=False):
            ret = pr.reconcile(ret, client=self.client_mock)
        self.assertEqual(ret.status, 'submitted')

    def test_unreadable_usdc_still_reaches_review(self):
        ret = self.submitted()
        PolygonReturn.objects.filter(pk=ret.pk).update(
            valid_before=int(time.time()) - pr.EXPIRE_GRACE_SECONDS - 5,
            submitted_at=timezone.now() - timedelta(seconds=pr.REVIEW_AFTER_SECONDS + 5))
        ret.refresh_from_db()
        self.client_mock.status.return_value = {'status': 'waiting'}
        with mock.patch.object(pr, 'authorization_used', return_value=None), \
                mock.patch('config.ops_alerts.send_ops_alert', return_value=True):
            self.assertEqual(pr.reconcile(ret, client=self.client_mock).status, 'needs_review')

    @mock.patch('config.ops_alerts.send_ops_alert', return_value=True)
    def test_two_failures_in_a_day_pause_the_silent_retry(self, alert):
        for i in range(2):
            PolygonReturn.objects.create(
                confio_account=self.owner, address=ADDR, status='refunded', amount_units='26000000',
                amount_out='1', amount_out_min='1', request_id='0x' + f'{i:064x}', receiver=RECEIVER,
                nonce=NONCE, valid_before=1)
        self.assertEqual(pr.state(self.owner)['state'], 'none')
        with self.assertRaisesMessage(pr.PolygonReturnError, pr.BUSY):
            self.prepare()
        alert.assert_called()

    def test_open_provider_journey_is_never_swept(self):
        with mock.patch.object(pr, 'provider_flow_open', return_value=True):
            self.assertEqual(pr.state(self.owner)['state'], 'none')
            with self.assertRaisesMessage(pr.PolygonReturnError, pr.BUSY):
                self.prepare()
        self.client_mock.quote.assert_not_called()

    def test_refused_quote_is_not_retried_for_the_same_amount(self):
        self.client_mock.quote.return_value = permit_quote(amount=1)
        with self.assertRaises(pr.PolygonReturnError):
            self.prepare()
        self.assertEqual(pr.state(self.owner)['state'], 'none')

    def test_return_under_review_pauses_silent_retries(self):
        PolygonReturn.objects.create(
            confio_account=self.owner, address=ADDR, status='needs_review', amount_units='26000000',
            amount_out='1', amount_out_min='1', request_id='0x' + '77' * 32, receiver=RECEIVER,
            nonce=NONCE, valid_before=1)
        self.assertEqual(pr.state(self.owner)['state'], 'none')
        with self.assertRaisesMessage(pr.PolygonReturnError, pr.BUSY):
            self.prepare()

    def test_rate_limited_first_post_is_retried_not_failed(self):
        from payment_accounts.relay import RelayError
        ret = self.prepare()
        self.client_mock.execute_permit.side_effect = RelayError('slow down', status_code=429)
        with mock.patch.object(pr, 'authorization_used', return_value=False):
            ret = pr.submit(self.owner, ret.internal_id, sign(ret), client=self.client_mock)
        self.assertEqual((ret.status, ret.post_accepted), ('submitted', False))

    def full_quote(self, recipient=ADDR):
        """A permit quote complete enough for RelayClient.validate_quote."""
        usdt = '0x55d398326f99059ff775485246999027b3197955'
        quote = permit_quote()
        out, minimum = str(25_930_000 * 10**12), str(25_500_000 * 10**12)
        cur = lambda chain, addr, dec: {'currency': {'chainId': chain, 'address': addr, 'decimals': dec}}
        quote['details'] = {
            'sender': ADDR, 'recipient': recipient,
            'currencyIn': dict(cur(137, USDC, 6), amount='26000000'),
            'currencyOut': dict(cur(56, usdt, 18), amount=out, minimumAmount=minimum),
            'refundCurrency': cur(137, USDC, 6),
        }
        quote['protocol'] = {'v2': {'orderData': {
            'inputs': [{'payment': {'chainId': 'polygon', 'currency': USDC, 'amount': '26000000'},
                        'refunds': [{'chainId': 'polygon', 'currency': USDC, 'recipient': ADDR}]}],
            'output': {'chainId': 'bnb', 'calls': [], 'payments': [
                {'currency': usdt, 'recipient': recipient, 'minimumAmount': minimum, 'expectedAmount': out}]},
            'fees': [],
        }}}
        return quote

    def test_real_client_accepts_a_complete_permit_quote(self):
        from payment_accounts.relay import RelayClient
        client = RelayClient()
        with mock.patch.object(client, '_request', return_value=self.full_quote()) as req:
            ret = pr.prepare(self.owner, client=client)
        self.assertTrue(req.call_args.kwargs['body']['usePermit'])
        self.assertEqual((ret.status, ret.amount_out_min), ('quoted', str(25_500_000 * 10**12)))

    def test_real_client_refuses_another_recipient_before_any_row(self):
        from payment_accounts.relay import RelayClient, RelayError
        client = RelayClient()
        bad = self.full_quote(recipient='0x' + '9' * 40)
        with mock.patch.object(client, '_request', return_value=bad):
            with self.assertRaisesMessage(RelayError, 'Relay recipient or sender mismatch'):
                client.quote('POL:USDC', 'BSC:USDT', '26000000', source_address=ADDR,
                             destination_address=ADDR, permit=True)
            with self.assertRaises(pr.PolygonReturnError):
                pr.prepare(self.owner, client=client)
        self.assertFalse(PolygonReturn.objects.exists())

    def provider_accounts(self):
        from payment_accounts.models import FinancialAccount, ProviderProfile
        profile = ProviderProfile.objects.create(
            confio_account=self.owner, provider='infinia', owner_type='individual', status='active')
        crypto = FinancialAccount.objects.create(
            provider_profile=profile, provider_account_id='crypto', country='XXX', asset='USDC_POL',
            ownership_structure='provider_named', status='active')
        local = FinancialAccount.objects.create(
            provider_profile=profile, provider_account_id='local', country='COL', asset='COP',
            ownership_structure='provider_named', status='active')
        return local, crypto

    def infinia_journey(self, stage, failure_code=''):
        import uuid
        from payment_accounts.models import InfiniaJourney, MoneyFlow
        local, crypto = self.provider_accounts()
        flow = MoneyFlow.objects.create(confio_account=self.owner, kind='fund', source_asset='COP', source_amount='30')
        return InfiniaJourney.objects.create(
            confio_account=self.owner, money_flow=flow, request_id=uuid.uuid4(), local_account=local,
            crypto_account=crypto, direction='to_wallet', minimum_fx_output='1', minimum_wallet_output='0.9',
            stage=stage, failure_code=failure_code, wallet_address=ADDR)

    def test_live_infinia_journey_blocks(self):
        self.infinia_journey('awaiting_wallet_authorization')
        self.assertTrue(pr.provider_flow_open(self.owner))
        self.assertEqual(pr.state(self.owner)['state'], 'none')

    def test_parked_infinia_journey_does_not_hold_the_money(self):
        self.infinia_journey('needs_review', failure_code='return_bridge_refunded')
        self.assertFalse(pr.provider_flow_open(self.owner))
        self.assertEqual(pr.state(self.owner)['state'], 'available')

    def test_finished_infinia_journey_does_not_block(self):
        self.infinia_journey('completed')
        self.assertFalse(pr.provider_flow_open(self.owner))

    def test_reconcile_leaves_the_first_hand_off_to_submit(self):
        ret = self.prepare()
        PolygonReturn.objects.filter(pk=ret.pk).update(status='submitted', signature=sign(ret),
                                                       submitted_at=timezone.now())
        ret.refresh_from_db()
        self.assertEqual(pr.reconcile(ret, client=self.client_mock).status, 'submitted')
        self.client_mock.status.assert_not_called()
        self.client_mock.execute_permit.assert_not_called()

    def test_provider_flow_query_runs(self):
        self.assertFalse(pr.provider_flow_open(self.owner))

    def test_home_balance_read_is_cached_and_single_flight(self):
        cache.clear()
        cache.add(pr._cache_key(ADDR) + ':reading', 1, 10)
        self.assertIsNone(pr.balance(ADDR))
        self.balance.assert_not_called()

    def test_task_runs_reconcile(self):
        from payment_accounts.tasks import reconcile_polygon_returns
        ret = self.submitted()
        with mock.patch('payment_accounts.polygon_return.reconcile', side_effect=lambda r: r) as rec:
            reconcile_polygon_returns()
        self.assertEqual(rec.call_args.args[0].pk, ret.pk)


class PolygonReturnDigestTests(TestCase):
    def test_digest_matches_standard_eip712(self):
        ret = PolygonReturn(address=ADDR, receiver=RECEIVER, amount_units='26000000',
                            valid_before=1793897703, nonce=NONCE)
        from cusd_plus.sponsor_7702 import recover_intent_signer
        self.assertEqual(recover_intent_signer(pr.digest(ret), sign(ret)).lower(), ADDR)
