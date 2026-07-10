"""
Leg-AB prepare: compose and sponsor-sign the Ahorrar atomic group
(ORCHESTRATION.md §6). The client builds the 5-txn Allbridge tail
(resources simulate-populated); this module builds the sponsored burn
prefix, VERIFIES the tail against the mandatory checklist, assigns one
group id over all 8, and signs ONLY the sponsor's transactions (KMS).

THE SPONSOR NEVER SIGNS A GROUP IT HASN'T FULLY PARSED. Every rule here
is mandatory; failures return errors, never partial packs.
"""
import base64
import logging
from decimal import Decimal

import requests
from algosdk import encoding as algo_encoding, transaction
from algosdk.abi import Method, Argument, Returns
from algosdk.logic import get_application_address
from algosdk.v2client import models
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import allbridge_math

logger = logging.getLogger(__name__)

TOKEN_INFO_URL = 'https://core.api.allbridgecoreapi.net/token-info'
SWAP_AND_BRIDGE_SELECTOR_METHOD = Method(
    name='swapAndBridge',
    args=[Argument(arg_type='pay'), Argument(arg_type='axfer'),
          Argument(arg_type='byte[32]'), Argument(arg_type='byte'),
          Argument(arg_type='byte[32]'), Argument(arg_type='byte[32]'),
          Argument(arg_type='uint64')],
    returns=Returns('void'),
)


def _token_info():
    """One token-info fetch shared by wiring AND the rule-8 re-quote.
    30s TTL: wiring is static, but pool balances must be fresh enough
    to price the route at signing time."""
    data = cache.get('cusd_plus_token_info')
    if data is None:
        data = requests.get(TOKEN_INFO_URL, timeout=15).json()
        cache.set('cusd_plus_token_info', data, 30)
    return data


def _bridge_wiring(data=None):
    """Server-side Allbridge wiring — NEVER trust client-supplied ids."""
    data = data or _token_info()
    alg, bsc = data['ALG'], data['BSC']
    usdc = next(t for t in alg['tokens'] if t['symbol'] == 'USDC')
    usdt = next(t for t in bsc['tokens'] if t['symbol'] == 'USDT')
    return {
        'bridge_app_id': int(alg['bridgeId']),
        'bridge_address': alg['bridgeAddress'],
        'padding_app_id': int(alg['paddingUtilId']),
        'dest_chain_id': int(bsc['chainId']),
        'usdc_asset_id': int(usdc['tokenAddress']),
        'usdt_bsc': usdt['tokenAddress'].lower(),
    }


MAX_REFS_PER_TXN = 8
MAX_ACCOUNTS_PER_TXN = 4


def _collect_units(res: dict) -> list[dict]:
    """Flatten a simulate 'unnamed-resources-accessed' block into units.
    AVM rule: a holding (account×asset) or local (account×app) is only
    group-available when BOTH parts sit on the SAME txn — kept as atomic
    pairs, never decomposed (that split is the 'unavailable Holding' error).
    Port of collectUnits in allbridgeAlgorand.ts."""
    if not res:
        return []
    units = []
    for a in res.get('apps', []):
        units.append({'kind': 'app', 'app': int(a)})
    for a in res.get('accounts', []):
        units.append({'kind': 'account', 'account': str(a)})
    for a in res.get('assets', []):
        units.append({'kind': 'asset', 'asset': int(a)})
    for b in res.get('boxes', []):
        units.append({'kind': 'box', 'app': int(b['app']),
                      'boxName': base64.b64decode(b['name'])})
    for al in res.get('app-locals', []):
        units.append({'kind': 'local', 'account': str(al['account']), 'app': int(al['app'])})
    for ah in res.get('asset-holdings', []):
        units.append({'kind': 'holding', 'account': str(ah['account']), 'asset': int(ah['asset'])})
    return units


def _used(s):
    return len(s['apps']) + len(s['accounts']) + len(s['assets']) + len(s['boxes'])


def _cost_in(s, u):
    has_app = u.get('app') is None or u['app'] in s['apps'] or s['own_app'] == u['app']
    has_acc = u.get('account') is None or u['account'] in s['accounts']
    has_asset = u.get('asset') is None or u['asset'] in s['assets']
    k = u['kind']
    if k == 'app':
        return 0 if has_app else 1
    if k == 'account':
        return 0 if has_acc else 1
    if k == 'asset':
        return 0 if has_asset else 1
    if k == 'box':
        return (0 if has_app else 1) + 1
    if k == 'holding':
        return (0 if has_acc else 1) + (0 if has_asset else 1)
    if k == 'local':
        return (0 if has_acc else 1) + (0 if has_app else 1)
    raise ValueError(u['kind'])


def _add_to(s, u):
    if u.get('app') is not None and u['app'] != s['own_app'] and u['app'] not in s['apps']:
        if u['kind'] not in ('account', 'asset', 'holding'):
            s['apps'].append(u['app'])
    if u.get('account') is not None and u['account'] not in s['accounts']:
        s['accounts'].append(u['account'])
    if u.get('asset') is not None and u['asset'] not in s['assets']:
        s['assets'].append(u['asset'])
    if u['kind'] == 'box':
        s['boxes'].append((u['app'], u['boxName']))


def _fits(s, u):
    if _used(s) + _cost_in(s, u) > MAX_REFS_PER_TXN:
        return False
    adds_acc = u.get('account') is not None and u['account'] not in s['accounts']
    if adds_acc and len(s['accounts']) >= MAX_ACCOUNTS_PER_TXN:
        return False
    return True


def _distribute_units(slots: list, per_txn: list, floating: list) -> None:
    """Place discovered resource units across app-call slots (mutates slots).
    Per-txn units pin to their own index; floating units go to the emptiest
    fitting slot. Boxes/holdings/locals cost their missing pair parts, kept
    on one slot (AVM pairing). Port of the placement half of
    populateDepositResources — testable without algod."""
    def place(u, hard_idx=None):
        if hard_idx is not None:
            s = next((x for x in slots if x['idx'] == hard_idx), None)
            if s is None or not _fits(s, u):
                raise RuntimeError('per-txn resource does not fit its transaction')
            _add_to(s, u)
            return
        for s in sorted(slots, key=_used):
            if _fits(s, u):
                _add_to(s, u)
                return
        raise RuntimeError('resource references exceed group capacity')

    for i, units in enumerate(per_txn):
        for u in units:
            if u and i >= 3:  # prefix app-calls (burn) must need nothing extra
                place(u, i)
            elif u:
                raise RuntimeError(f'unexpected per-txn resource on prefix txn {i}')
    for u in floating:
        place(u)


def _populate_deposit_resources(algod_client, group: list) -> list:
    """Simulate the FULL group (allow-unnamed-resources, empty sigs) and
    rebuild ONLY the tail's bridge app-calls carrying every discovered
    reference (boxes paired with their app in the same txn). The padding
    calls exist precisely to hold the overflow. The burn call (sponsor-
    signed) is never a slot. Server-side port of populateDepositResources —
    a tail-only simulate can't work (no USDC until the burn's inner transfer
    runs), so this runs on prefix+tail, before gid/signing.
    """
    signed = [transaction.SignedTransaction(t, '') for t in group]
    req = models.SimulateRequest(
        txn_groups=[models.SimulateRequestTransactionGroup(txns=signed)],
        allow_empty_signatures=True,
        allow_unnamed_resources=True,
    )
    resp = algod_client.simulate_transactions(req)
    tg = resp['txn-groups'][0]
    if tg.get('failure-message'):
        raise RuntimeError(f"deposit simulate failed: {tg['failure-message']}")

    floating = _collect_units(tg.get('unnamed-resources-accessed'))
    per_txn = [_collect_units((tr or {}).get('unnamed-resources-accessed'))
               for tr in tg.get('txn-results', [])]

    # Slots = TAIL app-calls only (never the burn at index 2). Prefix is 3.
    slots = []
    for idx, t in enumerate(group):
        if idx >= 3 and t.type == 'appl':
            ac = t
            slots.append({
                'idx': idx,
                'own_app': int(ac.index or 0),
                'apps': [int(x) for x in (ac.foreign_apps or [])],
                'accounts': [str(x) for x in (ac.accounts or [])],
                'assets': [int(x) for x in (ac.foreign_assets or [])],
                'boxes': [(int(b[0]), b[1]) for b in (ac.boxes or [])],
            })

    _distribute_units(slots, per_txn, floating)

    # Rebuild the tail app-calls with their final resource arrays.
    rebuilt = list(group)
    for s in slots:
        t = group[s['idx']]
        rebuilt[s['idx']] = transaction.ApplicationCallTxn(
            sender=t.sender,
            sp=transaction.SuggestedParams(
                fee=t.fee, first=t.first_valid_round, last=t.last_valid_round,
                gh=t.genesis_hash, gen=t.genesis_id, flat_fee=True, min_fee=1000,
            ),
            index=t.index, on_complete=transaction.OnComplete.NoOpOC,
            app_args=list(t.app_args or []),
            note=(t.note if t.note else None),
            foreign_apps=s['apps'] or None,
            foreign_assets=s['assets'] or None,
            accounts=s['accounts'] or None,
            boxes=[(app, name) for (app, name) in s['boxes']] or None,
        )
    return rebuilt


def _no_rekey_close(txn) -> bool:
    return not getattr(txn, 'rekey_to', None) and \
        not getattr(txn, 'close_remainder_to', None) and \
        not getattr(txn, 'close_assets_to', None)


def verify_tail(tail, user_address: str, bsc_address: str, cusd_micro: int, wiring) -> str | None:
    """Checklist rules 1-5 for the client-built tail. Returns error or None."""
    if len(tail) != 5:
        return 'tail_must_have_5_txns'
    fee_pay, usdc_axfer, bridge_call, pad1, pad2 = tail

    for t in tail:  # rule 2
        if t.sender != user_address:
            return 'tail_sender_mismatch'
        if not _no_rekey_close(t):
            return 'tail_rekey_or_close_set'

    # rule 1 shapes + rule 3 wiring
    if not isinstance(fee_pay, transaction.PaymentTxn) or fee_pay.receiver != wiring['bridge_address']:
        return 'bad_bridge_fee_payment'
    max_fee = int(getattr(settings, 'CUSD_PLUS_MAX_BRIDGE_FEE_MICROALGO', 8_000_000))
    if fee_pay.amt > max_fee:  # rule 5
        return 'bridge_fee_above_cap'
    if not isinstance(usdc_axfer, transaction.AssetTransferTxn) or \
            usdc_axfer.index != wiring['usdc_asset_id'] or \
            usdc_axfer.receiver != wiring['bridge_address']:
        return 'bad_usdc_transfer'
    if usdc_axfer.amount != cusd_micro:  # rule 5: bridge exactly the burn output
        return 'usdc_amount_mismatch'
    if not isinstance(bridge_call, transaction.ApplicationCallTxn) or \
            bridge_call.index != wiring['bridge_app_id']:
        return 'bad_bridge_app_call'
    for pad in (pad1, pad2):
        if not isinstance(pad, transaction.ApplicationCallTxn) or pad.index != wiring['padding_app_id']:
            return 'bad_padding_call'

    # rule 4: swapAndBridge args — selector, recipient, chain, receive token
    args = bridge_call.app_args
    if len(args) != 6 or args[0] != SWAP_AND_BRIDGE_SELECTOR_METHOD.get_selector():
        return 'bad_bridge_selector'
    recipient = args[1]
    if len(recipient) != 32 or recipient[:12] != b'\x00' * 12:
        return 'bad_recipient_shape'
    if '0x' + recipient[12:].hex() != bsc_address.lower():
        return 'recipient_not_registered_bsc_address'
    if args[2] != bytes([wiring['dest_chain_id']]):
        return 'bad_destination_chain'
    if len(args[3]) != 32 or '0x' + args[3][12:].hex() != wiring['usdt_bsc']:
        return 'bad_receive_token'
    return None


def prepare_leg_ab(*, account, amount: Decimal, tail_b64: list) -> dict:
    """Build prefix, verify tail, compose, sponsor-sign. Returns pack dict."""
    from blockchain.cusd_transaction_builder import CUSDTransactionBuilder
    from blockchain.algorand_client import get_algod_client
    from .models import CusdPlusConversion

    user_address = account.algorand_address
    bsc_address = (account.bsc_address or '').lower()
    if not user_address or not bsc_address:
        return {'success': False, 'error': 'account_addresses_missing'}

    # rule 6: rate limit + per-tx cap
    rl_key = f'cusd_plus_prepare_rl_{account.id}'
    if cache.get(rl_key, 0) >= 3:
        return {'success': False, 'error': 'rate_limited'}
    cache.set(rl_key, cache.get(rl_key, 0) + 1, 60)
    max_usd = Decimal(str(getattr(settings, 'CUSD_PLUS_MAX_CONVERT_USD', '25000')))
    if amount <= 0 or amount > max_usd:
        return {'success': False, 'error': 'amount_out_of_bounds'}

    try:
        tail = [algo_encoding.msgpack_decode(t) for t in tail_b64]
    except Exception:
        return {'success': False, 'error': 'tail_decode_failed'}

    info = _token_info()
    wiring = _bridge_wiring(info)
    cusd_micro = int(amount * 1_000_000)
    err = verify_tail(tail, user_address, bsc_address, cusd_micro, wiring)
    if err:
        logger.warning('leg-AB tail rejected for account %s: %s', account.id, err)
        return {'success': False, 'error': err}

    # rule 8: independent server re-quote right before signing. The client
    # quotes for UX; the SPONSOR prices the route itself — a stale or
    # hostile client quote can never commit the user to a bad fill.
    # Allbridge has no on-chain end-to-end minReceive (the destination leg
    # executes later), so this check is the last enforcement point.
    src = allbridge_math.Side.from_token_info(
        next(t for t in info['ALG']['tokens'] if t['symbol'] == 'USDC'))
    dst = allbridge_math.Side.from_token_info(
        next(t for t in info['BSC']['tokens'] if t['symbol'] == 'USDT'))
    bridge_receive_usd = allbridge_math.quote_receive_usd(amount, src, dst)
    fee_bps = int(getattr(settings, 'CUSD_PLUS_CONVERT_FEE_BPS', 0))
    receive_usd = bridge_receive_usd * (1 - Decimal(fee_bps) / 10_000)
    quoted_cost_bps = allbridge_math.cost_bps(amount, receive_usd)
    # Client partial fills target the threshold exactly; the grace margin
    # absorbs pool drift between the client's quote and this check without
    # weakening the guard materially.
    # 100bps ceiling (2026-07-06): the guard stops catastrophes, not
    # conversions — within 1% the user sees the quoted cost and decides.
    threshold_bps = Decimal(int(getattr(settings, 'CUSD_PLUS_SPREAD_THRESHOLD_BPS', 100))
                            + int(getattr(settings, 'CUSD_PLUS_SPREAD_GRACE_BPS', 10)))
    if quoted_cost_bps > threshold_bps:
        max_fill = allbridge_math.max_fill_under_threshold_usd(
            amount, threshold_bps - fee_bps, src, dst)
        logger.warning(
            'leg-AB spread rejected for account %s: %.1fbps > %sbps (max fill $%s)',
            account.id, quoted_cost_bps, threshold_bps, max_fill)
        return {
            'success': False,
            'error': 'spread_above_threshold',
            'cost_bps': float(round(quoted_cost_bps, 1)),
            'max_fill_usd': str(max_fill),
        }

    builder = CUSDTransactionBuilder()
    algod_client = get_algod_client()
    params = algod_client.suggested_params()
    min_fee = getattr(params, 'min_fee', 1000) or 1000
    app_address = get_application_address(builder.app_id)

    # ── Burn prefix (mirrors build_burn_transactions, group deferred) ──
    # Sponsor payment covers the bridge messenger fee (user holds no ALGO
    # float) — sponsorship, not custody: it lands at the user's address and
    # leaves in the same atomic group.
    sponsor_topup = tail[0].amt + int(getattr(settings, 'CUSD_PLUS_SPONSOR_FEE_BUDGET', 4 * min_fee))
    sp = transaction.SuggestedParams(
        fee=0, first=params.first, last=params.last, gh=params.gh,
        gen=params.gen, flat_fee=True, min_fee=min_fee,
    )
    sponsor_pay = transaction.PaymentTxn(
        sender=builder.sponsor_address, sp=_flat(sp, min_fee), receiver=user_address,
        amt=sponsor_topup,
    )
    cusd_transfer = transaction.AssetTransferTxn(
        sender=user_address, sp=_flat(sp, 0), receiver=app_address,
        amt=cusd_micro, index=builder.cusd_asset_id,
    )
    burn_method = Method(name='burn_for_collateral', args=[], returns=Returns('void'))
    burn_call = transaction.ApplicationCallTxn(
        sender=builder.sponsor_address, sp=_flat(sp, 3 * min_fee),
        index=builder.app_id, on_complete=transaction.OnComplete.NoOpOC,
        app_args=[burn_method.get_selector()],
        foreign_assets=[builder.cusd_asset_id, builder.usdc_asset_id],
    )

    group = [sponsor_pay, cusd_transfer, burn_call] + tail
    # ORCHESTRATION §6 addendum: simulate the FULL group and apply discovered
    # resources to the tail's bridge app-calls (pair-aware; port of the TS
    # populateDepositResources). A tail-only simulate can't work — the user
    # holds no USDC until the burn's inner transfer runs. Runs before gid so
    # the sponsor signs the final bytes; the burn (index 2) is never touched.
    try:
        group = _populate_deposit_resources(algod_client, group)
    except Exception as exc:  # noqa: BLE001 — never sign an unpopulated group
        logger.warning('leg-AB resource population failed for account %s: %s', account.id, exc)
        return {'success': False, 'error': 'resource_population_failed'}
    sponsor_pay, cusd_transfer, burn_call = group[0], group[1], group[2]

    gid = transaction.calculate_group_id(group)
    for t in group:
        t.group = gid

    sponsor_signed = {
        0: builder.signer.sign_transaction_msgpack(sponsor_pay),
        2: builder.signer.sign_transaction_msgpack(burn_call),
    }

    conv = CusdPlusConversion.objects.create(
        actor_user=account.user if account.account_type == 'personal' else None,
        actor_business=account.business if account.account_type == 'business' else None,
        actor_type='user' if account.account_type == 'personal' else 'business',
        actor_display_name=account.display_name or '',
        direction='to_savings',
        amount_usd=amount,
        quoted_receive_usd=receive_usd.quantize(Decimal('0.000001')),  # rule-8 server quote
        user_algo_address=user_address,
        user_bsc_address=bsc_address,
    )

    return {
        'success': True,
        'conversion_id': str(conv.internal_id),
        'group_id': base64.b64encode(gid).decode(),
        'transactions': [
            algo_encoding.msgpack_encode(t) if i not in sponsor_signed else None
            for i, t in enumerate(group)
        ],
        'sponsor_transactions': [
            {'index': i, 'signed': s} for i, s in sponsor_signed.items()
        ],
    }


def _flat(sp, fee):
    return transaction.SuggestedParams(
        fee=fee, first=sp.first, last=sp.last, gh=sp.gh, gen=sp.gen,
        flat_fee=True, min_fee=sp.min_fee,
    )
