"""
BSC presale purchase flow — sponsored 7702 batches against ConfioPresaleVault.

Two-step, server-authoritative:

  prepare_purchase   full journey gate (presale active, geo/IP, terms +
                     not-US attestation, min/max, per-user limit, cUSD
                     balance), on-chain quote (quoteTokens/quoteCost),
                     PresalePurchase record, and the EXACT call batch
                     [cUSD.approve(vault, cap), vault.buy(q, cap)] stored
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
from django.db import IntegrityError
from django.utils import timezone

from eth_utils import keccak

logger = logging.getLogger(__name__)

ONE_CONFIO = 10 ** 18

# Funding sources this module produces (legacy Algorand buys are 'algorand_cusd')
BSC_FUNDING_SOURCES = ('cusd_redeem', 'cusd_direct', 'cusd_plus_via_cusd')

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


# Ondo's Instant Manager refuses redemptions under $1, and unwrapToCusd
# floors twice (shares→USDY→USDT) before the fee-free savings settlement,
# so an unwrap leg targets slightly more than the gap and never below the
# protocol floor.
MIN_IM_REDEEM_WEI = 10 ** 18            # $1.00 — Ondo's hard floor
REDEEM_TARGET_FLOOR_WEI = 105 * 10 ** 16  # $1.05 — what we aim for at the floor
REDEEM_BUFFER_BPS = 50                   # +0.5% over the gap


def _build_calls(vault: str, q_wei: int, cap_wei: int, funding: dict) -> list:
    """Normalize savings to cUSD if needed, then buy without leaving Confío."""
    from cusd_plus.sponsor_7702 import SEL_APPROVE, SEL_PRESALE_BUY

    calls = []
    unwrap = funding.get('unwrap')
    if unwrap:
        calls.append({
            'to': unwrap['savings_vault'],
            'value': '0',
            'data': (
                '0x' + keccak(text='unwrapToCusd(uint256,uint256,address)')[:4].hex()
                + _uint_word(unwrap['shares'])
                + _uint_word(unwrap['min_cusd_out'])
                + _addr_word(unwrap['to'])
            ),
        })
    calls.append({
        'to': funding['cusd_vault'],
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

    Use cUSD first and unwrap cUSD+ for any shortfall. Presale is inside the
    Confío dollar system, so this path never redeems to raw USDT.

    The wallet figure is the SWEEPABLE balance (fresh, minus USDT already
    committed to pending sends / off-ramp orders / in-flight sagas): spending
    reserved money here would simply move the failure to whichever flow
    reserved it.
    """
    from cusd_plus import vault as cusd_plus_vault

    from cusd_plus.cusd_vault import vault_address as cusd_address

    cusd = cusd_address()
    if not cusd:
        return {'error': 'insufficient_cusd_balance'}
    cusd_held = cusd_plus_vault.erc20_balance_raw(cusd, user_addr)
    base = {
        'cusd_vault': cusd,
        'to': user_addr,
        'spendable_wei': cusd_held,
    }
    if cusd_held >= amount_wei:
        return {'source': 'cusd_direct', 'unwrap': None, **base}

    savings_vault = (cusd_plus_vault.vault_address() or '').lower()
    if not savings_vault:
        return {'error': 'insufficient_cusd_balance'}
    shares_held = cusd_plus_vault.erc20_balance_raw(savings_vault, user_addr)
    if shares_held <= 0:
        return {'error': 'insufficient_cusd_balance'}

    shortfall = amount_wei - cusd_held
    pps = cusd_plus_vault.p_plus_wad()
    oracle_p = cusd_plus_vault.last_oracle_price_wad()
    if pps <= 0 or oracle_p <= 0:
        return {'error': 'quote_unavailable'}

    target_out = max(
        shortfall * (10_000 + REDEEM_BUFFER_BPS) // 10_000,
        REDEEM_TARGET_FLOOR_WEI,
    )
    # cUSD out equals the gross USDT redeemed inside the fee-free savings
    # settlement. Invert shares × pPlus / 1e18, round up, cap at holdings.
    shares = min(-(-target_out * 10 ** 18 // pps), shares_held)
    predicted_out = cusd_plus_vault.redeem_gross_usdt_out(shares, pps, oracle_p)
    if predicted_out < shortfall or predicted_out < MIN_IM_REDEEM_WEI:
        # Either savings genuinely can't cover the gap, or what's left is
        # dust below Ondo's $1 floor — both read the same to the user.
        return {'error': 'insufficient_cusd_balance'}

    return {
        'source': 'cusd_plus_via_cusd',
        **base,
        'unwrap': {
            'savings_vault': savings_vault,
            'shares': shares,
            # The functional floor: deliver at least the gap, or revert the
            # whole batch rather than fail confusingly at the buy.
            'min_cusd_out': shortfall,
            'to': user_addr,
        },
    }


def prepare_purchase(user, account, amount, accepted_terms: bool, not_us_attestation: bool,
                     client_ip=None, ip_country_hint=None, user_agent: str = '') -> dict:
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

    # Create the row used for the authoritative lock below. Do not reject on
    # the user's entered ceiling here: tail-inventory clamping can make the
    # actual debit materially smaller, and only that bounded debit consumes
    # the per-user allowance.
    UserPresaleLimit.objects.get_or_create(user=user, phase=phase)

    user_addr = (getattr(account, 'bsc_address', None) or '').lower()
    if not user_addr.startswith('0x') or len(user_addr) != 42:
        return {'success': False, 'error': 'no_bsc_address'}

    # cUSD is 18dp on BSC; amounts are dollars with 2dp
    amount_wei = int(amount_usd * Decimal(10) ** 18)

    # The entered amount is the maximum cUSD debit. Presale is an internal
    # Confío use, so there is no USDT-perimeter conversion fee.
    try:
        from cusd_plus.cusd_vault import require_operational
        require_operational()
        purchase_cap_wei = amount_wei
        q_wei = _eth_call(vault, SEL_QUOTE_TOKENS + _uint_word(purchase_cap_wei))
        if q_wei <= 0:
            return {'success': False, 'error': 'sold_out'}
        cost_wei = _eth_call(vault, SEL_QUOTE_COST + _uint_word(q_wei))
        # Fund at most 1% above the current exact cost for curve movement.
        # This prevents a tail-inventory quote from unwrapping the user's
        # entire entered maximum and leaving an unnecessary cUSD remainder.
        funding_net_wei = min(
            purchase_cap_wei,
            max(cost_wei, -(-cost_wei * 10_100 // 10_000)),
        )
        exec_params = execution_params(user_addr)
    except Exception as exc:  # noqa: BLE001
        logger.warning('[PRESALE][BSC] quote rpc failed: %s', exc)
        return {'success': False, 'error': 'quote_unavailable'}

    # Fund the bounded execution cap, not the user's potentially much larger
    # entered maximum (important when quoteTokens clamps to tail inventory).
    try:
        plan = _plan_funding(user, user_addr, funding_net_wei)
    except Exception:  # noqa: BLE001 — reservations fail closed (vault.py)
        logger.exception('[PRESALE][BSC] funding plan failed for user %s', user.id)
        return {'success': False, 'error': 'funding_plan_failed'}
    if plan.get('error'):
        return {'success': False, 'error': plan['error']}
    if plan.get('unwrap'):
        from cusd_plus.vault import redeem_blocked_reason
        blocked = redeem_blocked_reason()
        if blocked:
            logger.warning('[PRESALE][BSC] savings funding blocked: %s', blocked)
            return {'success': False, 'error': 'savings_redeem_paused'}

    confio_amount = (Decimal(q_wei) / Decimal(ONE_CONFIO)).quantize(Decimal('0.000001'))
    actual_gross_usd = Decimal(cost_wei) / Decimal(10 ** 18)
    # Phase limits apply to what will actually be debited, not merely the
    # user's larger ceiling. Refuse a sub-minimum sellout tail explicitly;
    # selling it would silently bypass the configured minimum.
    if actual_gross_usd < phase.min_purchase:
        return {'success': False, 'error': 'below_minimum'}
    if actual_gross_usd > phase.max_purchase:
        return {'success': False, 'error': 'above_maximum'}
    avg_price = (actual_gross_usd / confio_amount).quantize(Decimal('0.0001'))
    unwrap = plan.get('unwrap')
    calls = _build_calls(vault, q_wei, funding_net_wei, plan)

    # Race-safe per-user reservation (audit 2026-07-31 P2): total_purchased
    # only counts CONFIRMED purchases, so N concurrent prepares each read the
    # same committed total and every one passes the naive check — a user
    # could blow past max_per_user with parallel buys. Serialize on the UPL
    # row and count in-flight ('processing') purchases as already reserved,
    # then create THIS purchase inside the same transaction so the next
    # prepare sees it. A stale unsigned row is reaped after 24h
    # (abandon_stale_bsc_purchases), releasing its reservation.
    from django.db import transaction
    try:
        with transaction.atomic():
            # The UPL row already exists (preliminary check above); lock it so
            # concurrent prepares for this user serialize here.
            locked = UserPresaleLimit.objects.select_for_update().get(
                user=user, phase=phase)
            # One outstanding signed intent per user. Besides making recovery
            # unambiguous, this prevents two parallel prepares from both
            # reserving the same on-chain cUSD/cUSD+ balance before either is
            # mined. The row lock serializes the check and creation.
            if PresalePurchase.objects.filter(
                user=user,
                phase=phase,
                status='processing',
                funding_source__in=BSC_FUNDING_SOURCES,
            ).exists():
                return {'success': False, 'error': 'purchase_in_progress'}
            if phase.max_per_user:
                if locked.total_purchased + actual_gross_usd > phase.max_per_user:
                    return {'success': False, 'error': 'exceeds_user_limit'}
            purchase = PresalePurchase.objects.create(
                user=user,
                phase=phase,
                cusd_amount=actual_gross_usd.quantize(Decimal('0.01')),
                cusd_amount_exact=actual_gross_usd,
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
                    'cap_wei': str(funding_net_wei),
                    # Stored so submit can re-derive the optional internal
                    # unwrap instead of trusting the stored bytes alone.
                    'funding': {
                        key: ({k: str(v) for k, v in value.items()}
                              if isinstance(value, dict) else str(value))
                        for key, value in plan.items()
                        if key not in {'spendable_wei'}
                    },
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
                # A presale row is CONFIO RECEIVED, not dollars spent. The
                # CONFIO account's history queries token_type='CONFIO' only
                # (AccountDetailScreen accountTokenTypes), so a row tagged
                # CUSD silently vanishes from the one screen it belongs on —
                # which is why BSC buys stopped showing a card while the
                # Algorand ones still had theirs. blockchain/tasks.py's
                # reconciler has always written the legacy rail this way
                # (token CONFIO, amount = confio_amount); match it exactly so
                # both rails produce one indistinguishable card.
                'amount': format(purchase.confio_amount.normalize(), 'f'),
                'token_type': 'CONFIO',
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
        'max_payment': str(Decimal(funding_net_wei) / Decimal(10 ** 18)),
        'confio_fee': '0',
        'avg_price': str(avg_price),
        'funding_source': plan['source'],
        'intent_id': intent_id_hex('presale_buy', purchase.id),
        **exec_params,
    }


def _validate_presale_batch(calls: list, purchase) -> None:
    """Defense-in-depth for optional cUSD+ unwrap -> cUSD presale buy."""
    from cusd_plus.sponsor_7702 import (
        PolicyError, SEL_APPROVE, SEL_PRESALE_BUY,
    )

    vault = presale_vault_address()
    meta = json.loads(purchase.notes or '{}')
    q_wei = int(meta.get('q_wei', '0'))
    cap_wei = int(meta.get('cap_wei', '0'))
    funding = meta.get('funding') or {}
    unwrap = funding.get('unwrap') or None

    expected_len = 3 if unwrap else 2
    if len(calls) != expected_len:
        raise PolicyError('bad_batch_size')
    if any(int(c['value']) != 0 for c in calls):
        raise PolicyError('value_not_allowed')

    if unwrap:
        leg = calls[0]
        if leg['to'] != (unwrap.get('savings_vault') or '').lower():
            raise PolicyError('destination_not_allowed')
        if (unwrap.get('to') or '').lower() != (purchase.from_address or '').lower():
            raise PolicyError('redeem_recipient_not_allowed')
        expected_unwrap = (
            keccak(text='unwrapToCusd(uint256,uint256,address)')[:4].hex()
            + _uint_word(int(unwrap['shares']))
            + _uint_word(int(unwrap['min_cusd_out']))
            + _addr_word(unwrap['to'])
        )
        if leg['data'][2:].lower() != expected_unwrap:
            raise PolicyError('bad_calldata')
    approve, buy = calls[-2], calls[-1]
    if approve['to'] != (funding.get('cusd_vault') or '').lower() or buy['to'] != vault:
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

    # Operational stop controls are authoritative at broadcast time too. A
    # valid prepared signature may live for 30 minutes, during which admins
    # can deactivate the sale/phase or the dollar perimeter can pause.
    from .models import PresaleSettings
    purchase.phase.refresh_from_db(fields=['status'])
    if not PresaleSettings.get_settings().is_presale_active:
        return {'success': False, 'error': 'presale_inactive'}
    if purchase.phase.status != 'active':
        return {'success': False, 'error': 'no_active_phase'}
    try:
        from cusd_plus.cusd_vault import require_operational
        require_operational()
        if (meta.get('funding') or {}).get('unwrap'):
            from cusd_plus.vault import redeem_blocked_reason
            if redeem_blocked_reason():
                return {'success': False, 'error': 'savings_redeem_paused'}
    except Exception:
        logger.warning('[PRESALE][BSC] submit perimeter preflight failed', exc_info=True)
        return {'success': False, 'error': 'conversion_paused'}

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
        # The DURABLE claim is the SponsoredBatch row (written 'signed' before
        # broadcast) plus cpsb_unique_active_presale_buy. This existence check
        # is only the cheap path that turns the common case into a clean error
        # instead of an IntegrityError; it is NOT the boundary, and nothing
        # here may depend on it winning a race.
        #
        # Terminal-FAILED batches are deliberately not counted — reverted /
        # noop_failed / dropped are exactly the cases the user must retry, and
        # the delegate's monotonic nonce makes that safe.
        from blockchain.models import SponsoredBatch
        if SponsoredBatch.objects.filter(
            kind='presale_buy', source_id=purchase.id,
            status__in=('signed', 'sent', 'confirmed'),
        ).exists():
            return {'success': False, 'error': 'purchase_already_submitted'}

        try:
            tx_hash, batch = sponsor_7702.send_sponsored_batch(
                user, user_addr, calls, int(nonce), int(deadline),
                intent_signature, auth_dict, 'presale_buy', source_id=purchase.id)
        except IntegrityError as exc:
            # ONLY our constraint means "someone else already has this
            # purchase". Any other integrity failure — the tx-hash uniqueness,
            # an FK, a check — is a real defect, and reporting it as a
            # duplicate submit would hide it behind a plausible-looking
            # message. Read the constraint name and re-raise anything else.
            diag = getattr(getattr(exc, '__cause__', None), 'diag', None)
            if getattr(diag, 'constraint_name', None) != 'cpsb_unique_active_presale_buy':
                raise
            # Nothing was broadcast by us: another request lost the race and
            # this one already has a live batch for the purchase.
            logger.warning(
                '[PRESALE][BSC] duplicate submit blocked by constraint for purchase %s',
                purchase.id)
            return {'success': False, 'error': 'purchase_already_submitted'}
    except sponsor_7702.PolicyError as exc:
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True,
                    **_retry_params(user_addr)}
        return {'success': False, 'error': exc.code}
    except Exception as exc:  # noqa: BLE001 — surface node rejections honestly
        logger.exception('[PRESALE][BSC] sponsored buy failed for purchase %s', purchase.id)
        return {'success': False, 'error': str(exc)[:200]}

    # THE INVARIANT: a purchase is 'failed' only while it has no live batch.
    # One now exists and has been broadcast, so anything that concluded
    # otherwise in the meantime concluded wrongly. A terminal task for a
    # PREVIOUS batch can have failed this row in the window between our status
    # check above and this batch existing — it saw no replacement because ours
    # was not created yet. Under the same lock it takes, restore the truth
    # rather than leave an executing buy booked as failed.
    from django.db import transaction as _tx

    from .models import PresalePurchase as _PP
    with _tx.atomic():
        locked = _PP.objects.select_for_update().get(pk=purchase.pk)
        if locked.status == 'failed':
            logger.warning(
                '[PRESALE][BSC] purchase %s was failed by a stale terminal task '
                'while this batch was being broadcast — restoring to processing '
                '(batch %s, tx %s)', purchase.id, batch.id, tx_hash)
            locked.status = 'processing'
        locked.transaction_hash = tx_hash
        locked.save(update_fields=['status', 'transaction_hash'])
    purchase.transaction_hash = tx_hash

    from .tasks import confirm_bsc_presale_purchase
    confirm_bsc_presale_purchase.apply_async(args=[purchase.id, batch.id], countdown=8)

    # See send/bsc_flow.py: sponsor-observed execution, not settlement.
    return {'success': True, 'transaction_hash': tx_hash,
            'execution': getattr(batch, 'executed_early', None)}
