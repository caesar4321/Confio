from __future__ import annotations

import logging
import re
from datetime import timedelta
from decimal import Decimal, ROUND_DOWN

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from conversion.models import Conversion
from notifications.models import NotificationType as NotificationTypeChoices
from notifications.utils import create_notification
from ramps.deposit_linking import link_koywe_deposit_to_ramp
from ramps.models import RampTransaction
from usdc_transactions.models import GuardarianTransaction, USDCDeposit, USDCWithdrawal
from achievements.models import UserReferral
from users.funnel import emit_event
from users.models_unified import UnifiedTransactionTable
from users.utils import touch_user_activity
from send.models import PhoneInvite

logger = logging.getLogger(__name__)

GUARDARIAN_CONVERSION_LINK_WINDOW = timedelta(days=14)
GUARDARIAN_WAITING_FOR_AUTOSWAP = 'deposit_confirmed_waiting_for_user_autoswap'
GUARDARIAN_AUTOSWAP_FAILED_RETRYABLE = 'deposit_confirmed_autoswap_failed_retryable'
GUARDARIAN_WAITING_FOR_BLOCKCHAIN_MATCH = 'provider_finished_waiting_for_blockchain_match'
BSC_RAMP_ATTRIBUTION_WINDOW = timedelta(days=14)


def _safe_related(instance, attr_name: str):
    try:
        return getattr(instance, attr_name)
    except Exception:
        return None


def _map_guardarian_status(status: str | None) -> str:
    normalized = (status or '').lower()
    if normalized in {'failed', 'refunded', 'expired'}:
        return 'FAILED'
    if normalized == 'hold':
        return 'AML_REVIEW'
    if normalized == 'finished':
        return 'COMPLETED'
    return 'PROCESSING' if normalized in {'confirmed', 'exchanging', 'sending'} else 'PENDING'


def _get_deposit_auto_swap_conversion(deposit: USDCDeposit | None) -> Conversion | None:
    if not deposit:
        return None
    pending_auto_swap = _safe_related(deposit, 'pending_auto_swap')
    if not pending_auto_swap:
        return None
    return _safe_related(pending_auto_swap, 'conversion')


def _derive_guardarian_ramp_outcome(guardarian_tx: GuardarianTransaction) -> tuple[str, str, timezone.datetime | None]:
    provider_status = _map_guardarian_status(guardarian_tx.status)
    provider_status_raw = (guardarian_tx.status or '').lower()
    direction = 'off_ramp' if guardarian_tx.transaction_type == 'sell' else 'on_ramp'
    deposit = guardarian_tx.onchain_deposit
    withdrawal = guardarian_tx.onchain_withdrawal
    conversion = None
    if deposit:
        conversion = _safe_related(deposit, 'ramp_transaction')
        conversion = getattr(conversion, 'conversion', None) if conversion else None
        conversion = conversion or _get_deposit_auto_swap_conversion(deposit)
    elif withdrawal:
        conversion = _safe_related(withdrawal, 'ramp_transaction')
        conversion = getattr(conversion, 'conversion', None) if conversion else None

    if direction == 'on_ramp':
        if conversion and conversion.status == 'FAILED':
            return 'PROCESSING', GUARDARIAN_AUTOSWAP_FAILED_RETRYABLE, None
        if conversion and conversion.status == 'COMPLETED':
            return 'COMPLETED', 'conversion_completed', timezone.now()
        if deposit and deposit.status == 'COMPLETED':
            if provider_status == 'FAILED':
                return 'FAILED', 'provider_failed_after_deposit', None
            return 'PROCESSING', GUARDARIAN_WAITING_FOR_AUTOSWAP, None
        if provider_status == 'COMPLETED':
            return 'PROCESSING', GUARDARIAN_WAITING_FOR_BLOCKCHAIN_MATCH, None
    else:
        if withdrawal and withdrawal.status == 'COMPLETED':
            if provider_status == 'FAILED':
                detail = 'provider_refunded' if provider_status_raw == 'refunded' else 'withdrawal_confirmed_provider_failed'
                return 'FAILED', detail, None
            if provider_status == 'COMPLETED':
                return 'COMPLETED', 'payout_completed', timezone.now()
            if provider_status == 'AML_REVIEW':
                return 'AML_REVIEW', 'provider_aml_review', None
            return 'PROCESSING', 'withdrawal_confirmed_provider_pending', None
        if provider_status == 'COMPLETED':
            return 'PROCESSING', GUARDARIAN_WAITING_FOR_BLOCKCHAIN_MATCH, None

    if provider_status == 'AML_REVIEW':
        return 'AML_REVIEW', 'provider_aml_review', None
    if provider_status == 'FAILED':
        if provider_status_raw == 'refunded':
            return 'FAILED', 'provider_refunded', None
        if provider_status_raw == 'expired':
            return 'FAILED', 'provider_expired', None
        return 'FAILED', 'provider_failed_pre_blockchain', None
    if provider_status == 'COMPLETED':
        return 'COMPLETED', 'provider_completed', timezone.now()
    if provider_status == 'PROCESSING':
        return 'PROCESSING', f'provider_{provider_status_raw or "processing"}', None
    return 'PENDING', f'provider_{provider_status_raw or "pending"}', None


def _get_guardarian_actor(guardarian_tx: GuardarianTransaction) -> tuple[str, str, object | None, object | None]:
    actor_user = guardarian_tx.user
    actor_business = None
    actor_type = 'user'
    actor_display_name = ''

    if actor_user:
        actor_display_name = f'{actor_user.first_name} {actor_user.last_name}'.strip() or actor_user.username or ''

    return actor_type, actor_display_name, actor_user, actor_business


def _derive_actor_address(ramp_tx: RampTransaction) -> str:
    if ramp_tx.conversion_id and ramp_tx.conversion:
        return ramp_tx.conversion.actor_address or ''
    if ramp_tx.usdc_deposit_id and ramp_tx.usdc_deposit:
        return ramp_tx.usdc_deposit.actor_address or ''
    if ramp_tx.usdc_withdrawal_id and ramp_tx.usdc_withdrawal:
        return ramp_tx.usdc_withdrawal.actor_address or ''
    return ramp_tx.actor_address or ''


def _ledger_token(ramp_tx: RampTransaction, final_currency: str) -> str:
    """A canonical ledger token, never a provider's product name.

    final_currency is whatever the provider (or an admin editing the row)
    put there — 'CUSD+', 'USDT BSC', a KOYWE_CRYPTO_SYMBOL override, even a
    fiat symbol like 'PEN' when no crypto amount was derived. The ledger now
    enforces a canonical token, so passing that straight through turns an
    unexpected provider string into an IntegrityError on a ramp save that
    used to succeed. Fold what we can, and fall back to the token the RAIL
    settles in rather than failing the write or inventing a currency.
    """
    from users.models_unified import CANONICAL_TOKEN_TYPES, canonical_token_type

    token = canonical_token_type(final_currency)
    if token in CANONICAL_TOKEN_TYPES:
        return token
    fallback = 'CUSD_PLUS' if ramp_tx.destination == 'cusd_plus' else 'CUSD'
    logger.warning(
        'ramp %s: final_currency %r is not a ledger token — recording as %s',
        getattr(ramp_tx, 'id', '?'), final_currency, fallback,
    )
    return fallback


def _derive_final_amount(ramp_tx: RampTransaction) -> tuple[Decimal | None, str]:
    if (
        ramp_tx.provider == 'koywe'
        and ramp_tx.direction == 'off_ramp'
        and ramp_tx.final_amount is not None
    ):
        return ramp_tx.final_amount, 'USDC'

    if ramp_tx.conversion_id and ramp_tx.conversion:
        if ramp_tx.direction == 'on_ramp':
            token = (
                'CUSD_PLUS'
                if ramp_tx.conversion.conversion_type == 'to_savings'
                else 'CUSD_BSC'
                if ramp_tx.conversion.conversion_type == 'usdt_to_cusd'
                else 'CUSD'
            )
            return ramp_tx.conversion.to_amount, token
        token = (
            'CUSD_PLUS' if ramp_tx.conversion.conversion_type == 'from_savings'
            else 'CUSD_BSC' if ramp_tx.conversion.conversion_type == 'cusd_to_usdt'
            else 'CUSD'
        )
        return ramp_tx.conversion.from_amount, token

    if ramp_tx.crypto_amount_actual is not None:
        return ramp_tx.crypto_amount_actual, ramp_tx.final_currency or 'CUSD'
    if ramp_tx.crypto_amount_estimated is not None:
        return ramp_tx.crypto_amount_estimated, ramp_tx.final_currency or 'CUSD'
    return None, ramp_tx.final_currency or 'CUSD'


def _find_koywe_ramp_for_conversion(conversion: Conversion) -> RampTransaction | None:
    """Walk Conversion -> PendingAutoSwap -> USDCDeposit -> RampTransaction.

    The Koywe linking pipeline writes USDCDeposit -> RampTransaction via
    link_koywe_deposit_to_ramp and creates the PendingAutoSwap from the
    deposit. The conversion is then attached to the PendingAutoSwap by
    BuildAutoSwapTransactionsMutation. The final hop (conversion ->
    ramp) was never wired up, leaving every Koywe ramp's `conversion`
    FK NULL even after a successful swap.
    """
    try:
        pas = conversion.pending_auto_swap  # OneToOne reverse
    except Exception:
        return None
    if not pas or not pas.usdc_deposit_id:
        return None
    try:
        ramp_tx = pas.usdc_deposit.ramp_transaction  # reverse OneToOne
    except Exception:
        return None
    if not ramp_tx or ramp_tx.provider != 'koywe':
        return None
    return ramp_tx


def _find_guardarian_ramp_for_conversion(conversion: Conversion) -> RampTransaction | None:
    if conversion.status != 'COMPLETED':
        return None
    # BSC attribution must arrive through attribute_bsc_ramp_arrival(), which
    # requires provider-source proof. This fallback is legacy Algorand only;
    # admitting BSC here turns the old amount/time heuristic back into a fee
    # and history attribution bypass.
    if conversion.conversion_type != 'usdc_to_cusd':
        return None
    if not conversion.actor_user_id or not conversion.actor_address:
        return None
    if conversion.from_amount is None:
        return None

    query = RampTransaction.objects.filter(
            provider='guardarian',
            direction='on_ramp',
            actor_user_id=conversion.actor_user_id,
            actor_address=conversion.actor_address,
            conversion__isnull=True,
            status__in=['PENDING', 'PROCESSING', 'AML_REVIEW'],
            created_at__gte=timezone.now() - GUARDARIAN_CONVERSION_LINK_WINDOW,
        )
    query = query.filter(
        usdc_deposit__isnull=False,
        usdc_deposit__amount=conversion.from_amount,
    )
    return query.order_by('created_at').first()


def attribute_bsc_ramp_arrival(*, actor_address: str, amount: Decimal,
                               tx_hash: str, log_index: int,
                               sender_address: str = '') -> RampTransaction | None:
    """Persist provider-order attribution when its BSC USDT transfer lands."""
    address = (actor_address or '').lower()
    if not address or not tx_hash or amount <= 0:
        return None
    tolerance = amount * Decimal('0.05')

    def _provider_hash(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {
                    'bsc_provider_transfer_tx_hash', 'provider_transfer_tx_hash',
                    'txHash', 'tx_hash', 'transactionHash', 'transaction_hash',
                } and isinstance(item, str) and re.fullmatch(r'0x[0-9a-fA-F]{64}', item):
                    return item.lower()
            for item in value.values():
                found = _provider_hash(item)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = _provider_hash(item)
                if found:
                    return found
        return None

    def _allowed_senders(provider: str) -> set[str]:
        setting_name = (
            'KOYWE_BSC_SETTLEMENT_ADDRESSES'
            if provider == 'koywe' else 'GUARDARIAN_BSC_SETTLEMENT_ADDRESSES'
        )
        raw = getattr(settings, setting_name, ()) or ()
        if isinstance(raw, str):
            raw = raw.split(',')
        return {str(value).strip().lower() for value in raw if str(value).strip()}

    with transaction.atomic():
        # Overlapping scanners and rewind scans are normal. Lock every live
        # candidate through selection + claim so two workers cannot attach
        # different transfer logs to the same sender-only provider order.
        candidates = list(RampTransaction.objects.select_for_update().filter(
            destination='cusd_plus', direction='on_ramp',
            actor_address__iexact=address, conversion__isnull=True,
            created_at__gte=timezone.now() - BSC_RAMP_ATTRIBUTION_WINDOW,
        ).exclude(status='FAILED').order_by('created_at'))
        explicit_matches = []
        sender_matches = []
        for ramp in candidates:
            metadata = dict(ramp.metadata or {})
            if metadata.get('bsc_arrival_tx_hash'):
                continue
            provider_hash = _provider_hash(metadata)
            if provider_hash:
                # An explicit provider hash is authoritative. Never let the
                # broad hot-wallet allowlist override a mismatch and steal a
                # sibling order with the same amount.
                if provider_hash != tx_hash.lower():
                    continue
                proof = 'explicit'
            else:
                if (sender_address or '').lower() not in _allowed_senders(ramp.provider):
                    continue
                proof = 'sender'
            expected = ramp.crypto_amount_actual or ramp.crypto_amount_estimated
            if expected is None:
                continue
            delta = abs(Decimal(expected) - amount)
            if delta <= tolerance:
                (explicit_matches if proof == 'explicit' else sender_matches).append(ramp)
        # Transaction hashes should identify exactly one order. Sender-only
        # proof is accepted only when it leaves a single possible live order;
        # otherwise wait for provider data/manual reconciliation rather than
        # guess.
        matches = explicit_matches or sender_matches
        if len(matches) != 1:
            return None
        best = matches[0]
        metadata = dict(best.metadata or {})
        metadata.update({
            'bsc_arrival_tx_hash': tx_hash.lower(),
            'bsc_arrival_log_index': int(log_index),
            'bsc_arrival_amount': format(amount, 'f'),
        })
        best.metadata = metadata
        best.crypto_amount_actual = amount
        best.save(update_fields=['metadata', 'crypto_amount_actual', 'updated_at'])
        return best


def _attributed_bsc_ramps(conversion: Conversion) -> list[RampTransaction]:
    if (conversion.status != 'COMPLETED'
            or conversion.conversion_type not in ('to_savings', 'usdt_to_cusd')
            or conversion.from_amount is None):
        return []
    address = (conversion.actor_address or conversion.user_bsc_address or '').lower()
    if not address:
        return []
    remaining = Decimal(conversion.from_amount)
    linked: list[RampTransaction] = []
    candidates = RampTransaction.objects.filter(
        destination='cusd_plus', direction='on_ramp',
        actor_address__iexact=address, conversion__isnull=True,
        created_at__gte=conversion.created_at - BSC_RAMP_ATTRIBUTION_WINDOW,
        created_at__lte=conversion.created_at + BSC_RAMP_ATTRIBUTION_WINDOW,
    ).exclude(status='FAILED').order_by('created_at')
    for ramp in candidates:
        arrival = (ramp.metadata or {}).get('bsc_arrival_amount')
        if arrival in (None, ''):
            continue
        try:
            amount = Decimal(str(arrival))
        except Exception:
            continue
        if amount <= 0 or amount > remaining:
            continue
        linked.append(ramp)
        remaining -= amount
    return linked


def _bsc_ramp_net_allocations(conversion: Conversion,
                              ramps: list[RampTransaction]) -> list[Decimal]:
    """Allocate an aggregate conversion net without crediting it twice."""
    gross = Decimal(conversion.gross_amount_exact or conversion.from_amount)
    net = Decimal(conversion.net_amount_exact or conversion.to_amount)
    if gross <= 0:
        return [Decimal('0') for _ in ramps]
    grain = Decimal('0.000001')
    ramp_gross = [
        Decimal(str((ramp.metadata or {})['bsc_arrival_amount']))
        for ramp in ramps
    ]
    allocations = [
        (amount * net / gross).quantize(grain, rounding=ROUND_DOWN)
        for amount in ramp_gross
    ]
    # When attributed ramps cover the complete sweep, give the last ramp the
    # six-decimal remainder so the displayed allocations sum exactly to the
    # conversion's displayed net. A mixed direct deposit keeps its own share.
    if ramps and abs(sum(ramp_gross, Decimal('0')) - gross) < grain:
        allocations[-1] += (
            Decimal(conversion.to_amount).quantize(grain, rounding=ROUND_DOWN)
            - sum(allocations, Decimal('0'))
        )
    return allocations


def _classify_first_deposit_source(user_id: int | None) -> str:
    if not user_id:
        return 'organic'

    if PhoneInvite.objects.filter(
        claimed_by_id=user_id,
        status='claimed',
    ).exists():
        return 'send_invite'

    if UserReferral.objects.filter(
        referred_user_id=user_id,
    ).exclude(status='inactive').exists():
        return 'referral_link'

    return 'organic'


def _first_deposit_referral_attribution(user_id: int | None) -> tuple[dict, str]:
    """Return bounded referral click metadata for first-deposit analytics."""
    if not user_id:
        return {}, ''

    referral = (
        UserReferral.objects
        .filter(referred_user_id=user_id)
        .exclude(status='inactive')
        .order_by('-created_at')
        .first()
    )
    if not referral or not referral.attribution_data:
        return {}, ''

    attribution = referral.attribution_data or {}
    allowed_keys = {
        'click_id',
        'session_id',
        'click_channel',
        'click_platform',
        'click_country',
        'source_type',
        'invitation_id',
        'utm_source',
        'utm_medium',
        'utm_campaign',
        'utm_content',
        'utm_term',
        'ttclid',
        'fbclid',
        'gclid',
        'signup_ip_address',
        'signup_user_agent',
    }
    properties = {
        key: str(value)[:255]
        for key, value in attribution.items()
        if key in allowed_keys and value not in (None, '')
    }
    identifier = (referral.referrer_identifier or '').lstrip('@').strip().upper()
    if identifier:
        properties['referral_code'] = identifier[:255]
    session_id = str(attribution.get('session_id') or '')[:64]
    return properties, session_id


def sync_ramp_transaction_from_guardarian(guardarian_tx: GuardarianTransaction) -> RampTransaction:
    actor_type, actor_display_name, actor_user, actor_business = _get_guardarian_actor(guardarian_tx)
    direction = 'off_ramp' if guardarian_tx.transaction_type == 'sell' else 'on_ramp'
    final_amount = guardarian_tx.to_amount_actual if direction == 'on_ramp' else guardarian_tx.from_amount
    is_bsc_dollar = (
        (guardarian_tx.network or '').upper() in {'BSC', 'BEP20', 'BNB SMART CHAIN'}
        and (guardarian_tx.to_currency if direction == 'on_ramp' else guardarian_tx.from_currency).upper() == 'USDT'
    )
    final_currency = 'USDT BSC' if is_bsc_dollar else 'CUSD'
    ramp_status, status_detail, completed_at = _derive_guardarian_ramp_outcome(guardarian_tx)
    conversion = None
    if direction == 'on_ramp':
        existing_ramp = _safe_related(guardarian_tx, 'ramp_transaction')
        if existing_ramp:
            conversion = _safe_related(existing_ramp, 'conversion')
        conversion = _get_deposit_auto_swap_conversion(guardarian_tx.onchain_deposit)
        if not conversion and existing_ramp:
            conversion = _safe_related(existing_ramp, 'conversion')
        if conversion and conversion.status != 'COMPLETED':
            conversion = None
        if conversion:
            final_amount = conversion.to_amount
            final_currency = (
                'CUSD+' if conversion.conversion_type == 'to_savings'
                else 'CUSD' if conversion.conversion_type == 'usdt_to_cusd'
                else final_currency
            )

    defaults = {
        'provider': 'guardarian',
        'direction': direction,
        'status': ramp_status,
        'provider_order_id': guardarian_tx.guardarian_id,
        'external_id': guardarian_tx.external_id or '',
        'actor_user': actor_user,
        'actor_business': actor_business,
        'actor_type': actor_type,
        'actor_display_name': actor_display_name,
        'actor_address': (
            guardarian_tx.onchain_deposit.actor_address
            if guardarian_tx.onchain_deposit_id
            else guardarian_tx.onchain_withdrawal.actor_address
            if guardarian_tx.onchain_withdrawal_id
            else (getattr(guardarian_tx.account, 'bsc_address', '') or '')
            if is_bsc_dollar else ''
        ),
        'destination': 'cusd_plus' if is_bsc_dollar else 'cusd',
        'fiat_currency': guardarian_tx.from_currency if direction == 'on_ramp' else guardarian_tx.to_currency,
        'fiat_amount': guardarian_tx.from_amount if direction == 'on_ramp' else None,
        'crypto_currency': guardarian_tx.to_currency if direction == 'on_ramp' else guardarian_tx.from_currency,
        'crypto_amount_estimated': guardarian_tx.to_amount_estimated if direction == 'on_ramp' else None,
        'crypto_amount_actual': guardarian_tx.to_amount_actual if direction == 'on_ramp' else guardarian_tx.from_amount,
        'final_currency': final_currency,
        'final_amount': final_amount,
        'status_detail': status_detail if not guardarian_tx.status_details else f'{status_detail}: {guardarian_tx.status_details}',
        'metadata': {
            **(dict(existing_ramp.metadata or {}) if direction == 'on_ramp' and existing_ramp else {}),
            'guardarian_status': guardarian_tx.status,
            'network': guardarian_tx.network,
            'confio_fee': guardarian_tx.confio_fee_metadata or {},
        },
        'guardarian_transaction': guardarian_tx,
        'usdc_deposit': guardarian_tx.onchain_deposit,
        'usdc_withdrawal': guardarian_tx.onchain_withdrawal,
        'conversion': conversion,
        'completed_at': completed_at,
    }

    ramp_tx, _ = RampTransaction.objects.update_or_create(
        guardarian_transaction=guardarian_tx,
        defaults=defaults,
    )
    return ramp_tx


def sync_unified_transaction_from_ramp(ramp_tx: RampTransaction) -> UnifiedTransactionTable:
    actor_address = _derive_actor_address(ramp_tx)
    final_amount, final_currency = _derive_final_amount(ramp_tx)

    # With no crypto amount anywhere, `amount` below falls back to
    # fiat_amount — and the row is then labelled in a CRYPTO token. That is
    # how production came to hold rows reading "100000 cUSD" for 100,000 CLP
    # (about $100) and "2000 cUSD" for €2,000: the ledger overstates what the
    # user has, by up to ~3800x for COP at the on-ramp maximum. There is no
    # honest token for a fiat figure, so write nothing. The RampTransaction
    # itself is still saved and still visible to support; the ledger simply
    # waits until the provider tells us what actually landed on chain.
    if final_amount is None:
        # A TERMINAL ramp with no crypto amount is a different situation: the
        # user's money really did move and we cannot say how much, so
        # deferring hides real funds instead of hiding a wrong number. Koywe
        # can report DELIVERED with no usable amountIn/amountOut, which is
        # exactly that case. Nothing honest can be written — inventing a
        # figure is what caused the fiat-as-dollars rows — so make it loud
        # enough for support to chase the provider rather than silent.
        if ramp_tx.status in ('COMPLETED', 'AML_REVIEW'):
            logger.error(
                'ramp %s is %s but reports NO crypto amount (fiat %s %s, provider '
                '%s) — the user was paid and the ledger cannot say how much; '
                'needs a provider reconciliation',
                ramp_tx.id, ramp_tx.status, ramp_tx.fiat_amount,
                ramp_tx.fiat_currency, ramp_tx.provider,
            )
        else:
            logger.info(
                'ramp %s: no crypto amount yet (fiat %s %s) — deferring the ledger row',
                getattr(ramp_tx, 'id', '?'), ramp_tx.fiat_amount, ramp_tx.fiat_currency,
            )
        return None

    status = ramp_tx.status
    if status == 'PROCESSING':
        unified_status = 'PENDING'
    elif status == 'COMPLETED':
        unified_status = 'CONFIRMED'
    elif status == 'FAILED':
        unified_status = 'FAILED'
    elif status == 'AML_REVIEW':
        unified_status = 'AML_REVIEW'
    else:
        unified_status = 'PENDING'

    provider_name = ramp_tx.get_provider_display()
    is_on_ramp = ramp_tx.direction == 'on_ramp'

    defaults = {
        'transaction_type': 'ramp',
        'amount': str(final_amount if final_amount is not None else ramp_tx.fiat_amount or Decimal('0')),
        'token_type': _ledger_token(ramp_tx, final_currency),
        # NOTE: deleted_at is deliberately NOT reset here. Doing so revived
        # every deliberately retracted row — a duplicate, a fraudulent one,
        # anything support hid — on the next provider poll. Un-retraction is
        # handled below, and only for the narrow case it was meant for: a row
        # retracted while it had no crypto amount, now that it has one.
        'status': unified_status,
        'transaction_hash': '',
        'error_message': ramp_tx.status_detail or '',
        'sender_user': None if is_on_ramp else ramp_tx.actor_user,
        'sender_business': None if is_on_ramp else ramp_tx.actor_business,
        'sender_type': 'external' if is_on_ramp else ramp_tx.actor_type,
        'sender_display_name': provider_name if is_on_ramp else (ramp_tx.actor_display_name or ''),
        'sender_phone': '',
        'sender_address': '' if is_on_ramp else actor_address,
        'counterparty_user': ramp_tx.actor_user if is_on_ramp else None,
        'counterparty_business': ramp_tx.actor_business if is_on_ramp else None,
        'counterparty_type': ramp_tx.actor_type if is_on_ramp else 'external',
        'counterparty_display_name': (ramp_tx.actor_display_name or '') if is_on_ramp else provider_name,
        'counterparty_phone': None,
        'counterparty_address': actor_address if is_on_ramp else '',
        'description': 'Recarga' if is_on_ramp else 'Retiro',
        'from_address': '' if is_on_ramp else actor_address,
        'to_address': actor_address if is_on_ramp else '',
        'transaction_date': ramp_tx.created_at,
        'ramp_transaction': ramp_tx,
    }

    existing = UnifiedTransactionTable.objects.filter(ramp_transaction=ramp_tx).first()
    # Un-retract ONLY what this module retracted: a row hidden because its
    # amount was a fiat figure, now that a real crypto amount exists. A row
    # support retracted for any other reason — duplicate, fraud, a manual
    # correction — stays hidden, because reviving it is not ours to decide
    # and the provider polls often enough to undo the decision instantly.
    if existing is not None and existing.deleted_at is not None:
        was_fiat_figure = str(existing.amount) == str(ramp_tx.fiat_amount or '')
        if was_fiat_figure:
            defaults['deleted_at'] = None
        else:
            logger.info(
                'ramp %s: unified row %s stays retracted (retracted with a real '
                'amount — not this module to revive)', ramp_tx.id, existing.id)

    unified, _ = UnifiedTransactionTable.objects.update_or_create(
        ramp_transaction=ramp_tx,
        defaults=defaults,
    )
    return unified


def _notify_ramp_status(ramp_tx: RampTransaction, *, created: bool, previous_status: str | None):
    if not ramp_tx.actor_user_id:
        return

    is_on_ramp = ramp_tx.direction == 'on_ramp'
    label = 'recarga' if is_on_ramp else 'retiro'
    fiat_amount_display = str(ramp_tx.fiat_amount) if ramp_tx.fiat_amount is not None else ''
    fiat_currency_display = (ramp_tx.fiat_currency or '').strip()
    wallet_amount = ramp_tx.final_amount or ramp_tx.crypto_amount_actual or ramp_tx.crypto_amount_estimated
    wallet_amount_display = str(wallet_amount) if wallet_amount is not None else ''
    wallet_currency_display = (ramp_tx.final_currency or 'CUSD').strip()
    amount_display = fiat_amount_display if is_on_ramp and fiat_amount_display else wallet_amount_display
    token_display = fiat_currency_display if is_on_ramp and fiat_currency_display else wallet_currency_display

    notification_type = None
    title = None
    message = None

    reservation_state = str(
        (ramp_tx.metadata or {}).get('wallet_address_reservation_state') or ''
    )
    provider_order_just_recorded = bool(
        getattr(ramp_tx, '_provider_order_just_recorded', False)
    )
    if hasattr(ramp_tx, '_provider_order_just_recorded'):
        # This is a one-save instruction. Reusing the same model instance for
        # a later save must not emit a second pending notification.
        delattr(ramp_tx, '_provider_order_just_recorded')

    if (
        (created or provider_order_just_recorded)
        and ramp_tx.status in {'PENDING', 'PROCESSING'}
        and reservation_state != 'creating_order'
    ):
        notification_type = NotificationTypeChoices.RAMP_PENDING
        title = 'Operación en proceso'
        message = f'Tu {label} está en proceso.'
    elif previous_status != ramp_tx.status and ramp_tx.status == 'PROCESSING' and previous_status == 'PENDING':
        notification_type = NotificationTypeChoices.RAMP_PROCESSING
        title = 'Pago recibido'
        message = f'Recibimos tu pago de {amount_display} {token_display}. Tu {label} se acreditará en breve.' if is_on_ramp else f'Recibimos tu solicitud de {label}. Se acreditará en breve.'
    elif previous_status != ramp_tx.status and ramp_tx.status == 'COMPLETED':
        notification_type = NotificationTypeChoices.RAMP_COMPLETED
        title = 'Operación completada'
        message = f'Tu {label} de {amount_display} {token_display} se completó.'.strip()
    elif previous_status != ramp_tx.status and ramp_tx.status in {'FAILED', 'AML_REVIEW'}:
        notification_type = NotificationTypeChoices.RAMP_FAILED
        title = 'Operación con problema'
        message = (
            f'Tu {label} requiere revisión.'
            if ramp_tx.status == 'AML_REVIEW'
            else f'No pudimos completar tu {label}.'
        )

    if not notification_type:
        return

    create_notification(
        user=ramp_tx.actor_user,
        business=ramp_tx.actor_business,
        notification_type=notification_type,
        title=title,
        message=message,
        data={
            'transaction_type': 'ramp',
            'direction': ramp_tx.direction,
            'provider': ramp_tx.provider,
            'amount': amount_display,
            'token_type': token_display,
            'currency': token_display,
            'ramp_fiat_amount': fiat_amount_display,
            'ramp_fiat_currency': fiat_currency_display,
            'wallet_amount': wallet_amount_display,
            'wallet_currency': wallet_currency_display,
            'internal_id': str(ramp_tx.internal_id),
        },
        related_object_type='RampTransaction',
        related_object_id=str(ramp_tx.internal_id),
        action_url=f'confio://transaction/{ramp_tx.internal_id}',
    )


@receiver(pre_save, sender=RampTransaction)
def cache_previous_ramp_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None  # pylint: disable=protected-access
        return
    try:
        previous = sender.objects.get(pk=instance.pk)
        instance._previous_status = previous.status  # pylint: disable=protected-access
    except sender.DoesNotExist:
        instance._previous_status = None  # pylint: disable=protected-access


@receiver(post_save, sender=GuardarianTransaction)
def handle_guardarian_transaction_save(sender, instance, **kwargs):
    ramp_tx = sync_ramp_transaction_from_guardarian(instance)
    if ramp_tx.actor_user_id:
        touch_user_activity(ramp_tx.actor_user_id)


@receiver(post_save, sender=RampTransaction)
def handle_ramp_transaction_save(sender, instance, created, **kwargs):
    try:
        sync_unified_transaction_from_ramp(instance)
    except Exception:  # noqa: BLE001 — derived-ledger failure cannot fail the provider order
        logger.exception(
            'ramp %s: failed to sync unified transaction',
            getattr(instance, 'pk', '?'),
        )
    previous_status = getattr(instance, '_previous_status', None)
    try:
        _notify_ramp_status(instance, created=created, previous_status=previous_status)
    except Exception:  # noqa: BLE001 — notification failure cannot fail a money operation
        logger.exception(
            'ramp %s: failed to create status notification',
            getattr(instance, 'pk', '?'),
        )

    # Emit the first successful on-ramp completion for this user.
    # This captures the `claim -> first_deposit` funnel milestone without
    # coupling to a specific provider implementation path.
    if (
        instance.actor_user_id
        and instance.direction == 'on_ramp'
        and instance.status == 'COMPLETED'
        and previous_status != 'COMPLETED'
    ):
        prior_completed_exists = RampTransaction.objects.filter(
            actor_user_id=instance.actor_user_id,
            direction='on_ramp',
            status='COMPLETED',
        ).exclude(pk=instance.pk).exists()

        if not prior_completed_exists:
            amount_value = (
                instance.final_amount
                or instance.crypto_amount_actual
                or instance.crypto_amount_estimated
            )
            source_type = _classify_first_deposit_source(instance.actor_user_id)
            referral_attribution, attribution_session_id = _first_deposit_referral_attribution(
                instance.actor_user_id
            )
            # Platform is not stored on RampTransaction (server-issued provider record);
            # derive it from the user's most recent funnel event that carried a known
            # platform value (signup_completed, referral_attached, etc.). This keeps the
            # F4 first_deposit event segmentable by iOS/Android without a schema migration.
            derived_platform = referral_attribution.get('click_platform') or ''
            try:
                if not derived_platform:
                    from users.models_analytics import FunnelEvent
                    last_known = (
                        FunnelEvent.objects
                        .filter(user_id=instance.actor_user_id)
                        .exclude(platform='')
                        .order_by('-created_at')
                        .values_list('platform', flat=True)
                        .first()
                    )
                    if last_known:
                        derived_platform = last_known
            except Exception:
                # Instrumentation must never break the deposit path.
                derived_platform = ''
            emit_event(
                'first_deposit',
                user=instance.actor_user,
                country=instance.country_code or getattr(instance.actor_user, 'phone_country', '') or '',
                platform=derived_platform,
                source_type=source_type,
                channel='koywe' if instance.provider == 'KOYWE' else (instance.provider or '').lower(),
                session_id=attribution_session_id,
                properties={
                    **referral_attribution,
                    'provider': instance.provider,
                    'internal_id': str(instance.internal_id),
                    'fiat_currency': instance.fiat_currency or '',
                    'fiat_amount': str(instance.fiat_amount) if instance.fiat_amount is not None else '',
                    'final_currency': instance.final_currency or '',
                    'final_amount': str(amount_value) if amount_value is not None else '',
                },
            )


@receiver(post_save, sender=USDCDeposit)
def handle_ramp_deposit_link(sender, instance, **kwargs):
    guardarian_tx = _safe_related(instance, 'guardarian_source')
    if guardarian_tx:
        ramp_tx = sync_ramp_transaction_from_guardarian(guardarian_tx)
        if ramp_tx.conversion_id and ramp_tx.status == 'COMPLETED':
            return
        if (
            ramp_tx.usdc_deposit_id != instance.id
            or ramp_tx.actor_address != (instance.actor_address or '')
            or ramp_tx.status_detail != GUARDARIAN_WAITING_FOR_AUTOSWAP
        ):
            ramp_tx.usdc_deposit = instance
            ramp_tx.actor_address = instance.actor_address or ramp_tx.actor_address
            ramp_tx.status = 'PROCESSING'
            ramp_tx.status_detail = GUARDARIAN_WAITING_FOR_AUTOSWAP
            ramp_tx.save(update_fields=['usdc_deposit', 'actor_address', 'status', 'status_detail', 'updated_at'])
        return

    link_koywe_deposit_to_ramp(instance)


@receiver(post_save, sender=USDCWithdrawal)
def handle_ramp_withdrawal_link(sender, instance, **kwargs):
    guardarian_tx = _safe_related(instance, 'guardarian_dest')
    if not guardarian_tx:
        return
    ramp_tx = sync_ramp_transaction_from_guardarian(guardarian_tx)
    if (
        ramp_tx.usdc_withdrawal_id != instance.id
        or ramp_tx.actor_address != (instance.actor_address or '')
        or ramp_tx.status_detail != 'withdrawal_confirmed_provider_pending'
    ):
        ramp_tx.usdc_withdrawal = instance
        ramp_tx.actor_address = instance.actor_address or ramp_tx.actor_address
        ramp_tx.status = 'PROCESSING'
        ramp_tx.status_detail = 'withdrawal_confirmed_provider_pending'
        ramp_tx.save(update_fields=['usdc_withdrawal', 'actor_address', 'status', 'status_detail', 'updated_at'])


@receiver(post_save, sender=Conversion)
def handle_ramp_conversion_link(sender, instance, **kwargs):
    # BSC provider delivery and foreground mint are distinct transactions.
    # Link through the source-transfer attribution captured by the BSC
    # scanner, and allow one sweep conversion to settle several arrivals.
    attributed = _attributed_bsc_ramps(instance)
    if attributed:
        allocations = _bsc_ramp_net_allocations(instance, attributed)
        final_currency = (
            'CUSD+' if instance.conversion_type == 'to_savings' else 'CUSD'
        )
        for ramp_tx, allocated_net in zip(attributed, allocations):
            ramp_tx.conversion = instance
            ramp_tx.actor_address = (
                instance.actor_address or instance.user_bsc_address
                or ramp_tx.actor_address
            )
            ramp_tx.final_amount = allocated_net
            ramp_tx.final_currency = final_currency
            ramp_metadata = dict(ramp_tx.metadata or {})
            ramp_metadata['conversion_allocation'] = {
                'gross_amount': ramp_metadata['bsc_arrival_amount'],
                'net_amount': format(allocated_net, 'f'),
                'conversion_id': str(instance.internal_id),
            }
            ramp_tx.metadata = ramp_metadata
            update_fields = [
                'conversion', 'actor_address', 'final_amount',
                'final_currency', 'metadata', 'updated_at',
            ]
            if ramp_tx.provider == 'guardarian':
                ramp_tx.status = 'COMPLETED'
                ramp_tx.status_detail = 'conversion_completed'
                ramp_tx.completed_at = ramp_tx.completed_at or timezone.now()
                update_fields.extend(['status', 'status_detail', 'completed_at'])
            ramp_tx.save(update_fields=update_fields)
        # The Conversion remains the exact fee ledger behind the ramp, but a
        # second user-visible conversion card would double-count one deposit.
        # Unified rows are derived mirrors, so retract the conversion mirror
        # after the ramp rows have been materialized.
        UnifiedTransactionTable.objects.filter(conversion=instance).delete()
        Conversion.objects.filter(pk=instance.pk).update(source='ramp')
        return

    # ramp_transactions is now a reverse FK manager (was OneToOne). For the
    # signal we only auto-attach if the conversion isn't already linked. If
    # an admin/script has manually linked multiple ramps (consolidated swap
    # case), we don't second-guess.
    try:
        ramp_tx = instance.ramp_transactions.first()
    except Exception:
        ramp_tx = None
    if not ramp_tx:
        ramp_tx = _find_guardarian_ramp_for_conversion(instance)
    if not ramp_tx:
        ramp_tx = _find_koywe_ramp_for_conversion(instance)
    if not ramp_tx:
        return
    ramp_tx.conversion = instance
    ramp_tx.actor_address = instance.actor_address or ramp_tx.actor_address
    if ramp_tx.provider == 'koywe':
        # Koywe lifecycle is authoritative via the webhook / poller path
        # (sync_koywe_ramp_transaction_from_order). The internal conversion
        # completing only means the cUSD<->USDC swap settled, not that Koywe
        # delivered fiat. A failed off-ramp conversion, however, means Koywe
        # was never funded and must not remain WAITING indefinitely.
        if ramp_tx.direction == 'off_ramp' and instance.status == 'FAILED':
            ramp_tx.status = 'FAILED'
            ramp_tx.status_detail = 'conversion_failed'
            ramp_tx.completed_at = None
            if ramp_tx.usdc_withdrawal_id:
                USDCWithdrawal.objects.filter(
                    pk=ramp_tx.usdc_withdrawal_id,
                    status__in=['PENDING', 'PROCESSING'],
                ).update(
                    status='FAILED',
                    error_message=instance.error_message or 'conversion_failed',
                    updated_at=timezone.now(),
                )
            ramp_tx.save(
                update_fields=[
                    'conversion',
                    'actor_address',
                    'status',
                    'status_detail',
                    'completed_at',
                    'updated_at',
                ]
            )
            return
        update_fields = ['conversion', 'actor_address', 'updated_at']
        if ramp_tx.direction == 'on_ramp' and instance.status == 'COMPLETED':
            ramp_tx.final_amount, ramp_tx.final_currency = _derive_final_amount(ramp_tx)
            update_fields.extend(['final_amount', 'final_currency'])
        ramp_tx.save(update_fields=update_fields)
        return
    ramp_tx.final_amount, ramp_tx.final_currency = _derive_final_amount(ramp_tx)
    if instance.status == 'COMPLETED':
        ramp_tx.status = 'COMPLETED'
        ramp_tx.status_detail = 'conversion_completed'
        if not ramp_tx.completed_at:
            ramp_tx.completed_at = timezone.now()
    elif instance.status == 'FAILED':
        ramp_tx.status = 'PROCESSING'
        ramp_tx.status_detail = GUARDARIAN_AUTOSWAP_FAILED_RETRYABLE
        ramp_tx.completed_at = None
    else:
        ramp_tx.status = 'PROCESSING'
        ramp_tx.status_detail = GUARDARIAN_WAITING_FOR_AUTOSWAP
        ramp_tx.completed_at = None
    ramp_tx.save(update_fields=['conversion', 'actor_address', 'final_amount', 'final_currency', 'status', 'status_detail', 'completed_at', 'updated_at'])
