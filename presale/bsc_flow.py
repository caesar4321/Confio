"""
BSC presale purchase flow — sponsored 7702 batches against ConfioPresaleVault.

Two-step, server-authoritative:

  prepare_purchase   full journey gate (presale active, geo/IP, terms +
                     not-US attestation, min/max, per-user limit, USDT
                     balance), on-chain quote (quoteTokens/quoteCost),
                     PresalePurchase record, and the EXACT call batch
                     [USDT.approve(vault, cap), vault.buy(q, cap)] stored
                     server-side. The client only ever signs what the
                     server stored — it cannot swap calldata.
  submit_purchase    recompute the EIP-712 digest from the STORED calls,
                     verify the user's signature, re-check geo, assert the
                     presale policy on the stored batch (defense in depth),
                     then broadcast via sponsor_7702.send_sponsored_batch.
                     A Celery task resolves the receipt into
                     completed/failed on the purchase row.

Division of labor (the architecture's core): this module decides WHO buys;
the vault alone decides AT WHAT PRICE. maxPayment is pinned to the user's
stated spend, so a curve moved by concurrent buys makes the tx revert
rather than charge more than the user agreed to.
"""
import json
import logging
import time
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from eth_utils import keccak

logger = logging.getLogger(__name__)

ONE_CONFIO = 10 ** 18

# Funding sources this module produces (legacy Algorand buys are 'algorand_cusd')
BSC_FUNDING_SOURCES = ('direct_cusd', 'cusd_plus_redeem')

SEL_QUOTE_TOKENS = '0x' + keccak(text='quoteTokens(uint256)')[:4].hex()
SEL_QUOTE_COST = '0x' + keccak(text='quoteCost(uint256)')[:4].hex()
SEL_BALANCE_OF = '0x' + keccak(text='balanceOf(address)')[:4].hex()
SEL_NONCES = '0x' + keccak(text='nonces()')[:4].hex()


def execution_params(user_addr: str) -> dict:
    """Everything the client needs to SIGN, so the device reads no chain.

    The server performs these reads anyway (submit re-checks delegation and
    the authorization's account nonce), so having the phone repeat them was
    pure duplicate latency — and, before the server transport landed, a
    third-party node learning the user's address.

    Trusting the server here is safe: every one of these is an EXECUTION
    parameter whose only failure mode is a revert or a silent no-op, both of
    which the server already detects and reports.
      - delegate nonce: the delegate requires nonce == current, so a wrong
        one reverts (BadNonce). It cannot redirect funds — the calls are
        server-built and the intent binds intentId to THIS purchase.
      - delegated: wrong either way costs at most one wasted sponsor tx
        (the sponsor griefing its own BNB); noop_failed catches it.
      - account nonce: submit re-reads the LIVE nonce and rejects a stale
        authorization before broadcasting.
    """
    from cusd_plus import sponsor_7702
    from cusd_plus.tasks import _rpc

    delegated = sponsor_7702.is_delegated(user_addr)
    # nonces() on a not-yet-delegated EOA returns empty data — that IS nonce 0.
    delegate_nonce = _eth_call(user_addr, SEL_NONCES)
    # Only a first-ever (undelegated) call needs the 7702 authorization tuple.
    account_nonce = (
        0 if delegated
        else int(_rpc('eth_getTransactionCount', [user_addr, 'pending']), 16)
    )
    return {
        'delegate_nonce': str(delegate_nonce),
        'is_delegated': delegated,
        'account_nonce': str(account_nonce),
        'delegate_address': sponsor_7702.delegate_address(),
    }


def presale_vault_address() -> str:
    return (getattr(settings, 'BSC_PRESALE_VAULT_ADDRESS', '') or '').lower()


def _uint_word(v: int) -> str:
    return format(int(v), 'x').rjust(64, '0')


def _addr_word(addr: str) -> str:
    return addr.lower().replace('0x', '').rjust(64, '0')


def _eth_call(to: str, data: str) -> int:
    from cusd_plus.tasks import _rpc
    raw = _rpc('eth_call', [{'to': to, 'data': data}, 'latest'])
    return int(raw, 16) if raw and raw != '0x' else 0


# Ondo's Instant Manager refuses redemptions under $1, and redeemToUsdt
# floors TWICE (shares→USDY→USDT), so a redeem leg targets slightly more
# than the gap it has to cover and never less than the floor.
MIN_IM_REDEEM_WEI = 10 ** 18            # $1.00 — Ondo's hard floor
REDEEM_TARGET_FLOOR_WEI = 105 * 10 ** 16  # $1.05 — what we aim for at the floor
REDEEM_BUFFER_BPS = 50                   # +0.5% over the gap


def _build_calls(vault: str, usdt: str, q_wei: int, cap_wei: int, redeem: dict | None = None) -> list:
    """[ (redeemToUsdt) , approve(vault, cap), buy(q, cap) ] — one atomic batch.

    When savings fund the purchase, the redeem leg runs FIRST inside the same
    transaction, so the USDT it releases never sits in the wallet where the
    savings auto-mint (or anything else) could take it back.
    """
    from cusd_plus.sponsor_7702 import SEL_APPROVE, SEL_PRESALE_BUY, SEL_REDEEM_TO_USDT

    calls = []
    if redeem:
        calls.append({
            'to': redeem['savings_vault'],
            'value': '0',
            'data': ('0x' + SEL_REDEEM_TO_USDT + _uint_word(redeem['shares'])
                     + _uint_word(redeem['min_usdt_out']) + _addr_word(redeem['to'])),
        })
    calls.append({
        'to': usdt,
        'value': '0',
        'data': '0x' + SEL_APPROVE + _addr_word(vault) + _uint_word(cap_wei),
    })
    calls.append({
        'to': vault,
        'value': '0',
        'data': '0x' + SEL_PRESALE_BUY + _uint_word(q_wei) + _uint_word(cap_wei),
    })
    return calls


def _plan_funding(user, user_addr: str, amount_wei: int) -> dict:
    """Decide what pays for `amount_wei`.

    Spend raw Confío Dollar (USDT) first — it is idle money and every redeem
    is an IM round trip — then cover any shortfall by redeeming cUSD+ savings
    inside the same batch. Returns {'source', 'redeem'} or {'error'}.

    The wallet figure is the SWEEPABLE balance (fresh, minus USDT already
    committed to pending sends / off-ramp orders / in-flight sagas): spending
    reserved money here would simply move the failure to whichever flow
    reserved it.
    """
    from cusd_plus import vault as cusd_plus_vault

    spendable = cusd_plus_vault.sweepable_usdt_wei(user, user_addr)
    if spendable >= amount_wei:
        return {'source': 'direct_cusd', 'redeem': None, 'spendable_wei': spendable}

    savings_vault = (cusd_plus_vault.vault_address() or '').lower()
    if not savings_vault:
        return {'error': 'insufficient_cusd_balance'}
    shares_held = cusd_plus_vault.erc20_balance_raw(savings_vault, user_addr)
    if shares_held <= 0:
        return {'error': 'insufficient_cusd_balance'}

    shortfall = amount_wei - spendable
    pps = cusd_plus_vault.p_plus_wad()
    oracle_p = cusd_plus_vault.last_oracle_price_wad()
    if pps <= 0 or oracle_p <= 0:
        return {'error': 'quote_unavailable'}

    target_out = max(
        shortfall * (10_000 + REDEEM_BUFFER_BPS) // 10_000,
        REDEEM_TARGET_FLOOR_WEI,
    )
    # usdtOut ≈ shares × pPlus / 1e18 → invert, round up, cap at what's held.
    shares = min(-(-target_out * 10 ** 18 // pps), shares_held)
    predicted_out = cusd_plus_vault.redeem_usdt_out(shares, pps, oracle_p)
    if predicted_out < shortfall or predicted_out < MIN_IM_REDEEM_WEI:
        # Either savings genuinely can't cover the gap, or what's left is
        # dust below Ondo's $1 floor — both read the same to the user.
        return {'error': 'insufficient_cusd_balance'}

    return {
        'source': 'cusd_plus_redeem',
        'spendable_wei': spendable,
        'redeem': {
            'savings_vault': savings_vault,
            'shares': shares,
            # The functional floor: deliver at least the gap, or revert the
            # whole batch rather than fail confusingly at the buy.
            'min_usdt_out': shortfall,
            'to': user_addr,
        },
    }


def prepare_purchase(user, account, amount, accepted_terms: bool, not_us_attestation: bool,
                     client_ip=None, ip_country_hint=None, user_agent: str = '') -> dict:
    from cusd_plus.sponsor_7702 import USDT_BSC
    from users.legal.documents import TERMS
    from users.models_unified import UnifiedTransactionTable

    from .geo_utils import check_presale_eligibility, get_country_for_ip
    from .models import PresalePhase, PresalePurchase, PresaleSettings, UserPresaleLimit

    vault = presale_vault_address()
    if not vault:
        return {'success': False, 'error': 'presale_vault_not_configured'}

    is_eligible, error_msg = check_presale_eligibility(
        user, client_ip=client_ip, ip_country_hint=ip_country_hint)
    if not is_eligible:
        return {'success': False, 'error': error_msg}
    # The BSC flow is new — no legacy clients to tolerate: both boxes required.
    if not accepted_terms:
        return {'success': False, 'error': 'terms_acceptance_required'}
    if not not_us_attestation:
        return {'success': False, 'error': 'not_us_attestation_required'}

    settings_obj = PresaleSettings.get_settings()
    if not settings_obj.is_presale_active:
        return {'success': False, 'error': 'presale_inactive'}
    # The active phase row survives as the CONFIG anchor (min/max/per-user
    # limits) — the curve, not the phase, decides the price.
    phase = PresalePhase.objects.filter(status='active').first()
    if not phase:
        return {'success': False, 'error': 'no_active_phase'}

    try:
        amount_usd = Decimal(str(amount))
    except Exception:
        return {'success': False, 'error': 'invalid_amount'}
    if amount_usd < phase.min_purchase:
        return {'success': False, 'error': 'below_minimum'}
    if amount_usd > phase.max_purchase:
        return {'success': False, 'error': 'above_maximum'}

    # Preliminary (non-authoritative) limit check — a fast reject before the
    # quote RPC. The AUTHORITATIVE, race-safe reservation happens under a row
    # lock at purchase-creation time below (audit 2026-07-31 P2).
    upl, _ = UserPresaleLimit.objects.get_or_create(user=user, phase=phase)
    if phase.max_per_user and upl.total_purchased + amount_usd > phase.max_per_user:
        return {'success': False, 'error': 'exceeds_user_limit'}

    user_addr = (getattr(account, 'bsc_address', None) or '').lower()
    if not user_addr.startswith('0x') or len(user_addr) != 42:
        return {'success': False, 'error': 'no_bsc_address'}

    # USDT is 18dp on BSC; amounts are dollars with 2dp
    amount_wei = int(amount_usd * Decimal(10) ** 18)

    # On-chain quote: q = tokens the budget buys now; cost = exact charge
    # for q (≤ budget). The vault clamps q to remaining supply.
    try:
        q_wei = _eth_call(vault, SEL_QUOTE_TOKENS + _uint_word(amount_wei))
        if q_wei <= 0:
            return {'success': False, 'error': 'sold_out'}
        cost_wei = _eth_call(vault, SEL_QUOTE_COST + _uint_word(q_wei))
        exec_params = execution_params(user_addr)
    except Exception as exc:  # noqa: BLE001
        logger.warning('[PRESALE][BSC] quote rpc failed: %s', exc)
        return {'success': False, 'error': 'quote_unavailable'}

    # Funding: wallet Confío Dollar first, cUSD+ savings for the shortfall.
    # Execution-time cost can drift UP TO maxPayment (= the stated spend) if
    # the curve moves first, so funding must cover the CAP, not just the
    # quoted cost.
    try:
        plan = _plan_funding(user, user_addr, amount_wei)
    except Exception:  # noqa: BLE001 — reservations fail closed (vault.py)
        logger.exception('[PRESALE][BSC] funding plan failed for user %s', user.id)
        return {'success': False, 'error': 'funding_plan_failed'}
    if plan.get('error'):
        return {'success': False, 'error': plan['error']}

    confio_amount = (Decimal(q_wei) / Decimal(ONE_CONFIO)).quantize(Decimal('0.000001'))
    avg_price = (amount_usd / confio_amount).quantize(Decimal('0.0001'))
    redeem = plan.get('redeem')
    calls = _build_calls(vault, USDT_BSC, q_wei, amount_wei, redeem=redeem)

    # Race-safe per-user reservation (audit 2026-07-31 P2): total_purchased
    # only counts CONFIRMED purchases, so N concurrent prepares each read the
    # same committed total and every one passes the naive check — a user
    # could blow past max_per_user with parallel buys. Serialize on the UPL
    # row and count in-flight ('processing') purchases as already reserved,
    # then create THIS purchase inside the same transaction so the next
    # prepare sees it. A stale unsigned row is reaped after 24h
    # (abandon_stale_bsc_purchases), releasing its reservation.
    from django.db import transaction
    from django.db.models import Sum
    try:
        with transaction.atomic():
            # The UPL row already exists (preliminary check above); lock it so
            # concurrent prepares for this user serialize here.
            locked = UserPresaleLimit.objects.select_for_update().get(
                user=user, phase=phase)
            if phase.max_per_user:
                in_flight = (PresalePurchase.objects.filter(
                    user=user, phase=phase, status='processing',
                    funding_source__in=BSC_FUNDING_SOURCES,
                ).aggregate(s=Sum('cusd_amount'))['s'] or Decimal('0'))
                if locked.total_purchased + in_flight + amount_usd > phase.max_per_user:
                    return {'success': False, 'error': 'exceeds_user_limit'}
            purchase = PresalePurchase.objects.create(
                user=user,
                phase=phase,
                cusd_amount=amount_usd,
                confio_amount=confio_amount,
                price_per_token=avg_price,
                status='processing',
                from_address=user_addr,
                funding_source=plan['source'],
                accepted_terms_version=TERMS['version'],
                accepted_terms_at=timezone.now(),
                accepted_terms_ip=client_ip,
                accepted_terms_user_agent=(user_agent or '')[:1000],
                attested_not_us_resident=True,
                attested_not_us_at=timezone.now(),
                ip_country=(get_country_for_ip(client_ip, ip_country_hint) or ''),
                notes=json.dumps({
                    'bsc_calls': calls,
                    'quote_cost_wei': str(cost_wei),
                    'q_wei': str(q_wei),
                    # Stored so submit can re-derive the redeem leg's exact
                    # calldata instead of trusting the stored bytes alone.
                    'redeem': ({k: str(v) for k, v in redeem.items()} if redeem else None),
                }),
            )
    except Exception:  # noqa: BLE001
        logger.exception('[PRESALE][BSC] reservation/create failed for user %s', user.id)
        return {'success': False, 'error': 'reservation_failed'}

    try:
        user_display = (
            purchase.user.get_full_name() or purchase.user.username
            or purchase.user.email or 'Tú'
        )
        UnifiedTransactionTable.objects.update_or_create(
            presale_purchase=purchase,
            defaults={
                'transaction_type': 'presale',
                'amount': str(purchase.cusd_amount),
                'token_type': 'CUSD',
                'status': 'PENDING_SIG',
                'transaction_hash': '',
                'error_message': '',
                'sender_user': None,
                'sender_business': None,
                'sender_type': 'external',
                'sender_display_name': 'Confío Preventa',
                'sender_phone': '',
                'sender_address': vault,
                'counterparty_user': purchase.user,
                'counterparty_business': None,
                'counterparty_type': 'user',
                'counterparty_display_name': user_display,
                'counterparty_phone': '',
                'counterparty_address': user_addr,
                'description': 'Compra de preventa $CONFIO',
                'from_address': vault,
                'to_address': user_addr,
                'transaction_date': purchase.created_at or timezone.now(),
                'payment_reference_id': f'presale_purchase:{purchase.id}',
            },
        )
    except Exception:
        logger.exception('[PRESALE][BSC] unified row create failed for purchase %s', purchase.id)

    from cusd_plus.sponsor_7702 import intent_id_hex
    return {
        'success': True,
        'purchase_id': str(purchase.internal_id),
        'calls': calls,
        'confio_amount': str(confio_amount),
        'cost': str((Decimal(cost_wei) / Decimal(10) ** 18).quantize(Decimal('0.000001'))),
        'max_payment': str(amount_usd),
        'avg_price': str(avg_price),
        'funding_source': plan['source'],
        'intent_id': intent_id_hex('presale_buy', purchase.id),
        **exec_params,
    }


def _validate_presale_batch(calls: list, purchase) -> None:
    """Defense-in-depth on the stored batch: [approve(vault, cap), buy(q, cap)]
    optionally preceded by redeemToUsdt(shares, minOut, buyer) — every field
    re-derived from the purchase row, never trusted from the stored bytes."""
    from cusd_plus.sponsor_7702 import (
        PolicyError, SEL_APPROVE, SEL_PRESALE_BUY, SEL_REDEEM_TO_USDT, USDT_BSC,
    )

    vault = presale_vault_address()
    meta = json.loads(purchase.notes or '{}')
    q_wei = int(meta.get('q_wei', '0'))
    cap_wei = int(purchase.cusd_amount * Decimal(10) ** 18)
    redeem = meta.get('redeem') or None

    expected_len = 3 if redeem else 2
    if len(calls) != expected_len:
        raise PolicyError('bad_batch_size')
    if any(int(c['value']) != 0 for c in calls):
        raise PolicyError('value_not_allowed')

    if redeem:
        leg = calls[0]
        # The recipient MUST be the buyer: a redeem paying anyone else would
        # drain savings out of the purchase entirely.
        if leg['to'] != (redeem.get('savings_vault') or '').lower():
            raise PolicyError('destination_not_allowed')
        if (redeem.get('to') or '').lower() != (purchase.from_address or '').lower():
            raise PolicyError('redeem_recipient_not_allowed')
        expected_redeem = (
            SEL_REDEEM_TO_USDT
            + _uint_word(int(redeem['shares']))
            + _uint_word(int(redeem['min_usdt_out']))
            + _addr_word(redeem['to'])
        )
        if leg['data'][2:].lower() != expected_redeem:
            raise PolicyError('bad_calldata')

    approve, buy = calls[-2], calls[-1]
    if approve['to'] != USDT_BSC or buy['to'] != vault:
        raise PolicyError('destination_not_allowed')
    if approve['data'][2:].lower() != (SEL_APPROVE + _addr_word(vault) + _uint_word(cap_wei)):
        raise PolicyError('bad_calldata')
    if buy['data'][2:].lower() != (SEL_PRESALE_BUY + _uint_word(q_wei) + _uint_word(cap_wei)):
        raise PolicyError('bad_calldata')


def _retry_params(user_addr: str) -> dict:
    """Fresh signing params attached to the two RETRYABLE submit failures, so
    the client can re-sign without going to the chain itself. Best effort: if
    the read fails the client falls back to reading them (through our own
    RPC transport), which is the old behavior."""
    try:
        return execution_params(user_addr)
    except Exception:  # noqa: BLE001
        logger.warning('[PRESALE][BSC] retry params unavailable for %s', user_addr)
        return {}


def submit_purchase(user, purchase, nonce: int, deadline: int, intent_signature: str,
                    authorization=None, client_ip=None, ip_country_hint=None) -> dict:
    from cusd_plus import sponsor_7702

    from .geo_utils import check_presale_eligibility

    if purchase.status != 'processing' or purchase.funding_source not in BSC_FUNDING_SOURCES:
        return {'success': False, 'error': 'purchase_not_pending'}

    meta = json.loads(purchase.notes or '{}')
    calls = meta.get('bsc_calls')
    if not calls:
        return {'success': False, 'error': 'purchase_not_prepared'}

    user_addr = (purchase.from_address or '').lower()
    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))

    now = int(time.time())
    if not (now + 30 <= int(deadline) <= now + 1800):
        return {'success': False, 'error': 'bad_deadline'}

    # Geo can change between prepare and submit (VPN toggles, travel):
    # the broadcast is the gate that matters, so re-check here.
    is_eligible, error_msg = check_presale_eligibility(
        user, client_ip=client_ip, ip_country_hint=ip_country_hint)
    if not is_eligible:
        return {'success': False, 'error': error_msg}

    try:
        _validate_presale_batch(calls, purchase)

        intent_id = sponsor_7702.intent_id_for('presale_buy', purchase.id)
        digest = sponsor_7702.intent_digest(
            calls, int(nonce), int(deadline), user_addr, chain_id, intent_id)
        signer = sponsor_7702.recover_intent_signer(digest, intent_signature)
        if signer != user_addr:
            return {'success': False, 'error': 'bad_intent_signature'}

        auth_dict = None
        if not sponsor_7702.is_delegated(user_addr):
            if authorization is None:
                return {'success': False, 'error': 'authorization_required',
                        'authorization_required': True,
                        **_retry_params(user_addr)}
            auth_dict = sponsor_7702.normalize_and_validate_authorization(
                authorization, user_addr, chain_id)

        # REPLAY GUARD. A successful broadcast below sets only
        # transaction_hash; the row stays 'processing' until
        # confirm_bsc_presale_purchase runs 8s later (longer if the queue
        # lags, indefinitely while it retries). The guard at the top of this
        # function only tests that status, so without this the same prepared
        # batch could be re-signed with a fresh delegate nonce and executed
        # again — redeeming the user's savings and calling buy() twice while
        # the database books one purchase, which also walks past the per-user
        # presale limits.
        #
        # Two layers because they cover different races: SponsoredBatch is
        # written BEFORE broadcast (durable, survives a cache flush) and
        # cache.add is atomic (covers two requests in flight at once).
        # Terminal-FAILED batches are deliberately not counted — reverted /
        # noop_failed / dropped are exactly the cases the user must retry,
        # and the delegate's monotonic nonce makes that safe.
        from django.core.cache import cache

        from blockchain.models import SponsoredBatch
        if SponsoredBatch.objects.filter(
            kind='presale_buy', source_id=purchase.id,
            status__in=('signed', 'sent', 'confirmed'),
        ).exists():
            return {'success': False, 'error': 'purchase_already_submitted'}
        claim_key = f'presale_bsc_submit_{purchase.id}'
        if not cache.add(claim_key, 1, 600):
            return {'success': False, 'error': 'purchase_already_submitting'}

        try:
            tx_hash, batch = sponsor_7702.send_sponsored_batch(
                user, user_addr, calls, int(nonce), int(deadline),
                intent_signature, auth_dict, 'presale_buy', source_id=purchase.id)
        except Exception:
            # Nothing was broadcast (or it failed outright) — let the user
            # retry rather than stranding the purchase behind a stale claim.
            cache.delete(claim_key)
            raise
    except sponsor_7702.PolicyError as exc:
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True,
                    **_retry_params(user_addr)}
        return {'success': False, 'error': exc.code}
    except Exception as exc:  # noqa: BLE001 — surface node rejections honestly
        logger.exception('[PRESALE][BSC] sponsored buy failed for purchase %s', purchase.id)
        return {'success': False, 'error': str(exc)[:200]}

    purchase.transaction_hash = tx_hash
    purchase.save(update_fields=['transaction_hash'])

    from .tasks import confirm_bsc_presale_purchase
    confirm_bsc_presale_purchase.apply_async(args=[purchase.id, batch.id], countdown=8)

    # See send/bsc_flow.py: sponsor-observed execution, not settlement.
    return {'success': True, 'transaction_hash': tx_hash,
            'execution': getattr(batch, 'executed_early', None)}
