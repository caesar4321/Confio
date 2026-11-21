"""Calldata and event encoding against the frozen Solidity interfaces: the
selectors and topics are computed from the signatures in the .sol files."""
import re
from pathlib import Path

from django.test import SimpleTestCase
from eth_abi import encode as abi_encode
from eth_utils import keccak

from smart_account import abi

INTERFACES = Path(__file__).resolve().parents[2] / 'contracts' / 'smart_account' / 'interfaces'
STRUCTS = {'RuleInput': abi.RULE_INPUT_ABI, 'Rule': abi.RULE_ABI, 'SaleLeg': abi.SALE_LEG_ABI,
           'ConfioSale': '(address,address)'}
ENUMS = {'Plan', 'RuleKind', 'Frequency'}


def _canonical(type_text: str) -> str:
    """'RuleInput calldata input' -> the ABI tuple; 'Plan plan_' -> uint8."""
    tokens = [t for t in type_text.strip().split() if t not in ('calldata', 'memory', 'indexed')]
    base = tokens[0]
    suffix = ''
    if base.endswith('[]'):
        base, suffix = base[:-2], '[]'
    if base in ENUMS:
        base = 'uint8'
    return STRUCTS.get(base, base) + suffix


def _signatures(source: str, keyword: str) -> dict:
    out = {}
    for name, params in re.findall(keyword + r'\s+(\w+)\(([^)]*)\)', source):
        types = [_canonical(p) for p in params.split(',') if p.strip()]
        out.setdefault(name, []).append(f"{name}({','.join(types)})")
    return out


class InterfaceParityTests(SimpleTestCase):
    def setUp(self):
        self.account = (INTERFACES / 'IConfioSmartAccount.sol').read_text()
        self.factory = (INTERFACES / 'IConfioSmartAccountFactory.sol').read_text()

    def test_every_encoded_function_matches_the_interface_signature(self):
        declared = _signatures(self.account, 'function')
        declared.update({k: v for k, v in _signatures(self.factory, 'function').items()
                         if k in abi.FACTORY_FUNCTIONS})
        for name, (signature, _types) in abi.FUNCTIONS.items():
            sol_name = signature.split('(')[0]
            self.assertIn(sol_name, declared, name)
            self.assertIn(signature, declared[sol_name], f'{name}: {signature} not in {declared[sol_name]}')
            self.assertEqual(abi.SELECTORS[name], keccak(text=signature)[:4].hex())

    def test_factory_views_match_the_interface(self):
        declared = _signatures(self.factory, 'function')
        for name, (signature, arg_types, _out) in abi.FACTORY_VIEWS.items():
            self.assertIn(signature, declared.get(name, []), name)
            self.assertEqual(signature, f"{name}({','.join(arg_types)})")
            returns = re.search(r'function\s+%s\([^)]*\)\s+external\s+view\s+returns\s*\((\w+)' % name,
                                self.factory).group(1)
            self.assertEqual([returns], _out, name)

    def test_overloaded_withdraws_have_distinct_selectors(self):
        self.assertNotEqual(abi.SELECTORS['withdraw'], abi.SELECTORS['withdrawTo'])
        self.assertNotEqual(abi.SELECTORS['withdrawAll'], abi.SELECTORS['withdrawAllTo'])
        self.assertEqual(abi.SELECTORS['withdraw'], 'f3fef3a3')  # withdraw(address,uint256)
        self.assertEqual(abi.SEL_TRANSFER, 'a9059cbb')

    def test_every_state_changing_interface_function_is_encodable(self):
        views = set(re.findall(r'function\s+(\w+)\([^)]*\)\s+external\s+view', self.account))
        declared = set(_signatures(self.account, 'function')) - views - {'initialize'}
        encoded = {sig.split('(')[0] for sig, _ in abi.FUNCTIONS.values()}
        self.assertEqual(declared - encoded, set())

    def test_event_topics_match_the_interface(self):
        for source, table in ((self.account, abi.ACCOUNT_EVENTS), (self.factory, abi.FACTORY_EVENTS)):
            declared = _signatures(source, 'event')
            self.assertEqual(set(declared), set(table))
            for name, fields in table.items():
                self.assertEqual([abi.event_signature(name, fields)], declared[name])
                indexed = re.search(r'event\s+%s\(([^)]*)\)' % name, source).group(1)
                flags = ['indexed' in p for p in indexed.split(',') if p.strip()]
                self.assertEqual(flags, [i for _t, i, _n in fields], name)


class EncodingTests(SimpleTestCase):
    A, B = '0x' + '11' * 20, '0x' + '22' * 20

    def test_subscribe_calldata(self):
        data = abi.encode_call('subscribe', abi.PLAN_ANNUAL, 149_990000000000000000)
        self.assertEqual(data[:10], '0x' + keccak(text='subscribe(uint8,uint256)')[:4].hex())
        self.assertEqual(int(data[10:74], 16), 2)
        self.assertEqual(int(data[74:138], 16), 149_990000000000000000)

    def test_roundtrip_and_non_canonical_bytes_are_refused(self):
        rule = abi.rule_input('send', 'weekly', self.A, payee=self.B, amount_usd_wei=25 * 10 ** 18)
        data = abi.encode_call('createRule', rule)
        name, args = abi.decode_call(data)
        self.assertEqual(name, 'createRule')
        self.assertEqual(args[0][0], abi.RULE_SEND)
        self.assertEqual(args[0][1], abi.FREQUENCY_IDS['weekly'])
        self.assertEqual(args[0][4].lower(), self.B)
        with self.assertRaises(ValueError):
            abi.decode_call(data + '00' * 32)
        self.assertEqual(abi.decode_call('0xdeadbeef'), (None, None))

    def test_rule_data_shapes(self):
        self.assertEqual(abi.send_rule_data(1, 5), abi_encode(['uint8', 'uint256'], [1, 5]))
        self.assertEqual(abi.payout_rule_data(self.A, 7), abi_encode(['address', 'uint256'], [self.A, 7]))
        self.assertEqual(abi.buy_rule_data(self.A, '0x1234', 9),
                         abi_encode(['address', 'bytes', 'uint256'], [self.A, b'\x12\x34', 9]))

    def test_forced_sale_encodes_legs(self):
        data = abi.encode_call('forcedSale', [(self.A, self.B, 10, b'\x01\x02')], 5, abi.ZERO_ADDRESS, 0)
        name, args = abi.decode_call(data)
        self.assertEqual(name, 'forcedSale')
        self.assertEqual(args[0][0][2], 10)
        self.assertEqual(args[1], 5)

    def test_decode_log_with_indexed_arguments(self):
        fields = abi.ACCOUNT_EVENTS['ClaimInitiated']
        log = {'topics': [abi.event_topic('ClaimInitiated', fields), '0x' + self.A[2:].rjust(64, '0')],
               'data': '0x' + abi_encode(['uint64'], [1_900_000_000]).hex()}
        self.assertEqual(abi.decode_log(log), ('ClaimInitiated', {'beneficiary': self.A, 'executableAt': '1900000000'}))
        fee = abi.ACCOUNT_EVENTS['FeeCollected']
        log = {'topics': [abi.event_topic('FeeCollected', fee)],
               'data': '0x' + abi_encode(['uint8', 'uint256', 'uint256', 'uint256', 'uint256', 'uint64'],
                                         [2, 149, 149, 0, 0, 77]).hex()}
        name, args = abi.decode_log(log)
        self.assertEqual((name, args['plan'], args['paidUntil']), ('FeeCollected', '2', '77'))
        self.assertIsNone(abi.decode_log({'topics': ['0x' + '00' * 32], 'data': '0x'}))

    def test_designation_approval_key_and_relay_allowlist(self):
        # keccak256(abi.encode(beneficiary, window)), as the factory keys it.
        self.assertEqual(abi.designation_key(self.A, 90 * 86400),
                         keccak(abi_encode(['address', 'uint256'], [self.A, 90 * 86400])))
        self.assertEqual(set(abi.RELAY_KINDS), set(abi.RELAY_KIND_CALLS))
        for kind, (target, name) in abi.RELAY_KIND_CALLS.items():
            self.assertIn(target, ('account', 'factory'))
            if target == 'factory':
                self.assertIn(name, abi.FACTORY_FUNCTIONS - {'createAccount'})
            else:
                self.assertIn(name, abi.RELAYER_FUNCTIONS | abi.KEEPER_FUNCTIONS)
        # No owner or beneficiary function is ever a relayer call.
        self.assertFalse({n for _t, n in abi.RELAY_KIND_CALLS.values()}
                         & (abi.OWNER_FUNCTIONS | abi.BENEFICIARY_FUNCTIONS))

    def test_classify(self):
        account = '0x' + '33' * 20
        self.assertEqual(abi.classify([abi.call(account, abi.encode_call('trade', self.A, b'', self.A, self.B, 1, 1))]),
                         'smart_trade')
        self.assertEqual(abi.classify([abi.call(account, abi.encode_call('cancelClaim'))]), 'smart_claim')
        # A personal-wallet batch with a trailing cancelClaim is not an account batch.
        self.assertIsNone(abi.classify([abi.transfer_call(self.A, self.B, 1),
                                        abi.call(account, abi.encode_call('cancelClaim'))]))
        self.assertIsNone(abi.classify([abi.transfer_call(self.A, self.B, 1)]))
