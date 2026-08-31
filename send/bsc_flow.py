"""
BSC send flow — sponsored EIP-7702 batches moving the BSC dollar between
Confío users or to external addresses. Phase 2 of the cUSD phase-out: the
transactional sibling of the savings rail (presale/bsc_flow.py shape).

Two-step, server-authoritative:

  prepare_bsc_send   resolve the recipient (user id → phone → raw 0x, the
                     same priority as the Algorand rail), pick the funding
                     source and call shape (A/B/C below), store the EXACT
                     call batch on the SendTransaction row. The client only
                     ever signs what the server stored.
  submit_bsc_send    recompute the EIP-712 digest from the STORED calls,
                     verify the sender's signature, byte-exact-revalidate
                     the batch, then broadcast via send_sponsored_batch.
                     A Celery task resolves the receipt into
                     CONFIRMED/FAILED, writes ledger movements and fires
                     SEND_SENT / SEND_RECEIVED.

Routing follows one product rule regardless of whether funds start in cUSD+,
cUSD, or both: eligible Confío recipients receive cUSD+; ineligible Confío
recipients receive cUSD through a fee-free internal wrap/unwrap; external
addresses receive USDT through the fee-bearing perimeter exit. CONFIO is a
plain BEP-20 transfer. Raw USDT is only a pre-rollout compatibility fallback
and cannot bypass the live perimeter. Mixed balances normalize atomically and
charge one exit fee, not one per funding leg.

Recipient coverage: bsc_address is client-registered (the server cannot
derive it), so a recipient who hasn't opened a post-EVM app version has no
on-chain destination. Locked decision (Julian, 2026-07-30): BLOCK the send
and notify BOTH sides — the recipient push is what drives registration.
"""
import json
import logging
import re
import time
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .kinds import BSC_SEND_KINDS

logger = logging.getLogger(__name__)

WAD = 10 ** 18
# minOut tolerance for redeem sends: pPlus only rises, but the prepared
# share count meets a slightly newer price at execution — 0.5% absorbs any
# realistic drift while still bounding what the recipient could lose.
REDEEM_MIN_OUT_BPS = 9_950
# The same 0.5% execution tolerance protects fee-free cUSD -> cUSD+
# conversions.  The argument to wrapCusd is Ondo's minimum USDY received,
# not a share-count floor.
INTERNAL_CONVERSION_MIN_OUT_BPS = 9_950
# MAX-send dust tolerance: the mint path floors twice on-chain (USDY units
# at the oracle price, then shares at pPlus), leaving a position a few wei
# short of the deposited cents — while every float layer above (position_usd,
# GraphQL, the app) reads it back as exactly the cent amount, so MAX
# re-requests a value the wallet is wei-short of. A request over the live
# balance by ≤ this is a full-position send, not an overdraft: clamp to the
# real balance instead of refusing. 10**12 wei = $0.000001 — far above any
# rounding dust, far below a spendable amount.
MAX_SEND_DUST_WEI = 10 ** 12
# Ondo's InstantManager rejects any redemption yielding under 1.00 USDT.
# Verified on BSC mainnet 2026-08-01: usdtOut of exactly 10**18 succeeds,
# 10**18 - 1 reverts with custom error 0xd0022dba. Nothing in our own
# contracts enforces this — the vault's minUsdtOut floor (REDEEM_MIN_OUT_BPS)
# sits BELOW it and so cannot catch it — and the revert only surfaces in
# simulation, after the SendTransaction row already exists. The canonical
# value lives in cusd_plus.vault because mint and send must share it.
EVM_ADDR_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')


def _min_usdy_out(dollar_wei: int, oracle_price_wad: int) -> int:
    """USDY-token floor for a dollar-denominated internal wrap.

    InstantManager's argument is RWA token units, not USD value.  USDY is an
    accumulating token, so one USDY is worth `oracle_price_wad / WAD` dollars.
    """
    if dollar_wei <= 0 or oracle_price_wad <= 0:
        return 0
    expected_usdy = dollar_wei * WAD // oracle_price_wad
    return expected_usdy * INTERNAL_CONVERSION_MIN_OUT_BPS // 10_000


def _uint_word(v: int) -> str:
    return format(int(v), 'x').rjust(64, '0')


def _addr_word(addr: str) -> str:
    return addr.lower().replace('0x', '').rjust(64, '0')


def _vault_address() -> str:
    return (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()


def _cusd_address() -> str:
    return (getattr(settings, 'CUSD_VAULT_ADDRESS', '') or '').lower()


def _confio_token_address() -> str:
    return (getattr(settings, 'BSC_CONFIO_TOKEN_ADDRESS', '') or '').lower()


def _exit_quote(gross_wei: int) -> tuple[int, int, int, int]:
    """Authoritative perimeter quote for an external dollar delivery."""
    if not getattr(settings, 'CUSD_CONVERSION_FEE_ENABLED', False):
        return gross_wei, 0, gross_wei, 0
    from cusd_plus.cusd_vault import preview_redeem_wei
    quote = preview_redeem_wei(gross_wei)
    return quote.gross_wei, quote.fee_wei, quote.net_wei, quote.fee_bps


def _decimal_wei(value: int) -> str:
    return format(Decimal(value) / Decimal(WAD), 'f')


def _display_name(user) -> str:
    return (user.get_full_name() or user.username or user.email or 'Contacto')


def _notify_recipient_needs_app(recipient_user, sender_user) -> None:
    """The adoption loop for the coverage cold-start: opening the app IS the
    registration (ensureBscAddressRegistered fires on every authenticated
    entry), so the push is the fix, not just an apology."""
    try:
        from notifications import utils as notif_utils
        from notifications.models import NotificationType as NotifType
        notif_utils.create_notification(
            user=recipient_user,
            account=None,
            business=None,
            notification_type=NotifType.SEND_RECEIVED,
            title='Alguien quiere enviarte dólares',
            message=(
                f'{_display_name(sender_user)} intentó enviarte dinero. '
                'Abre Confío para activar tu cuenta y poder recibirlo.'
            ),
            data={'transaction_type': 'send_blocked', 'reason': 'no_bsc_address'},
        )
    except Exception:  # noqa: BLE001 — the nudge must not mask the error
        logger.exception('recipient-needs-app notification failed')


def _resolve_recipient(recipient_user_id, recipient_phone, recipient_address):
    """Mirror of the Algorand rail's priority (blockchain/mutations.py):
    user id → phone (any client shape) → raw 0x address. Returns
    (recipient_user|None, recipient_business|None, bsc_address|None, error|None).
    recipient_user is set for internal recipients even when their address is
    missing — the caller needs it to send the activation nudge."""
    from django.contrib.auth import get_user_model
    from users.models import Account, RetiredWalletAddress
    User = get_user_model()

    if recipient_user_id:
        try:
            recipient_user = User.objects.get(id=recipient_user_id)
        except User.DoesNotExist:
            return None, None, None, 'recipient_not_found'
        account = recipient_user.accounts.filter(
            account_type='personal', account_index=0).first()
        addr = (getattr(account, 'bsc_address', None) or '').lower() if account else ''
        return recipient_user, None, (addr or None), None

    if recipient_phone:
        # Full number only — canonical key "57:313…" or E.164. A local number
        # without a calling code identifies no one and resolves to nothing.
        from users.phone_utils import find_user_by_phone
        found = find_user_by_phone(recipient_phone)
        if not found:
            # Non-Confío phone: the invite flow is a separate product
            # (Algorand invite-send today; BSC invites are a follow-up).
            return None, None, None, 'recipient_not_on_confio'
        account = found.accounts.filter(account_type='personal', account_index=0).first()
        addr = (getattr(account, 'bsc_address', None) or '').lower() if account else ''
        return found, None, (addr or None), None

    if recipient_address:
        if not EVM_ADDR_RE.match(recipient_address):
            return None, None, None, 'invalid_recipient_address'
        addr = recipient_address.lower()
        # Serialize reverse lookup with reenrollment. A concurrent address
        # replacement either sees the later SendTransaction reservation or
        # commits its tombstone before this lookup is allowed to continue.
        with transaction.atomic():
            match = Account.objects.select_for_update(of=('self',)).filter(
                bsc_address__iexact=addr,
                deleted_at__isnull=True,
            ).select_related('user', 'business').first()
            if RetiredWalletAddress.is_retired(
                RetiredWalletAddress.CHAIN_BSC,
                addr,
            ):
                return None, None, None, 'retired_recipient_address'
            if match:
                return match.user, match.business, addr, None
            return None, None, addr, None

    return None, None, None, 'recipient_required'


def _lock_internal_recipient_account(recipient_user, recipient_business):
    """Lock the account whose BSC address is about to be snapshotted.

    Wallet reenrollment locks the same row, so an inbound send either commits
    its old-address intent first (and blocks replacement) or observes the new
    address and asks the caller to prepare again.
    """
    from users.models import Account

    accounts = Account.objects.select_for_update().filter(deleted_at__isnull=True)
    if recipient_business is not None:
        return accounts.filter(
            business=recipient_business,
            account_type='business',
        ).order_by('account_index').first()
    if recipient_user is not None:
        return accounts.filter(
            user=recipient_user,
            account_type='personal',
            account_index=0,
        ).first()
    return None


def prepare_bsc_send(user, jwt_ctx, amount, recipient_user_id=None,
                     recipient_phone=None, recipient_address=None,
                     memo: str = '', idempotency_key: str = '',
                     token: str = '') -> dict:
    """Build and store the send. `jwt_ctx` is the validated JWT business
    context (send_funds already enforced by the mutation). `token` empty =
    dollar-value send (shapes A–C); 'CUSD_PLUS'/'CONFIO' = the explicit
    token shapes D/E."""
    from cusd_plus import vault as cp_vault
    from cusd_plus.eligibility import is_ondo_eligible
    from cusd_plus.sponsor_7702 import (
        SEL_APPROVE,
        SEL_CUSD_REDEEM,
        SEL_REDEEM_TO_USDT,
        SEL_TRANSFER,
        SEL_UNWRAP_TO_CUSD,
        SEL_WRAP_CUSD,
        USDT_BSC,
    )
    from users.models import Account
    from .models import SendTransaction

    vault_addr = _vault_address()
    cusd_addr = _cusd_address()
    if not vault_addr or not cusd_addr:
        return {'success': False, 'error': 'vault_not_configured'}
    if not getattr(settings, 'BSC_SEND_ENABLED', False):
        return {'success': False, 'error': 'bsc_send_disabled'}

    # Sender account from the JWT context only (house rule).
    if jwt_ctx['account_type'] == 'business' and jwt_ctx.get('business_id'):
        sender_account = Account.objects.filter(
            business_id=jwt_ctx['business_id'], account_type='business',
            account_index=jwt_ctx.get('account_index', 0)).first()
        sender_business = sender_account.business if sender_account else None
    else:
        sender_account = user.accounts.filter(
            account_type='personal', account_index=jwt_ctx.get('account_index', 0)).first()
        sender_business = None
    sender_addr = (getattr(sender_account, 'bsc_address', None) or '').lower()
    if not sender_addr:
        return {'success': False, 'error': 'no_bsc_address'}

    # Idempotent replay: same sender + key. Look up early but DON'T return
    # yet — a reused key with DIFFERENT params must not silently hand back
    # the old prepared calls (audit P3), so we compare against the resolved
    # request below before replaying.
    existing = None
    if idempotency_key:
        existing = SendTransaction.objects.filter(
            sender_user=user, idempotency_key=idempotency_key,
            deleted_at__isnull=True,
        ).first()

    try:
        amount_usd = Decimal(str(amount))
    except Exception:  # noqa: BLE001
        return {'success': False, 'error': 'invalid_amount'}
    if amount_usd <= 0:
        return {'success': False, 'error': 'invalid_amount'}

    recipient_user, recipient_business, recipient_addr, err = _resolve_recipient(
        recipient_user_id, recipient_phone, recipient_address)
    if err:
        return {'success': False, 'error': err}
    if recipient_user is not None and recipient_user.id == user.id and not recipient_business:
        return {'success': False, 'error': 'self_send_not_allowed'}
    if not recipient_addr:
        # Internal recipient without a registered address: BLOCK + nudge
        # (locked decision — no dual-rail, no escrow).
        if recipient_user is not None:
            _notify_recipient_needs_app(recipient_user, user)
        return {'success': False, 'error': 'recipient_no_bsc_address'}

    requested = (token or '').upper()

    # Now that amount + recipient + token intent are known, resolve the
    # idempotency key: replay ONLY if the request matches the stored row;
    # a mismatch is a reused key for a different send → reject, never return
    # the stale calls (audit P3).
    if existing is not None and existing.bsc_calls_json:
        # Token intent must line up too: an explicit CONFIO/CUSD_PLUS request
        # must match the stored token; a dollar-value request (token='') must
        # have stored a dollar send (the funding source may differ run to run,
        # so USDT and CUSD_PLUS are interchangeable there).
        if requested in ('CONFIO', 'CUSD_PLUS'):
            token_ok = existing.token_type == requested
        else:
            token_ok = existing.token_type in ('CUSD_PLUS', 'CUSD', 'USDT')
        same = (
            token_ok
            and existing.amount == amount_usd
            and (existing.recipient_address or '').lower() == recipient_addr.lower()
            and (existing.recipient_user_id or None) == (recipient_user.id if recipient_user else None)
            and (existing.recipient_business_id or None) == (recipient_business.id if recipient_business else None)
        )
        if not same:
            return {'success': False, 'error': 'idempotency_key_conflict'}
        from cusd_plus.sponsor_7702 import intent_id_hex
        existing_kind = (json.loads(existing.bsc_calls_json) or {}).get('kind', '')
        return {
            'success': True,
            'send_id': existing.internal_id,
            'calls': (json.loads(existing.bsc_calls_json) or {}).get('calls', []),
            'token_type': existing.token_type,
            'intent_id': intent_id_hex(existing_kind, existing.id),
            'gross_amount': (json.loads(existing.bsc_calls_json) or {}).get('receipt', {}).get('gross'),
            'fee_amount': (json.loads(existing.bsc_calls_json) or {}).get('receipt', {}).get('fee'),
            'net_amount': (json.loads(existing.bsc_calls_json) or {}).get('receipt', {}).get('net'),
            'fee_bps': (json.loads(existing.bsc_calls_json) or {}).get('receipt', {}).get('fee_bps', 0),
        }

    amount_wei = int(amount_usd * WAD)
    receipt_gross_wei = amount_wei
    receipt_fee_wei = 0
    receipt_net_wei = amount_wei
    receipt_fee_bps = 0
    mixed_meta = None
    if requested and requested not in ('CUSD_PLUS', 'CONFIO'):
        return {'success': False, 'error': 'unsupported_token'}

    if requested == 'CONFIO':
        # E: plain BEP-20 transfer of the governance/utility token.
        confio_addr = _confio_token_address()
        if not confio_addr:
            return {'success': False, 'error': 'confio_not_configured'}
        try:
            confio_raw = cp_vault.erc20_balance_raw(confio_addr, sender_addr)
        except Exception as exc:  # noqa: BLE001
            logger.warning('[SEND][BSC] balance rpc failed: %s', exc)
            return {'success': False, 'error': 'balance_unavailable'}
        if confio_raw < amount_wei:
            if confio_raw + MAX_SEND_DUST_WEI < amount_wei:
                return {'success': False, 'error': 'insufficient_balance'}
            amount_wei = confio_raw  # dust-short MAX → send the full balance
        if amount_wei <= 0:
            return {'success': False, 'error': 'invalid_amount'}
        kind = 'send_confio'
        token_type = 'CONFIO'
        token_addr, units, min_out = confio_addr, amount_wei, None
        calls = [{
            'to': confio_addr, 'value': '0',
            'data': '0x' + SEL_TRANSFER + _addr_word(recipient_addr) + _uint_word(amount_wei),
        }]
    else:
        # Funding source: prefer the yield position, then universal cUSD.
        # Raw USDT is only a transient-arrival compatibility fallback.
        try:
            pps_wad = cp_vault.p_plus_wad()
            # Needed to predict a redeem exactly (the chain floors twice).
            oracle_p_wad = cp_vault.last_oracle_price_wad()
            if pps_wad <= 0 or oracle_p_wad <= 0:
                raise ValueError('invalid vault price')
            shares_raw = cp_vault.erc20_balance_raw(vault_addr, sender_addr)
            shares_value_wei = (shares_raw * pps_wad) // WAD
            cusd_raw = cp_vault.erc20_balance_raw(cusd_addr, sender_addr)
            usdt_raw = cp_vault.usdt_balance_raw(sender_addr, fresh=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning('[SEND][BSC] balance rpc failed: %s', exc)
            return {'success': False, 'error': 'balance_unavailable'}

        if shares_value_wei + MAX_SEND_DUST_WEI >= amount_wei:
            # Value → shares at the live price; floor favors the sender's
            # remaining balance (never over-burn).
            shares = (amount_wei * WAD) // pps_wad
            if shares > shares_raw:
                shares = shares_raw  # dust-short MAX → the whole position
            if shares <= 0:
                return {'success': False, 'error': 'invalid_amount'}
            recipient_eligible = (
                recipient_user is not None
                and recipient_business is None
                and is_ondo_eligible(recipient_user)
            )
            if recipient_eligible:
                kind = 'send_cusd_plus'
                token_type = 'CUSD_PLUS'
                token_addr, units, min_out = vault_addr, shares, None
                calls = [{
                    'to': vault_addr, 'value': '0',
                    'data': '0x' + SEL_TRANSFER + _addr_word(recipient_addr) + _uint_word(shares),
                }]
            elif recipient_user is not None or recipient_business is not None:
                # Cross-jurisdiction Confío friend send: cUSD+ -> cUSD is
                # perimeter-internal and therefore fee-free. The sponsor is
                # allowed to bind the recipient in this exact stored intent.
                shares = -(-amount_wei * WAD // pps_wad)
                for _ in range(8):
                    if shares >= shares_raw:
                        break
                    if cp_vault.redeem_gross_usdt_out(shares, pps_wad, oracle_p_wad) >= amount_wei:
                        break
                    shares += 1
                if shares > shares_raw:
                    shares = shares_raw
                cusd_out = cp_vault.redeem_gross_usdt_out(shares, pps_wad, oracle_p_wad)
                if cusd_out < cp_vault.ONDO_MIN_REDEEM_WEI:
                    return {'success': False, 'error': 'redeem_below_minimum'}
                kind = 'send_unwrap_cusd'
                token_type = 'CUSD'
                token_addr, units = vault_addr, shares
                min_out = (min(amount_wei, cusd_out) * REDEEM_MIN_OUT_BPS) // 10_000
                calls = [{
                    'to': vault_addr, 'value': '0',
                    'data': '0x' + SEL_UNWRAP_TO_CUSD + _uint_word(shares)
                            + _uint_word(min_out) + _addr_word(recipient_addr),
                }]
            else:
                # External address: leave the Confío dollar perimeter and
                # pay the universal 0.9% via redeemToUsdt.
                #
                # The entered amount is the GROSS Confío-dollar debit. The
                # recipient receives that amount minus the universal 0.9%
                # exit fee; new clients disclose the exact net, while legacy
                # clients remain executable and briefly show stale fee copy.
                # Round shares up until the pre-fee redeem covers the gross
                # debit so flooring cannot silently reduce the quoted base.
                shares = -(-amount_wei * WAD // pps_wad)
                # The chain floors TWICE (shares→USDY at the oracle price, then
                # USDY→USDT), so ceiling on shares alone can still land short.
                # Nudge up until the EXACT preview covers the request; each
                # share-wei moves the output by about a wei, so this converges
                # immediately. Bounded so a pathological price can't spin.
                for _ in range(8):
                    if shares >= shares_raw:
                        break
                    if cp_vault.redeem_gross_usdt_out(
                            shares, pps_wad, oracle_p_wad) >= amount_wei:
                        break
                    shares += 1
                if shares > shares_raw:
                    shares = shares_raw  # dust-short MAX → the whole position
                if shares <= 0:
                    return {'success': False, 'error': 'invalid_amount'}
                # Ondo's floor applies to what the recipient RECEIVES. Checked
                # against the exact two-floor preview, not shares * pPlus,
                # which is an OVER-estimate and would approve a redemption
                # Ondo rejects (audit 2026-08-01).
                gross_redeem_wei = cp_vault.redeem_gross_usdt_out(
                    shares, pps_wad, oracle_p_wad)
                (receipt_gross_wei, receipt_fee_wei, redeem_out_wei,
                 receipt_fee_bps) = _exit_quote(gross_redeem_wei)
                receipt_net_wei = redeem_out_wei
                if gross_redeem_wei < cp_vault.ONDO_MIN_REDEEM_WEI and (
                        usdt_raw + MAX_SEND_DUST_WEI >= amount_wei):
                    # Not a dead end: raw USDT covers this send. Refusing
                    # outright stranded a user holding $0.50 of savings and
                    # plenty of USDT (audit 2026-08-01). This branch is
                    # external-only: raw USDT already is the required output
                    # asset, so converting it into cUSD merely to redeem it
                    # again would be both unnecessary and fee-wasteful.
                    if amount_wei > usdt_raw:
                        amount_wei = usdt_raw
                    kind = 'send_usdt'
                    token_type = 'USDT'
                    token_addr, units, min_out = USDT_BSC, amount_wei, None
                    calls = [{
                        'to': USDT_BSC, 'value': '0',
                        'data': '0x' + SEL_TRANSFER + _addr_word(recipient_addr)
                                + _uint_word(amount_wei),
                    }]
                elif gross_redeem_wei < cp_vault.ONDO_MIN_REDEEM_WEI:
                    return {'success': False, 'error': 'redeem_below_minimum'}
                else:
                    kind = 'send_redeem'
                    token_type = 'USDT'
                    # minOut floors what the RECIPIENT accepts; derived from the
                    # exact preview, not the request, now that shares may be a
                    # hair above it.
                    min_out = (redeem_out_wei * REDEEM_MIN_OUT_BPS) // 10_000
                    token_addr, units = vault_addr, shares
                    calls = [{
                        'to': vault_addr, 'value': '0',
                        'data': '0x' + SEL_REDEEM_TO_USDT + _uint_word(shares)
                                + _uint_word(min_out) + _addr_word(recipient_addr),
                    }]
        elif cusd_raw + MAX_SEND_DUST_WEI >= amount_wei:
            if amount_wei > cusd_raw:
                amount_wei = cusd_raw
            if amount_wei <= 0:
                return {'success': False, 'error': 'invalid_amount'}
            recipient_eligible = (
                recipient_user is not None
                and recipient_business is None
                and is_ondo_eligible(recipient_user)
            )
            if recipient_eligible:
                # cUSD -> cUSD+ for an eligible friend, fee-free. Approval and
                # wrap execute atomically in the same sponsored batch.
                kind = 'send_wrap_cusd'
                token_type = 'CUSD_PLUS'
                try:
                    mint_oracle_p_wad = cp_vault.current_oracle_price_wad()
                except Exception as exc:  # noqa: BLE001
                    logger.warning('[SEND][BSC] live mint oracle read failed: %s', exc)
                    return {'success': False, 'error': 'quote_unavailable'}
                wrap_min_out = _min_usdy_out(amount_wei, mint_oracle_p_wad)
                token_addr, units, min_out = vault_addr, amount_wei, wrap_min_out
                calls = [
                    {
                        'to': cusd_addr, 'value': '0',
                        'data': '0x' + SEL_APPROVE + _addr_word(vault_addr)
                                + _uint_word(amount_wei),
                    },
                    {
                        'to': vault_addr, 'value': '0',
                        'data': '0x' + SEL_WRAP_CUSD + _uint_word(amount_wei)
                                + _uint_word(wrap_min_out)
                                + _addr_word(recipient_addr),
                    },
                ]
            elif recipient_user is not None or recipient_business is not None:
                kind = 'send_cusd'
                token_type = 'CUSD'
                token_addr, units, min_out = cusd_addr, amount_wei, None
                calls = [{
                    'to': cusd_addr, 'value': '0',
                    'data': '0x' + SEL_TRANSFER + _addr_word(recipient_addr)
                            + _uint_word(amount_wei),
                }]
            else:
                # External wallet receives USDT net of the universal fee.
                from cusd_plus.cusd_vault import preview_redeem_wei
                preview = preview_redeem_wei(amount_wei)
                receipt_gross_wei = preview.gross_wei
                receipt_fee_wei = preview.fee_wei
                receipt_net_wei = preview.net_wei
                receipt_fee_bps = preview.fee_bps
                kind = 'send_cusd_redeem'
                token_type = 'USDT'
                token_addr, units, min_out = cusd_addr, amount_wei, preview.net_wei
                calls = [{
                    'to': cusd_addr, 'value': '0',
                    'data': '0x' + SEL_CUSD_REDEEM + _uint_word(amount_wei)
                            + _uint_word(preview.net_wei) + _addr_word(recipient_addr),
                }]
        elif shares_value_wei + cusd_raw + MAX_SEND_DUST_WEI >= amount_wei:
            # A displayed dollar balance is spendable as one balance. Convert
            # only the cUSD+ shortfall to cUSD, then finish atomically. For an
            # external recipient this also guarantees ONE ceiling-rounded
            # perimeter fee rather than one fee per source leg.
            shortfall = max(0, amount_wei - cusd_raw)
            shares = -(-shortfall * WAD // pps_wad)
            for _ in range(8):
                if shares >= shares_raw:
                    break
                if cp_vault.redeem_gross_usdt_out(
                        shares, pps_wad, oracle_p_wad) >= shortfall:
                    break
                shares += 1
            shares = min(shares, shares_raw)
            predicted = cp_vault.redeem_gross_usdt_out(
                shares, pps_wad, oracle_p_wad)
            if predicted < shortfall:
                return {'success': False, 'error': 'insufficient_balance'}
            if predicted < cp_vault.ONDO_MIN_REDEEM_WEI:
                return {'success': False, 'error': 'redeem_below_minimum'}
            recipient_eligible = (
                recipient_user is not None
                and recipient_business is None
                and is_ondo_eligible(recipient_user)
            )
            internal = recipient_user is not None or recipient_business is not None
            unwrap_call = {
                'to': vault_addr, 'value': '0',
                'data': '0x' + SEL_UNWRAP_TO_CUSD + _uint_word(shares)
                        + _uint_word(shortfall) + _addr_word(sender_addr),
            }
            if recipient_eligible:
                kind = 'send_mixed_wrap_cusd'
                token_type = 'CUSD_PLUS'
                try:
                    mint_oracle_p_wad = cp_vault.current_oracle_price_wad()
                except Exception as exc:  # noqa: BLE001
                    logger.warning('[SEND][BSC] live mint oracle read failed: %s', exc)
                    return {'success': False, 'error': 'quote_unavailable'}
                wrap_min_out = _min_usdy_out(amount_wei, mint_oracle_p_wad)
                token_addr, units, min_out = vault_addr, amount_wei, wrap_min_out
                calls = [unwrap_call, {
                    'to': cusd_addr, 'value': '0',
                    'data': '0x' + SEL_APPROVE + _addr_word(vault_addr)
                            + _uint_word(amount_wei),
                }, {
                    'to': vault_addr, 'value': '0',
                    'data': '0x' + SEL_WRAP_CUSD + _uint_word(amount_wei)
                            + _uint_word(wrap_min_out)
                            + _addr_word(recipient_addr),
                }]
            elif internal:
                kind = 'send_mixed_cusd'
                token_type = 'CUSD'
                token_addr, units, min_out = cusd_addr, amount_wei, None
                calls = [unwrap_call, {
                    'to': cusd_addr, 'value': '0',
                    'data': '0x' + SEL_TRANSFER + _addr_word(recipient_addr)
                            + _uint_word(amount_wei),
                }]
            else:
                from cusd_plus.cusd_vault import preview_redeem_wei
                preview = preview_redeem_wei(amount_wei)
                receipt_gross_wei = preview.gross_wei
                receipt_fee_wei = preview.fee_wei
                receipt_net_wei = preview.net_wei
                receipt_fee_bps = preview.fee_bps
                kind = 'send_mixed_cusd_redeem'
                token_type = 'USDT'
                token_addr, units, min_out = cusd_addr, amount_wei, preview.net_wei
                calls = [unwrap_call, {
                    'to': cusd_addr, 'value': '0',
                    'data': '0x' + SEL_CUSD_REDEEM + _uint_word(amount_wei)
                            + _uint_word(preview.net_wei) + _addr_word(recipient_addr),
                }]
            mixed_meta = {'shares': str(shares), 'unwrap_min': str(shortfall)}
        elif usdt_raw + MAX_SEND_DUST_WEI >= amount_wei:
            # External destinations always receive USDT. If the holder
            # already has raw USDT (notably a pre-cUSD legacy balance), send
            # that output asset directly: there is no conversion to charge.
            # Internal Confío recipients still wait for foreground
            # conversion so friend sends use cUSD/cUSD+ and cannot bypass the
            # entry perimeter.
            if (getattr(settings, 'CUSD_CONVERSION_FEE_ENABLED', False)
                    and (requested == 'CUSD_PLUS'
                         or recipient_user is not None
                         or recipient_business is not None)):
                return {'success': False, 'error': 'conversion_pending'}
            if amount_wei > usdt_raw:
                amount_wei = usdt_raw  # dust-short MAX → the full wallet balance
            if amount_wei <= 0:
                return {'success': False, 'error': 'invalid_amount'}
            kind = 'send_usdt'
            token_type = 'USDT'
            token_addr, units, min_out = USDT_BSC, amount_wei, None
            calls = [{
                'to': USDT_BSC, 'value': '0',
                'data': '0x' + SEL_TRANSFER + _addr_word(recipient_addr) + _uint_word(amount_wei),
            }]
        else:
            return {'success': False, 'error': 'insufficient_balance'}

    recipient_display = ''
    recipient_phone_val = ''
    if recipient_business is not None:
        recipient_display = recipient_business.name
    elif recipient_user is not None:
        recipient_display = _display_name(recipient_user)
        recipient_phone_val = recipient_user.phone_number or ''

    with transaction.atomic():
        if recipient_user is not None or recipient_business is not None:
            locked_recipient = _lock_internal_recipient_account(
                recipient_user,
                recipient_business,
            )
            current_recipient = (
                getattr(locked_recipient, 'bsc_address', None) or ''
            ).lower()
            if current_recipient != recipient_addr:
                return {'success': False, 'error': 'recipient_address_changed'}

        send_tx = SendTransaction.objects.create(
            sender_user=user,
            sender_business=sender_business,
            sender_type='business' if sender_business else 'user',
            sender_display_name=(
                sender_business.name if sender_business else _display_name(user)),
            sender_phone=user.phone_number or '',
            recipient_user=recipient_user,
            recipient_business=recipient_business,
            recipient_type=(
                'business' if recipient_business else
                'user' if recipient_user else 'external'),
            recipient_display_name=recipient_display,
            recipient_phone=recipient_phone_val,
            sender_address=sender_addr,
            recipient_address=recipient_addr,
            amount=amount_usd,
            token_type=token_type,
            memo=(memo or '')[:500],
            status='PENDING',
            idempotency_key=idempotency_key or None,
            bsc_calls_json=json.dumps({
                'calls': calls, 'kind': kind,
                # Canonical intent for the submit-side byte-exact rebuild.
                'token': token_addr, 'recipient': recipient_addr,
                'units': str(units),
                'min_out': (str(min_out) if min_out is not None else None),
                'mixed': mixed_meta,
                'receipt': {
                    'gross': _decimal_wei(receipt_gross_wei),
                    'fee': _decimal_wei(receipt_fee_wei),
                    'net': _decimal_wei(receipt_net_wei),
                    'fee_bps': receipt_fee_bps,
                    'finalized': False,
                },
            }),
        )
    # Unified row arrives via the existing post_save signal
    # (users/signals.py create_unified_transaction_from_send).

    from cusd_plus.sponsor_7702 import intent_id_hex
    return {
        'success': True,
        'send_id': send_tx.internal_id,
        'calls': calls,
        'token_type': token_type,
        'gross_amount': _decimal_wei(receipt_gross_wei),
        'fee_amount': _decimal_wei(receipt_fee_wei),
        'net_amount': _decimal_wei(receipt_net_wei),
        'fee_bps': receipt_fee_bps,
        # The client signs the Execute struct binding THIS intentId (audit
        # 2026-07-31): keccak(kind:send_id), re-derived + verified at submit.
        'intent_id': intent_id_hex(kind, send_tx.id),
    }


def _validate_send_batch(calls: list, send_tx, meta: dict) -> None:
    """Defense in depth on the STORED batch (the client never resends calls
    — it can only sign what prepare stored). Rebuild the ONE expected call
    byte-for-byte from the canonical intent (kind + token + recipient +
    units + min_out) and require the stored call to equal it exactly, so a
    tampered/drifted AMOUNT is caught, not just a tampered recipient (audit
    2026-07-31 P2). The token + recipient are cross-checked against the row
    and the allowlist before the rebuild is trusted."""
    from cusd_plus.sponsor_7702 import (
        PolicyError,
        SEL_APPROVE,
        SEL_CUSD_REDEEM,
        SEL_REDEEM_TO_USDT,
        SEL_TRANSFER,
        SEL_UNWRAP_TO_CUSD,
        SEL_WRAP_CUSD,
        USDT_BSC,
    )

    vault = _vault_address()
    cusd = _cusd_address()
    confio = _confio_token_address()
    kind = meta.get('kind')
    expected_counts = {
        'send_wrap_cusd': 2,
        'send_mixed_wrap_cusd': 3,
        'send_mixed_cusd': 2,
        'send_mixed_cusd_redeem': 2,
    }
    expected_count = expected_counts.get(kind, 1)
    if len(calls) != expected_count:
        raise PolicyError('bad_batch_size')
    if any(int(call.get('value') or 0) != 0 for call in calls):
        raise PolicyError('value_not_allowed')

    call = calls[-1]
    token = (meta.get('token') or '').lower()
    recipient = (meta.get('recipient') or '').lower()
    try:
        units = int(meta.get('units'))
    except (TypeError, ValueError):
        raise PolicyError('bad_calldata')

    # The canonical recipient must be exactly the row's recipient — the row
    # is the authority the notifications and ledger key on.
    if not recipient or recipient != (send_tx.recipient_address or '').lower():
        raise PolicyError('recipient_mismatch')

    # Token allowlist, pinned to the kind (a CONFIO row can only move CONFIO).
    allowed = {
        'send_confio': confio,
        'send_usdt': USDT_BSC,
        'send_cusd_plus': vault,
        'send_redeem': vault,
        'send_unwrap_cusd': vault,
        'send_wrap_cusd': vault,
        'send_cusd': cusd,
        'send_cusd_redeem': cusd,
        'send_mixed_wrap_cusd': vault,
        'send_mixed_cusd': cusd,
        'send_mixed_cusd_redeem': cusd,
    }.get(kind)
    if not allowed or token != allowed:
        raise PolicyError('destination_not_allowed')

    # Rebuild the exact call prepare must have stored.
    if kind.startswith('send_mixed_'):
        mixed = meta.get('mixed') or {}
        try:
            shares = int(mixed['shares'])
            unwrap_min = int(mixed['unwrap_min'])
        except (KeyError, TypeError, ValueError):
            raise PolicyError('bad_calldata')
        expected_unwrap = (
            '0x' + SEL_UNWRAP_TO_CUSD + _uint_word(shares)
            + _uint_word(unwrap_min) + _addr_word(send_tx.sender_address)
        )
        if ((calls[0].get('to') or '').lower() != vault
                or (calls[0].get('data') or '').lower() != expected_unwrap.lower()):
            raise PolicyError('bad_calldata')
        if kind == 'send_mixed_wrap_cusd':
            min_out = int(meta.get('min_out') or 0)
            expected_approve = (
                '0x' + SEL_APPROVE + _addr_word(vault) + _uint_word(units))
            if ((calls[1].get('to') or '').lower() != cusd
                    or (calls[1].get('data') or '').lower() != expected_approve.lower()):
                raise PolicyError('bad_calldata')
            expected_data = ('0x' + SEL_WRAP_CUSD + _uint_word(units)
                             + _uint_word(min_out) + _addr_word(recipient))
        elif kind == 'send_mixed_cusd':
            expected_data = '0x' + SEL_TRANSFER + _addr_word(recipient) + _uint_word(units)
        else:
            min_out = int(meta.get('min_out'))
            expected_data = ('0x' + SEL_CUSD_REDEEM + _uint_word(units)
                             + _uint_word(min_out) + _addr_word(recipient))
    elif kind == 'send_redeem':
        min_out = int(meta.get('min_out'))
        expected_data = ('0x' + SEL_REDEEM_TO_USDT + _uint_word(units)
                         + _uint_word(min_out) + _addr_word(recipient))
    elif kind == 'send_unwrap_cusd':
        min_out = int(meta.get('min_out'))
        expected_data = ('0x' + SEL_UNWRAP_TO_CUSD + _uint_word(units)
                         + _uint_word(min_out) + _addr_word(recipient))
    elif kind == 'send_wrap_cusd':
        min_out = int(meta.get('min_out') or 0)
        expected_data = ('0x' + SEL_WRAP_CUSD + _uint_word(units)
                         + _uint_word(min_out) + _addr_word(recipient))
        expected_approve = ('0x' + SEL_APPROVE + _addr_word(vault)
                            + _uint_word(units))
        if ((calls[0].get('to') or '').lower() != cusd
                or (calls[0].get('data') or '').lower() != expected_approve):
            raise PolicyError('bad_calldata')
    elif kind == 'send_cusd_redeem':
        min_out = int(meta.get('min_out'))
        expected_data = ('0x' + SEL_CUSD_REDEEM + _uint_word(units)
                         + _uint_word(min_out) + _addr_word(recipient))
    else:
        expected_data = '0x' + SEL_TRANSFER + _addr_word(recipient) + _uint_word(units)

    if (call.get('to') or '').lower() != token:
        raise PolicyError('destination_not_allowed')
    if (call.get('data') or '').lower() != expected_data:
        raise PolicyError('bad_calldata')


def submit_bsc_send(user, send_tx, nonce, deadline, intent_signature,
                    authorization=None) -> dict:
    from cusd_plus import sponsor_7702

    if send_tx.sender_user_id != user.id:
        return {'success': False, 'error': 'not_your_send'}
    if send_tx.status != 'PENDING' or not send_tx.bsc_calls_json:
        return {'success': False, 'error': 'send_not_pending'}

    sender_addr = (send_tx.sender_address or '').lower()
    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))

    now = int(time.time())
    if not (now + 30 <= int(deadline) <= now + 1800):
        return {'success': False, 'error': 'bad_deadline'}

    meta = json.loads(send_tx.bsc_calls_json or '{}')
    kind = meta.get('kind') or 'send_usdt'
    calls = meta.get('calls') or []

    try:
        _validate_send_batch(calls, send_tx, meta)

        intent_id = sponsor_7702.intent_id_for(kind, send_tx.id)
        digest = sponsor_7702.intent_digest(
            calls, int(nonce), int(deadline), sender_addr, chain_id, intent_id)
        signer = sponsor_7702.recover_intent_signer(digest, intent_signature)
        if signer != sender_addr:
            return {'success': False, 'error': 'bad_intent_signature'}

        auth_dict = None
        if not sponsor_7702.is_delegated(sender_addr):
            if authorization is None:
                return {'success': False, 'error': 'authorization_required',
                        'authorization_required': True}
            auth_dict = sponsor_7702.normalize_and_validate_authorization(
                authorization, sender_addr, chain_id)

        tx_hash, batch = sponsor_7702.send_sponsored_batch(
            user, sender_addr, calls, int(nonce), int(deadline),
            intent_signature, auth_dict, kind, source_id=send_tx.id)
    except sponsor_7702.ExistingSponsoredBatch as exc:
        existing = exc.batch
        if (exc.reason != 'source_id'
                or existing.source_id != send_tx.id
                or existing.user_bsc_address.lower() != sender_addr
                or not sponsor_7702.batch_matches_calls(existing, kind, calls)):
            return {'success': False, 'error': 'send_already_in_flight'}
        # The losing retry adopts the durable winner instead of broadcasting
        # a fresh-nonce duplicate. Common code below stamps the domain row and
        # re-enqueues its idempotent confirmer.
        tx_hash, batch = existing.tx_hash, existing
    except sponsor_7702.PolicyError as exc:
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        if exc.code == 'simulation_reverted':
            # The STORED batch cannot execute against current chain state, and
            # nothing re-submits this row — the client always re-prepares a new
            # one. Leaving it PENDING strands a send in the user's history
            # forever (three such rows on 2026-08-01). Terminal, not retryable.
            #
            # But ONLY if nothing was broadcast. A concurrent or retried submit
            # can reach this handler after a sibling call already signed and
            # sent a batch for the same row; marking FAILED there would make
            # confirm_bsc_send refuse to settle a batch that DID land, and the
            # client would send again (audit 2026-08-01). The conditional
            # UPDATE is the claim: it only fires while the row is still
            # PENDING with no hash, and a batch row is the other witness.
            from blockchain.models import SponsoredBatch  # noqa: PLC0415
            broadcast = SponsoredBatch.objects.filter(source_id=send_tx.id).exists()
            if not broadcast:
                claimed = SendTransaction.objects.filter(
                    pk=send_tx.pk, status='PENDING', transaction_hash='',
                ).update(status='FAILED', error_message='simulation_reverted',
                         updated_at=timezone.now())
                if not claimed:
                    logger.warning(
                        '[SEND][BSC] %s advanced while simulating — left alone',
                        send_tx.internal_id)
            else:
                logger.error(
                    '[SEND][BSC] %s simulation reverted but a batch exists — '
                    'NOT failing the row; the receipt task owns it',
                    send_tx.internal_id)
        return {'success': False, 'error': exc.code}
    except Exception as exc:  # noqa: BLE001 — surface node rejections honestly
        logger.exception('[SEND][BSC] sponsored send failed for %s', send_tx.internal_id)
        return {'success': False, 'error': str(exc)[:200]}

    send_tx.transaction_hash = tx_hash
    send_tx.status = 'SUBMITTED'
    send_tx.save(update_fields=['transaction_hash', 'status', 'updated_at'])

    # Balance caches just changed for the sender (and the recipient, for
    # internal sends) — drop the fresh-read keys.
    try:
        from cusd_plus.vault import invalidate_position
        invalidate_position(sender_addr)
        invalidate_position(send_tx.recipient_address or '')
    except Exception:  # noqa: BLE001
        pass

    from .tasks import confirm_bsc_send
    # 4s: just behind the batch receipt check (3s), so the domain row flips
    # to CONFIRMED on the first pass in the common case rather than waiting
    # out a retry — this delay IS how long the user sees 'Confirmando…'.
    confirm_bsc_send.apply_async(args=[send_tx.id, batch.id], countdown=4)

    # executed_early: the sponsor already SAW this execute() in a receipt, so
    # the client can stop spinning without a poll of its own. None = not yet
    # observed (client falls back to polling); it is never a settlement claim
    # — confirm_bsc_send still owns the money row.
    return {'success': True, 'transaction_hash': tx_hash,
            'execution': getattr(batch, 'executed_early', None)}
