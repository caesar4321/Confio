"""ABI of ConfioSmartAccount and its factory: selectors, calldata encoders
and event decoding.

Source of truth: contracts/smart_account/interfaces/IConfioSmartAccount.sol
and IConfioSmartAccountFactory.sol. Pure module (no Django models, no RPC) so
cusd_plus/sponsor_7702.py can import it at load time.
"""
from __future__ import annotations

import re

from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak

ZERO_ADDRESS = '0x' + '00' * 20
ZERO_BYTES32 = b'\x00' * 32

PLAN_NONE, PLAN_MONTHLY, PLAN_ANNUAL = 0, 1, 2
PLAN_IDS = {'monthly': PLAN_MONTHLY, 'annual': PLAN_ANNUAL}
PLAN_KEYS = {v: k for k, v in PLAN_IDS.items()}
PERIOD_DAYS = {'monthly': 30, 'annual': 365}

# Card (decision 35) is appended: the values of the others are fixed.
RULE_SEND, RULE_PAYOUT, RULE_BUY, RULE_CARD = 0, 1, 2, 3
# v2 (IConfioSmartAccountV2.RuleKind): Trade and Purchase appended. Only a v2
# account stores them; a v1 account's createRule reverts on these values.
RULE_TRADE, RULE_PURCHASE = 4, 5
RULE_KIND_IDS = {'send': RULE_SEND, 'payout': RULE_PAYOUT, 'buy': RULE_BUY, 'card': RULE_CARD,
                 'trade': RULE_TRADE, 'purchase': RULE_PURCHASE}
RULE_KIND_KEYS = {v: k for k, v in RULE_KIND_IDS.items()}
# Kinds the relayer runs with executeRule. A Card rule is pulled by its
# allowlisted spender (cardPull); executeRule on it reverts BadRule.
EXECUTABLE_RULE_KINDS = ('send', 'payout', 'buy')

FREQUENCY_IDS = {'daily': 0, 'weekly': 1, 'biweekly': 2, 'monthly': 3}
FREQUENCY_KEYS = {v: k for k, v in FREQUENCY_IDS.items()}
MIN_GAP_DAYS = {'daily': 1, 'weekly': 7, 'biweekly': 14, 'monthly': 28}

# Which Confío dollar; values match ConfioSwapRouter's source/dest.
DOLLAR_PLUS, DOLLAR = 0, 1

STATUS_KEYS = {0: 'none', 1: 'active', 2: 'cancel_pending', 3: 'expired', 4: 'inherited'}
BILLING_KEYS = {0: 'current', 1: 'payment_due', 2: 'notice', 3: 'sale_allowed'}

RULE_INPUT_ABI = '(uint8,uint8,address,address,address,bytes32,uint256,uint64)'
# rule(id): ... nextRunAt, epoch. `active` is effective: false for a rule of
# an earlier subscription epoch (spec 4.4), whatever was stored.
RULE_ABI = '(uint8,uint8,bool,address,address,address,bytes32,uint256,uint64,uint64)'
SALE_LEG_ABI = '(address,address,uint256,bytes)'

# name -> (signature, argument types)
FUNCTIONS = {
    # owner
    'subscribe': ('subscribe(uint8,uint256)', ['uint8', 'uint256']),
    'changePlan': ('changePlan(uint8)', ['uint8']),
    'cancelSubscription': ('cancelSubscription()', []),
    'undoCancel': ('undoCancel()', []),
    'withdraw': ('withdraw(address,uint256)', ['address', 'uint256']),
    'withdrawAll': ('withdrawAll(address[])', ['address[]']),
    'withdrawTo': ('withdraw(address,uint256,address)', ['address', 'uint256', 'address']),
    'withdrawAllTo': ('withdrawAll(address[],address)', ['address[]', 'address']),
    'trade': ('trade(address,bytes,address,address,uint256,uint256)',
              ['address', 'bytes', 'address', 'address', 'uint256', 'uint256']),
    'createRule': (f'createRule({RULE_INPUT_ABI})', [RULE_INPUT_ABI]),
    'updateRule': (f'updateRule(uint256,{RULE_INPUT_ABI})', ['uint256', RULE_INPUT_ABI]),
    'cancelRule': ('cancelRule(uint256)', ['uint256']),
    'setBeneficiary': ('setBeneficiary(address,uint64)', ['address', 'uint64']),
    'withdrawDesignation': ('withdrawDesignation()', []),
    'removeBeneficiary': ('removeBeneficiary()', []),
    'cancelClaim': ('cancelClaim()', []),
    # beneficiary
    'acceptBeneficiary': ('acceptBeneficiary()', []),
    'initiateClaim': ('initiateClaim()', []),
    'executeClaim': ('executeClaim()', []),
    # relayer
    'collectFee': ('collectFee()', []),
    'startPaymentNotice': ('startPaymentNotice()', []),
    'forcedSale': (f'forcedSale({SALE_LEG_ABI}[],uint256,address,uint256)',
                   [f'{SALE_LEG_ABI}[]', 'uint256', 'address', 'uint256']),
    'executeRule': ('executeRule(uint256,bytes,address,uint256)', ['uint256', 'bytes', 'address', 'uint256']),
    'convertUsdt': ('convertUsdt(uint8,uint256,address,uint256)', ['uint8', 'uint256', 'address', 'uint256']),
    # anyone
    'returnAsset': ('returnAsset(address)', ['address']),
    'latchConfioSale': ('latchConfioSale()', []),
    # card spender (decision 35): the issuer's allowlisted spender calls it,
    # never Confío's relay or an owner batch. Encoded for tests and decoding.
    'cardPull': ('cardPull(uint256,uint256)', ['uint256', 'uint256']),
    # factory
    'createAccount': ('createAccount()', []),
    # factory, relayer-only (audit fix to decision 26): a 1-hour approval of
    # the exact designation / acceptance the server checked.
    'approveDesignation': ('approveDesignation(address,address,uint64)', ['address', 'address', 'uint64']),
    'approveAcceptance': ('approveAcceptance(address,address)', ['address', 'address']),
}
FACTORY_FUNCTIONS = frozenset({'createAccount', 'approveDesignation', 'approveAcceptance'})

# Factory views chain.py reads, as (signature, argument types, return types);
# checked against the interface in test_abi. One current account per owner:
# accountOf moves to a new clone, one generation on, only after the previous
# one was inherited (spec 4.3, decision 33).
FACTORY_VIEWS = {
    'accountOf': ('accountOf(address)', ['address'], ['address']),
    'generationOf': ('generationOf(address)', ['address'], ['uint64']),
    'predictAddress': ('predictAddress(address)', ['address'], ['address']),
    'predictAddressAt': ('predictAddressAt(address,uint64)', ['address', 'uint64'], ['address']),
    # Card spenders (decision 35): the Safe's allowlist and global card pause.
    'isCardSpender': ('isCardSpender(address)', ['address'], ['bool']),
    'cardPaused': ('cardPaused()', [], ['bool']),
    'cardSpenderAllowed': ('cardSpenderAllowed(address)', ['address'], ['bool']),
}
# Account views that take arguments, as (signature, argument types, return
# types); the no-argument ones are chain._ACCOUNT_VIEWS.
ACCOUNT_ARG_VIEWS = {
    # Card: gross USD taken in the period that starts at rule(id).nextRunAt
    # (stale, in effect zero, once that period ended).
    'cardSpentUsd': ('cardSpentUsd(uint256)', ['uint256'], ['uint256']),
}


def selector(signature: str) -> str:
    return keccak(text=signature)[:4].hex()


# Custom errors of ConfioSmartAccount the server acts on, by name; checked
# against the contract source in test_abi. A relayer call's simulation
# carries the 4-byte selector of the revert (revert_error).
ACCOUNT_ERRORS = (
    'NotOwner', 'NotRelayer', 'RelayerPaused', 'BadState', 'IsInherited', 'BadPlan', 'FeeAboveMax',
    'DollarsShort', 'DollarsCover', 'AlreadySold', 'CapExceeded', 'BadRule', 'TooEarly', 'Slippage',
)
# What each means for the owner, in Spanish; unknown ones get no message.
ERROR_MESSAGES = {
    'IsInherited': 'Esta Cuenta inteligente ya pasó a tu beneficiario.',
    'BadRule': 'Esa regla ya no está activa.',
    'BadState': 'Tu Cuenta inteligente no permite esta acción ahora.',
    'DollarsCover': 'Tus dólares cubren la renovación: no hace falta vender nada.',
}


SELECTORS = {name: selector(sig) for name, (sig, _types) in FUNCTIONS.items()}
NAME_BY_SELECTOR = {sel: name for name, sel in SELECTORS.items()}
SEL_TRANSFER = selector('transfer(address,uint256)')
SEL_TRADE = SELECTORS['trade']
SEL_CANCEL_CLAIM = SELECTORS['cancelClaim']
ERROR_SELECTORS = {selector(f'{name}()'): name for name in ACCOUNT_ERRORS}


def revert_error(text) -> str | None:
    """The account error named by a revert's data (as a node reports it in
    an eth_call failure: 0x + selector, possibly inside a message), or None.
    Only selectors in ACCOUNT_ERRORS are recognised."""
    found = re.findall(r'0x([0-9a-fA-F]{8})', str(text or ''))
    for candidate in found:
        name = ERROR_SELECTORS.get(candidate.lower())
        if name is not None:
            return name
    return None

OWNER_FUNCTIONS = frozenset({
    'subscribe', 'changePlan', 'cancelSubscription', 'undoCancel', 'withdraw', 'withdrawAll',
    'withdrawTo', 'withdrawAllTo', 'trade', 'createRule', 'updateRule', 'cancelRule',
    'setBeneficiary', 'withdrawDesignation', 'removeBeneficiary', 'cancelClaim',
})
BENEFICIARY_FUNCTIONS = frozenset({'acceptBeneficiary', 'initiateClaim', 'executeClaim'})
RELAYER_FUNCTIONS = frozenset({'collectFee', 'startPaymentNotice', 'forcedSale', 'executeRule', 'convertUsdt'})
KEEPER_FUNCTIONS = frozenset({'returnAsset', 'latchConfioSale'})
# Called by a card issuer's spender only; never in a batch or relay kind.
SPENDER_FUNCTIONS = frozenset({'cardPull'})

# Sponsored-batch kinds (blockchain.SponsoredBatch.kind) and the account
# functions each may contain besides deposits' ERC-20 transfer, the factory's
# createAccount and a trailing cancelClaim.
BATCH_KIND_FUNCTIONS = {
    'smart_subscribe': {'createAccount', 'subscribe'},
    'smart_deposit': set(),
    'smart_withdraw': {'withdraw', 'withdrawAll'},
    'smart_trade': {'trade'},
    'smart_rule': {'createRule', 'updateRule'},
    # Cancelling a rule stops money leaving: never under the identity hold.
    'smart_rule_cancel': {'cancelRule'},
    'smart_cancel': {'changePlan', 'cancelSubscription', 'undoCancel'},
    'smart_beneficiary': {'setBeneficiary', 'acceptBeneficiary'},
    'smart_beneficiary_remove': {'withdrawDesignation', 'removeBeneficiary'},
    'smart_claim': {'cancelClaim', 'initiateClaim', 'executeClaim'},
    'smart_inherited_withdraw': {'withdrawTo', 'withdrawAllTo'},
}
BATCH_KINDS = tuple(BATCH_KIND_FUNCTIONS)
# Not outgoing transfers to someone else (send_sponsored_batch identity list):
# money stays the signer's, or the call only protects them.
BATCH_KINDS_NOT_OUTGOING = (
    'smart_deposit', 'smart_withdraw', 'smart_trade', 'smart_cancel', 'smart_rule_cancel',
    'smart_beneficiary_remove', 'smart_claim', 'smart_inherited_withdraw',
)
# Relayer transactions (relayer.send_relayer_call): kind -> (target, the one
# function it may call). 'account' = the SmartAccount's own contract;
# 'factory' = the factory, with the account as the call's first argument.
# Nothing else is ever signed by the relayer path.
RELAY_KIND_CALLS = {
    'smart_collect_fee': ('account', 'collectFee'),
    'smart_payment_notice': ('account', 'startPaymentNotice'),
    'smart_forced_sale': ('account', 'forcedSale'),
    'smart_execute_rule': ('account', 'executeRule'),
    'smart_convert_usdt': ('account', 'convertUsdt'),
    'smart_return': ('account', 'returnAsset'),
    'smart_latch_confio': ('account', 'latchConfioSale'),
    'smart_designation_approval': ('factory', 'approveDesignation'),
    'smart_acceptance_approval': ('factory', 'approveAcceptance'),
}
RELAY_KINDS = tuple(RELAY_KIND_CALLS)
# Relayer kinds that never change a token balance of the account.
RELAY_KINDS_NO_BALANCE = ('smart_designation_approval', 'smart_acceptance_approval')

# Gas budgets. NOT fork-measured (the contracts were written in parallel):
# conservative figures, and every transaction is simulated under its budget.
GAS_PER_SELECTOR = {
    SELECTORS['createAccount']: 350_000,
    SELECTORS['subscribe']: 300_000,
    SELECTORS['changePlan']: 90_000,
    SELECTORS['cancelSubscription']: 90_000,
    SELECTORS['undoCancel']: 70_000,
    SELECTORS['withdraw']: 140_000,
    SELECTORS['withdrawTo']: 180_000,
    SELECTORS['createRule']: 260_000,
    SELECTORS['updateRule']: 200_000,
    SELECTORS['cancelRule']: 90_000,
    SELECTORS['setBeneficiary']: 160_000,
    SELECTORS['withdrawDesignation']: 90_000,
    SELECTORS['removeBeneficiary']: 110_000,
    SELECTORS['cancelClaim']: 90_000,
    SELECTORS['acceptBeneficiary']: 150_000,
    SELECTORS['initiateClaim']: 120_000,
    SELECTORS['executeClaim']: 200_000,
}
GAS_PER_WITHDRAWN_TOKEN = 110_000
GAS_TRADE_OVERHEAD = 250_000
RELAY_GAS = {
    'smart_collect_fee': 400_000,
    'smart_payment_notice': 150_000,
    'smart_convert_usdt': 1_100_000,
    'smart_return': 200_000,
    'smart_latch_confio': 150_000,
    'smart_designation_approval': 120_000,
    'smart_acceptance_approval': 120_000,
    # Measured in the spender's Foundry tests at about 540k (a cUSD+ pull),
    # never on BSC: simulated under this budget before every send.
    'smart_purchase_pull': 900_000,
}
RELAY_GAS_RULE = {'send': 1_100_000, 'payout': 1_200_000, 'buy_stock': 2_400_000, 'buy_crypto': 1_900_000}
RELAY_GAS_SALE_LEG = {'stock': 2_300_000, 'crypto': 1_700_000, 'confio': 1_700_000}
RELAY_GAS_SALE_BASE = 500_000
# Legs one forced sale may carry, and the gas it may then need: every leg at
# the largest leg budget. 9.7M, under a tenth of BSC's block gas limit
# (>= 100M since 2025), so a full sale is always includable.
MAX_SALE_LEGS = 4
RELAY_GAS_SALE_MAX = RELAY_GAS_SALE_BASE + MAX_SALE_LEGS * max(RELAY_GAS_SALE_LEG.values())


def encode_call(name: str, *args) -> str:
    """0x-prefixed lowercase calldata for one function."""
    _sig, types = FUNCTIONS[name]
    return '0x' + SELECTORS[name] + abi_encode(types, list(args)).hex()


def decode_call(data: str):
    """(function name, decoded args) or (None, None) for an unknown selector.
    Raises ValueError on trailing or non-canonical bytes."""
    data_hex = (data or '')[2:].lower()
    name = NAME_BY_SELECTOR.get(data_hex[:8])
    if name is None:
        return None, None
    _sig, types = FUNCTIONS[name]
    raw = bytes.fromhex(data_hex[8:])
    try:
        args = abi_decode(types, raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError('bad_calldata') from exc
    if abi_encode(types, args) != raw:
        raise ValueError('bad_calldata')
    return name, args


def call(to: str, data: str) -> dict:
    return {'to': to.lower(), 'value': '0', 'data': data.lower()}


def transfer_call(token: str, recipient: str, amount: int) -> dict:
    return call(token, '0x' + SEL_TRANSFER + abi_encode(['address', 'uint256'], [recipient, int(amount)]).hex())


def rule_input(kind: str, frequency: str, token_in: str, *, token_out: str = ZERO_ADDRESS,
               payee: str = ZERO_ADDRESS, payout_ref: bytes = ZERO_BYTES32,
               amount_usd_wei: int, first_run_at: int = 0) -> tuple:
    return (RULE_KIND_IDS[kind], FREQUENCY_IDS[frequency], token_in, token_out, payee,
            payout_ref, int(amount_usd_wei), int(first_run_at))


def send_rule_data(payee_dollar: int, min_out: int) -> bytes:
    return abi_encode(['uint8', 'uint256'], [payee_dollar, int(min_out)])


def payout_rule_data(destination: str, min_usdt_out: int) -> bytes:
    """cUSD rule: abi.encode(destination, minUsdtOut), a floor."""
    return abi_encode(['address', 'uint256'], [destination, int(min_usdt_out)])


def payout_plus_rule_data(destination: str, usdt_out: int, gross_cusd: int) -> bytes:
    """cUSD+ rule: abi.encode(destination, usdtOut, grossCusd). usdtOut is
    EXACT (grossCusd - CusdVault.feeFor(grossCusd)); the two-word cUSD form
    reverts on a cUSD+ rule (ConfioSmartAccount._runPayout)."""
    return abi_encode(['address', 'uint256', 'uint256'], [destination, int(usdt_out), int(gross_cusd)])


def buy_rule_data(venue: str, venue_calldata: str, min_out: int) -> bytes:
    return abi_encode(['address', 'bytes', 'uint256'],
                      [venue, bytes.fromhex(venue_calldata[2:]), int(min_out)])


def designation_key(beneficiary: str, window_seconds: int) -> bytes:
    """keccak256(abi.encode(beneficiary, window)): the factory's approval key."""
    return keccak(abi_encode(['address', 'uint64'], [beneficiary, int(window_seconds)]))


def gas_for_call(call_: dict) -> int | None:
    """Budget for one inner call of an owner batch; None when the selector is
    not an account or factory function (the generic table then applies)."""
    data_hex = (call_.get('data') or '')[2:].lower()
    sel = data_hex[:8]
    if sel == SEL_TRADE:
        try:
            _name, args = decode_call(call_['data'])
            inner = args[1][:4].hex()
        except Exception:  # noqa: BLE001 — budget for the worst case if unreadable
            return GAS_TRADE_OVERHEAD + 1_900_000
        from cusd_plus import sponsor_7702
        return GAS_TRADE_OVERHEAD + sponsor_7702.GAS_PER_SELECTOR.get(inner, 1_900_000)
    if sel in (SELECTORS['withdrawAll'], SELECTORS['withdrawAllTo']):
        try:
            _name, args = decode_call(call_['data'])
            return 80_000 + GAS_PER_WITHDRAWN_TOKEN * max(1, len(args[0]))
        except Exception:  # noqa: BLE001
            return 1_000_000
    return GAS_PER_SELECTOR.get(sel)


def classify(calls: list) -> str | None:
    """Sponsored-batch kind from the selectors alone, or None when no call is
    an account/factory function. A pure deposit (ERC-20 transfers only) cannot
    be told apart here: its kind comes from the prepared action."""
    names = {NAME_BY_SELECTOR.get((c.get('data') or '')[2:10].lower()) for c in calls} - {None}
    names &= (OWNER_FUNCTIONS | BENEFICIARY_FUNCTIONS | {'createAccount'})
    if not names:
        return None
    if names == {'cancelClaim'}:
        # A personal-wallet batch may carry a trailing cancelClaim (spec 6.4):
        # that does not make it an account batch.
        only = all((c.get('data') or '')[2:10].lower() == SEL_CANCEL_CLAIM for c in calls)
        return 'smart_claim' if only else None
    for kind in ('smart_subscribe', 'smart_trade', 'smart_rule', 'smart_rule_cancel',
                 'smart_inherited_withdraw', 'smart_withdraw', 'smart_cancel', 'smart_beneficiary',
                 'smart_beneficiary_remove', 'smart_claim'):
        if names & (BATCH_KIND_FUNCTIONS[kind] - {'cancelClaim'}):
            return kind
    return 'smart_claim'  # cancelClaim alone


# ── events ──────────────────────────────────────────────────────────────
# name -> [(type, indexed, arg)]
ACCOUNT_EVENTS = {
    'Subscribed': [('uint8', False, 'plan'), ('uint256', False, 'feeUsd'), ('uint64', False, 'paidUntil')],
    'PlanChanged': [('uint8', False, 'nextPlan')],
    'SubscriptionCancelled': [('uint64', False, 'paidUntil')],
    'CancelUndone': [],
    'FeeCollected': [('uint8', False, 'plan'), ('uint256', False, 'feeUsd'), ('uint256', False, 'cusdAmount'),
                     ('uint256', False, 'cusdPlusShares'), ('uint256', False, 'pPlus'), ('uint64', False, 'paidUntil')],
    'PaymentNoticeStarted': [('uint64', False, 'forPeriod'), ('uint64', False, 'saleAllowedAt')],
    'ForcedSale': [('address', True, 'tokenIn'), ('uint256', False, 'amountIn'),
                   ('uint256', False, 'dollarsOut'), ('uint64', False, 'forPeriod')],
    'Withdrawn': [('address', True, 'token'), ('address', True, 'to'), ('uint256', False, 'amount')],
    'AssetReturned': [('address', True, 'token'), ('uint256', False, 'amount')],
    'Traded': [('address', True, 'venue'), ('address', True, 'tokenIn'), ('address', True, 'tokenOut'),
               ('uint256', False, 'amountIn'), ('uint256', False, 'amountOut')],
    'UsdtConverted': [('uint8', False, 'dollar'), ('uint256', False, 'usdtIn'), ('uint256', False, 'dollarsOut')],
    'RuleCreated': [('uint256', True, 'id'), ('uint8', False, 'kind')],
    'RuleUpdated': [('uint256', True, 'id')],
    'RuleCancelled': [('uint256', True, 'id')],
    'RuleExecuted': [('uint256', True, 'id'), ('address', False, 'tokenIn'), ('address', False, 'tokenOut'),
                     ('uint256', False, 'amountIn'), ('uint256', False, 'amountOut')],
    'PayoutSent': [('uint256', True, 'id'), ('bytes32', True, 'payoutRef'), ('address', False, 'destination'),
                   ('address', False, 'tokenIn'), ('uint256', False, 'amountIn'), ('uint256', False, 'usdtOut')],
    'BeneficiaryNamed': [('address', True, 'pendingBeneficiary'), ('uint64', False, 'challengeWindow'),
                         ('uint64', False, 'expiresAt')],
    'BeneficiaryAccepted': [('address', True, 'beneficiary'), ('uint64', False, 'challengeWindow')],
    'DesignationWithdrawn': [('address', True, 'pendingBeneficiary')],
    'BeneficiaryRemoved': [('address', True, 'beneficiary')],
    'ClaimInitiated': [('address', True, 'beneficiary'), ('uint64', False, 'executableAt')],
    'ClaimCancelled': [('address', True, 'beneficiary'), ('uint64', False, 'cooldownUntil')],
    'ClaimExecuted': [('address', True, 'previousOwner'), ('address', True, 'newOwner')],
    'ConfioSaleLatched': [('address', False, 'venue'), ('address', False, 'priceRef')],
    # Decision 35: usdSpent is the gross counted against the rule's cap.
    'CardPulled': [('uint256', True, 'id'), ('address', True, 'spender'), ('uint256', False, 'usdtOut'),
                   ('uint256', False, 'usdSpent')],
}
FACTORY_EVENTS = {
    'AccountCreated': [('address', True, 'owner'), ('address', True, 'account')],
    'FeeScheduled': [('uint8', False, 'plan'), ('uint256', False, 'newFeeUsd'), ('uint64', False, 'effectiveAt')],
    'ChallengeWindowSet': [('uint64', False, 'window'), ('bool', False, 'allowed')],
    'ClaimCooldownSet': [('uint64', False, 'cooldown')],
    'ForcedSaleNoticeSet': [('uint64', False, 'notice')],
    'InheritanceEnabled': [],
    'RelayerPausedSet': [('bool', False, 'paused')],
    'ConfioSaleSet': [('address', False, 'venue'), ('address', False, 'priceRef')],
    'DesignationApproved': [('address', True, 'account'), ('address', True, 'beneficiary'),
                            ('uint64', False, 'window'), ('uint64', False, 'expiresAt')],
    'AcceptanceApproved': [('address', True, 'account'), ('address', True, 'beneficiary'),
                           ('uint64', False, 'expiresAt')],
    'CardSpenderSet': [('address', True, 'spender'), ('bool', False, 'allowed')],
    'CardPausedSet': [('bool', False, 'paused')],
}


def event_signature(name: str, fields: list) -> str:
    return f"{name}({','.join(t for t, _i, _n in fields)})"


def event_topic(name: str, fields: list) -> str:
    return '0x' + keccak(text=event_signature(name, fields)).hex()


ACCOUNT_TOPICS = {event_topic(n, f): n for n, f in ACCOUNT_EVENTS.items()}
FACTORY_TOPICS = {event_topic(n, f): n for n, f in FACTORY_EVENTS.items()}


def _jsonable(type_: str, value):
    if type_ == 'address':
        return str(value).lower()
    if type_.startswith('bytes'):
        return '0x' + bytes(value).hex()
    if type_ == 'bool':
        return bool(value)
    return str(int(value))  # uint256 does not fit a JSON number


def decode_log(log: dict, *, factory: bool = False):
    """(event name, {arg: json-safe value}) or None for a foreign log.
    Integers are decimal strings; addresses lowercase."""
    topics = [(t or '').lower() for t in (log.get('topics') or [])]
    if not topics:
        return None
    table, events = (FACTORY_TOPICS, FACTORY_EVENTS) if factory else (ACCOUNT_TOPICS, ACCOUNT_EVENTS)
    name = table.get(topics[0])
    if name is None:
        # A v2 event (V2_ACCOUNT_EVENTS / V2_FACTORY_EVENTS, kept apart from the v1 tables).
        events = V2_FACTORY_EVENTS if factory else V2_ACCOUNT_EVENTS
        name = {event_topic(n, f): n for n, f in events.items()}.get(topics[0])
    if name is None:
        return None
    fields = events[name]
    indexed = [(t, n) for t, i, n in fields if i]
    plain = [(t, n) for t, i, n in fields if not i]
    if len(topics) != 1 + len(indexed):
        raise ValueError(f'{name}: topic count mismatch')
    args = {}
    for (type_, arg), topic in zip(indexed, topics[1:]):
        args[arg] = _jsonable(type_, abi_decode([type_], bytes.fromhex(topic[2:]))[0])
    data = bytes.fromhex((log.get('data') or '0x')[2:])
    values = abi_decode([t for t, _n in plain], data) if plain else ()
    for (type_, arg), value in zip(plain, values):
        args[arg] = _jsonable(type_, value)
    return name, args


# ── the purchase spender (decisions 38 to 42) ───────────────────────────
# Not an account function and not in RELAY_KIND_CALLS: its target is the
# spender (purchases.spender_address), never the account, and relayer.
# relay_target checks that the call names the account it is sent for.
PURCHASE_KIND = 'smart_purchase_pull'
PURCHASE_PULL_SIG = 'pullTo(address,uint256,uint256,address,bytes32)'
PURCHASE_PULL_TYPES = ['address', 'uint256', 'uint256', 'address', 'bytes32']
SEL_PURCHASE_PULL = selector(PURCHASE_PULL_SIG)
FORWARDED_FIELDS = [('address', True, 'account'), ('uint256', True, 'ruleId'), ('address', True, 'to'),
                    ('uint256', False, 'usdtOut'), ('bytes32', False, 'ref')]
FORWARDED_TOPIC = event_topic('Forwarded', FORWARDED_FIELDS)


def purchase_pull_call(account: str, rule_id: int, usdt_out: int, to: str, ref: bytes) -> str:
    """0x-prefixed lowercase calldata of spender.pullTo."""
    return '0x' + SEL_PURCHASE_PULL + abi_encode(
        PURCHASE_PULL_TYPES, [account, int(rule_id), int(usdt_out), to, bytes(ref)]).hex()


def decode_purchase_pull(data: str) -> tuple:
    """(account, ruleId, usdtOut, to, ref) of a pullTo call. Raises
    ValueError for anything else or for non-canonical bytes."""
    data_hex = (data or '')[2:].lower()
    if data_hex[:8] != SEL_PURCHASE_PULL:
        raise ValueError('not_pull_to')
    raw = bytes.fromhex(data_hex[8:])
    try:
        args = abi_decode(PURCHASE_PULL_TYPES, raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError('bad_calldata') from exc
    if abi_encode(PURCHASE_PULL_TYPES, list(args)) != raw:
        raise ValueError('bad_calldata')
    return (str(args[0]).lower(), int(args[1]), int(args[2]), str(args[3]).lower(), bytes(args[4]))


def decode_forwarded(log: dict) -> dict | None:
    """{'account', 'ruleId', 'to', 'usdtOut', 'ref'} of the spender's Forwarded
    event (json-safe, as decode_log), or None for any other log."""
    topics = [(t or '').lower() for t in (log.get('topics') or [])]
    if not topics or topics[0] != FORWARDED_TOPIC:
        return None
    if len(topics) != 4:
        raise ValueError('Forwarded: topic count mismatch')
    args = {}
    for (type_, _indexed, arg), topic in zip(FORWARDED_FIELDS[:3], topics[1:]):
        args[arg] = _jsonable(type_, abi_decode([type_], bytes.fromhex(topic[2:]))[0])
    values = abi_decode(['uint256', 'bytes32'], bytes.fromhex((log.get('data') or '0x')[2:]))
    args['usdtOut'], args['ref'] = _jsonable('uint256', values[0]), _jsonable('bytes32', values[1])
    return args


# ── v2 account (IConfioSmartAccountV2.sol, IConfioSmartAccountFactoryV2.sol) ──
# Hands-off trades by the Cuenta inteligente. Kept apart from FUNCTIONS and
# ACCOUNT_EVENTS (checked against the v1 interface in test_abi): every v2
# constant the server relies on lives here, so a contract change is one edit.
V2_VERSION = 2
RELAY_TRADE_KIND = 'smart_relay_trade'
RELAY_TRADE_SIG = 'relayTrade(uint256,address,bytes,uint256,uint256)'
RELAY_TRADE_TYPES = ['uint256', 'address', 'bytes', 'uint256', 'uint256']
SEL_RELAY_TRADE = selector(RELAY_TRADE_SIG)
RELAY_PURCHASE_SIG = 'relayPurchase(uint256,bytes32,address,uint256,uint16,uint256,bytes)'
SEL_RELAY_PURCHASE = selector(RELAY_PURCHASE_SIG)
# Hands-off Comprar purchases (relay_purchases.py): relayPurchase on the account itself.
RELAY_PURCHASE_KIND = 'smart_relay_purchase'
RELAY_PURCHASE_TYPES = ['uint256', 'bytes32', 'address', 'uint256', 'uint16', 'uint256', 'bytes']
# A cUSD+ rule unwraps (about 500k measured for a Payout) before the escrow's depositFrom (about 250k):
# simulated under this budget before every send.
RELAY_PURCHASE_GAS = 1_200_000
# bucketOf(id) -> (used, lastAt): `used` already decayed to now (leaky bucket:
# amountUsd * elapsed / gap leaks out); a buy fits while used + usd <= amountUsd.
BUCKET_OF = ('bucketOf(uint256)', ['uint256'], ['uint256', 'uint256'])
VERSION_VIEW = ('VERSION()', [], ['uint256'])
FACTORY_V2_VIEWS = {
    'tradePaused': ('tradePaused()', [], ['bool']),
    'implementationOf': ('implementationOf(address)', ['address'], ['address']),
}
FACTORY_MIGRATE_SIG = 'migrate()'
# The contract's own limits (ConfioSmartAccountV2): mirrored so the server
# never sends what the account would refuse.
RELAY_TRADE_MIN_GAP_SECONDS = 60
TRADE_MAX_SLIPPAGE_BPS = 150
MAX_STOCK_FEE_BPS = 90
RELAY_TRADE_GAS = {'stock': 2_400_000, 'crypto': 1_900_000}
V2_ACCOUNT_EVENTS = {
    'RelayTraded': [('uint256', True, 'id'), ('address', True, 'venue'), ('address', False, 'tokenIn'),
                    ('address', False, 'tokenOut'), ('uint256', False, 'amountIn'), ('uint256', False, 'amountOut'),
                    ('uint256', False, 'usdCounted')],
    'RelayPurchased': [('uint256', True, 'id'), ('bytes32', True, 'orderId'), ('uint256', False, 'amount'),
                       ('uint256', False, 'usdCounted')],
}
RELAY_TRADED_TOPIC = event_topic('RelayTraded', V2_ACCOUNT_EVENTS['RelayTraded'])
# relayTrade's own reverts the server acts on: beyond the bucket (buys and sells count, at the value of what
# went out), and less than that value within 1.5% + the conversion fee of the feed / quote.
V2_ERROR_SELECTORS = {selector('CapExceeded()'): 'CapExceeded', selector('BelowFeed()'): 'BelowFeed'}


def v2_revert_error(text) -> str | None:
    for candidate in re.findall(r'0x([0-9a-fA-F]{8})', str(text or '')):
        name = V2_ERROR_SELECTORS.get(candidate.lower())
        if name is not None:
            return name
    return None
V2_FACTORY_EVENTS = {
    'TradePausedSet': [('bool', False, 'paused')],
    'ImplementationAdded': [('address', True, 'implementation'), ('uint256', False, 'index')],
    'AccountMigrated': [('address', True, 'owner'), ('address', True, 'from'), ('address', True, 'to'),
                        ('uint64', False, 'generation')],
}

# The owner's one-Face migration batch (services.prepare_migration, relay_policy._check_migration):
# old.cancelSubscription() while Active; factory.migrate(); old.withdrawAll(tokens) to the owner;
# token.transfer(new, amount) per balance; new.createRule(...) per carried rule; new.subscribe(...) when
# no paid period carries. Its own call limit; every other batch keeps services.MAX_CALLS.
MIGRATE_KIND = 'smart_migrate'
MIGRATION_MAX_CALLS = 16
SEL_MIGRATE = selector(FACTORY_MIGRATE_SIG)
GAS_PER_SELECTOR[SEL_MIGRATE] = 600_000


def relay_trade_call(rule_id: int, venue: str, venue_data: bytes, max_in: int, min_out: int) -> str:
    return '0x' + SEL_RELAY_TRADE + abi_encode(
        RELAY_TRADE_TYPES, [int(rule_id), venue, bytes(venue_data), int(max_in), int(min_out)]).hex()


def decode_relay_trade(data: str) -> tuple:
    """(id, venue, data bytes, maxIn, minOut); ValueError for anything else."""
    data_hex = (data or '')[2:].lower()
    if data_hex[:8] != SEL_RELAY_TRADE:
        raise ValueError('not relayTrade')
    raw = bytes.fromhex(data_hex[8:])
    try:
        args = abi_decode(RELAY_TRADE_TYPES, raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError('bad_calldata') from exc
    if abi_encode(RELAY_TRADE_TYPES, list(args)) != raw:
        raise ValueError('bad_calldata')
    return int(args[0]), str(args[1]).lower(), bytes(args[2]), int(args[3]), int(args[4])


def decode_relay_traded(log: dict) -> dict | None:
    """RelayTraded's arguments (json-safe), or None for another log."""
    topics = [(t or '').lower() for t in (log.get('topics') or [])]
    if not topics or topics[0] != RELAY_TRADED_TOPIC or len(topics) != 3:
        return None
    token_in, token_out, amount_in, amount_out, usd_counted = abi_decode(
        ['address', 'address', 'uint256', 'uint256', 'uint256'], bytes.fromhex((log.get('data') or '0x')[2:]))
    return {'id': str(int(topics[1], 16)), 'venue': '0x' + topics[2][-40:], 'tokenIn': token_in.lower(),
            'tokenOut': token_out.lower(), 'amountIn': str(amount_in), 'amountOut': str(amount_out),
            'usdCounted': str(usd_counted)}


def relay_purchase_call(rule_id: int, order_id32: str, merchant: str, amount: int, fee_bps: int, deadline: int,
                        auth_sig: bytes) -> str:
    return '0x' + SEL_RELAY_PURCHASE + abi_encode(RELAY_PURCHASE_TYPES, [
        int(rule_id), bytes.fromhex(order_id32.removeprefix('0x')), merchant, int(amount), int(fee_bps),
        int(deadline), bytes(auth_sig)]).hex()


def decode_relay_purchase(data: str) -> tuple:
    """(id, orderId hex without 0x, merchant, amount, feeBps, deadline, authSig bytes); ValueError otherwise."""
    data_hex = (data or '')[2:].lower()
    if data_hex[:8] != SEL_RELAY_PURCHASE:
        raise ValueError('not relayPurchase')
    raw = bytes.fromhex(data_hex[8:])
    try:
        args = abi_decode(RELAY_PURCHASE_TYPES, raw)
    except Exception as exc:  # noqa: BLE001
        raise ValueError('bad_calldata') from exc
    if abi_encode(RELAY_PURCHASE_TYPES, list(args)) != raw:
        raise ValueError('bad_calldata')
    return (int(args[0]), bytes(args[1]).hex(), str(args[2]).lower(), int(args[3]), int(args[4]), int(args[5]),
            bytes(args[6]))


RELAY_PURCHASED_TOPIC = event_topic('RelayPurchased', V2_ACCOUNT_EVENTS['RelayPurchased'])


def decode_relay_purchased(log: dict) -> dict | None:
    """RelayPurchased's arguments (json-safe), or None for another log."""
    topics = [(t or '').lower() for t in (log.get('topics') or [])]
    if not topics or topics[0] != RELAY_PURCHASED_TOPIC or len(topics) != 3:
        return None
    amount, usd_counted = abi_decode(['uint256', 'uint256'], bytes.fromhex((log.get('data') or '0x')[2:]))
    return {'id': str(int(topics[1], 16)), 'orderId': topics[2][2:], 'amount': str(amount),
            'usdCounted': str(usd_counted)}
