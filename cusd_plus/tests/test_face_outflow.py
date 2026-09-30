from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, override_settings

from cusd_plus.face_step_up import claim_external_outflow, has_external_outflow
from cusd_plus import sponsor_7702 as sponsor


SIGNER = '0x' + '11' * 20
RECIPIENT = '0x' + '22' * 20
VAULT = '0x' + '33' * 20


def call(selector, words, target=VAULT):
    return {'to': target, 'value': '0', 'data': '0x' + selector + ''.join(
        (word.removeprefix('0x') if isinstance(word, str) else format(word, 'x')).rjust(64, '0')
        for word in words)}


@override_settings(CUSD_PLUS_VAULT_ADDRESS=VAULT, CUSD_PLUS_PANCAKE_ROUTER=VAULT)
class FaceOutflowTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch('security.identity_reuse.outgoing_identity_restriction', return_value='')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_self_conversions_and_approvals_do_not_claim(self):
        calls = [call(sponsor.SEL_APPROVE, [VAULT, 10], sponsor.USDT_BSC),
                 call(sponsor.SEL_REDEEM_TO_USDT, [10, 0, SIGNER])]
        with mock.patch('security.face_step_up.require_face_step_up') as gate:
            self.assertEqual(claim_external_outflow(
                object(), None, calls, SIGNER, namespace='test', identifier='same', payload={}), '')
        gate.assert_not_called()

    def test_external_transfer_and_direct_redeem_are_outgoing(self):
        self.assertTrue(has_external_outflow([
            call(sponsor.SEL_TRANSFER, [RECIPIENT, 10], sponsor.USDT_BSC)], SIGNER))
        self.assertTrue(has_external_outflow([
            call(sponsor.SEL_REDEEM_TO_USDT, [10, 0, RECIPIENT])], SIGNER))
        self.assertFalse(has_external_outflow([
            call(sponsor.SEL_TRANSFER, [SIGNER, 10], sponsor.USDT_BSC)], SIGNER))

    def test_business_external_transfer_remains_exempt(self):
        with mock.patch('security.face_step_up.require_face_step_up') as gate:
            self.assertEqual(claim_external_outflow(
                object(), {'account_type': 'business'},
                [call(sponsor.SEL_TRANSFER, [RECIPIENT, 10], sponsor.USDT_BSC)],
                SIGNER, namespace='test', identifier='same', payload={}), '')
        gate.assert_not_called()

    def test_claim_is_bound_to_exact_payload(self):
        transfer = call(sponsor.SEL_TRANSFER, [RECIPIENT, 10], sponsor.USDT_BSC)
        with mock.patch('security.face_step_up.require_face_step_up', return_value='face') as gate:
            for amount in (10, 10, 11):
                result = claim_external_outflow(
                    object(), None, [transfer], SIGNER, namespace='test',
                    identifier='same-request', payload={'amount': amount, 'source': SIGNER})
                self.assertEqual(result, 'face')
        keys = [args.kwargs['action_key'] for args in gate.call_args_list]
        self.assertEqual(keys[0], keys[1])
        self.assertNotEqual(keys[0], keys[2])
        self.assertTrue(all(args.kwargs['consume'] for args in gate.call_args_list))

    def test_legacy_unknown_and_foreign_conversion_recipients_require_face(self):
        self.assertTrue(has_external_outflow([call('deadbeef', [])], SIGNER, legacy=True))
        self.assertTrue(has_external_outflow([
            call(sponsor.SEL_SUBSCRIBE_AND_MINT, [10, 0, RECIPIENT])], SIGNER, legacy=True))
        self.assertFalse(has_external_outflow([
            call('7ff36ab5', [0, 128, SIGNER, 99])], SIGNER, legacy=True))
        self.assertTrue(has_external_outflow([
            call(sponsor.SEL_APPROVE, [RECIPIENT, 10])], SIGNER, legacy=True))

    def test_legacy_gate_prevents_broadcast(self):
        from cusd_plus.schema import SubmitBscTransaction
        from eth_account import Account
        key = '0x' + '11' * 32
        signer = Account.from_key(key).address.lower()
        data = call(sponsor.SEL_TRANSFER, [RECIPIENT, 10], sponsor.USDT_BSC)['data']
        signed = Account.sign_transaction({
            'chainId': 56, 'nonce': 1, 'gasPrice': 1, 'gas': 100000,
            'to': bytes.fromhex(sponsor.USDT_BSC[2:]), 'value': 0, 'data': data,
        }, key)
        raw = '0x' + bytes(signed.raw_transaction).hex()
        info = SimpleNamespace(context=SimpleNamespace(user=SimpleNamespace(id=1, is_authenticated=True)))
        with self.settings(BSC_CHAIN_ID=56, CUSD_CONVERSION_FEE_ENABLED=False), \
                mock.patch('cusd_plus.schema._bsc_rate_limited', return_value=False), \
                mock.patch('users.jwt_context.get_jwt_business_context_with_validation', return_value=None), \
                mock.patch('cusd_plus.schema._active_bsc_address', return_value=signer), \
                mock.patch('security.face_step_up.require_face_step_up', return_value='face') as gate, \
                mock.patch('cusd_plus.tasks._rpc') as rpc:
            result = SubmitBscTransaction.mutate(None, info, raw)
        self.assertFalse(result.success)
        self.assertEqual(result.error, 'face')
        gate.assert_called_once()
        rpc.assert_not_called()
