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
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

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


def _bridge_wiring():
    """Server-side Allbridge wiring — NEVER trust client-supplied ids."""
    wiring = cache.get('cusd_plus_bridge_wiring')
    if wiring:
        return wiring
    data = requests.get(TOKEN_INFO_URL, timeout=15).json()
    alg, bsc = data['ALG'], data['BSC']
    usdc = next(t for t in alg['tokens'] if t['symbol'] == 'USDC')
    usdt = next(t for t in bsc['tokens'] if t['symbol'] == 'USDT')
    wiring = {
        'bridge_app_id': int(alg['bridgeId']),
        'bridge_address': alg['bridgeAddress'],
        'padding_app_id': int(alg['paddingUtilId']),
        'dest_chain_id': int(bsc['chainId']),
        'usdc_asset_id': int(usdc['tokenAddress']),
        'usdt_bsc': usdt['tokenAddress'].lower(),
    }
    cache.set('cusd_plus_bridge_wiring', wiring, 300)
    return wiring


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

    wiring = _bridge_wiring()
    cusd_micro = int(amount * 1_000_000)
    err = verify_tail(tail, user_address, bsc_address, cusd_micro, wiring)
    if err:
        logger.warning('leg-AB tail rejected for account %s: %s', account.id, err)
        return {'success': False, 'error': err}

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
    # TODO(ORCHESTRATION §6 addendum): before gid — simulate the FULL group
    # (allow-unnamed-resources, empty sigs) and apply discovered resources to
    # the three tail app-calls (pair-aware placement, port of the TS
    # populateDepositResources). A tail-only simulate cannot work: the user
    # holds no USDC until the burn's inner transfer runs.
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
        quoted_receive_usd=amount,  # refined by client Advance; bridge floor enforces
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
