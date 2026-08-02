"""
BSC payroll flow — ConfioPayrollVault (per-business cUSD+ escrow with
delegate-signed payouts). Phase 2 W3 of the cUSD phase-out.

Why this rail is shaped differently from send/pay: under EIP-7702 only the
business key can sign for the business EOA, so an employee-delegate cannot
author a business batch. The delegate model lives ON-CHAIN instead — the
business parks cUSD+ shares in ConfioPayrollVault and allowlists delegate
EVM addresses; each payout is an EIP-712 signature by the delegate (their
OWN personal wallet key) which ANY caller may execute. Confío's KMS sponsor
is that caller (plain type-2 tx, not 7702), paying gas.

Three surfaces:

  admin ops (business EOA, 7702 sponsored batches like every other flow):
      fund          [cusdPlus.approve(payroll, shares), payroll.deposit(shares)]
      withdraw      [payroll.withdraw(shares, business)]   — NEVER blocked
      set_delegate  [payroll.setDelegate(delegateAddr, allowed)]
    No stored batch: submit rebuilds the calls from INTEGER params (shares,
    delegate address), so the batch is byte-exact by construction and the
    server never trusts client calldata.

  payout (two-step, server-authoritative like send/pay):
      prepare  gates + branch choice, stores the exact Payout struct on the
               PayrollItem, returns the EIP-712 digest for the delegate to
               sign with their own key
      submit   recover signer from the STORED struct, double-check the
               on-chain allowlist, broadcast payout() as a plain KMS tx
               under the shared sponsor nonce lock

Recipient rails mirror send/bsc_flow.py: eligible → shares transfer;
ineligible/unknown → vault.redeemToUsdt inside payout() (atomic USDT
delivery — exits never geo-gated).
"""
import json
import logging
import time
from decimal import Decimal

from django.conf import settings
from eth_abi import encode as abi_encode
from eth_utils import keccak

logger = logging.getLogger(__name__)

WAD = 10 ** 18
REDEEM_MIN_OUT_BPS = 9_950  # same drift tolerance as send/bsc_flow.py
PAYOUT_DEADLINE_S = 900

# Ondo's Instant Manager refuses redemptions under $1.
ONDO_MIN_REDEEM_WEI = 10 ** 18

# ── EIP-712 (canonical strings shared with ConfioPayrollVault.sol and the
#    client signer — parity anchored in test_payout_digest_parity + the
#    contract's payoutDigest() view; never change one alone) ──────────────
P_DOMAIN_TYPEHASH = keccak(
    text='EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)')
P_NAME_HASH = keccak(text='ConfioPayrollVault')
P_VERSION_HASH = keccak(text='1')
PAYOUT_TYPEHASH = keccak(
    text='Payout(address business,address recipient,uint256 netShares,'
         'uint256 feeShares,bool redeemToUsdt,uint256 minUsdtOut,'
         'bytes32 itemId,uint256 deadline)')


def _sel(sig: str) -> str:
    return keccak(text=sig)[:4].hex()


SEL_PAYROLL_DEPOSIT = _sel('deposit(uint256)')
SEL_PAYROLL_WITHDRAW = _sel('withdraw(uint256,address)')
SEL_PAYROLL_SET_DELEGATE = _sel('setDelegate(address,bool)')
SEL_PAYOUT = _sel(
    'payout((address,address,uint256,uint256,bool,uint256,bytes32,uint256),bytes)')
SEL_ESCROW_SHARES = _sel('escrowShares(address)')
SEL_IS_DELEGATE = _sel('isDelegate(address,address)')

# Fork-calibrated (ConfioPayrollVault.fork.t.sol: transfer payout 147k,
# redeem payout 566k) + the sponsor-spend headroom rule.
GAS_PAYOUT_TRANSFER = 350_000
GAS_PAYOUT_REDEEM = 950_000


def _payroll_address() -> str:
    return (getattr(settings, 'BSC_PAYROLL_VAULT_ADDRESS', '') or '').lower()


def _vault_address() -> str:
    return (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()


def _uint_word(v: int) -> str:
    return format(int(v), 'x').rjust(64, '0')


def _addr_word(addr: str) -> str:
    return addr.lower().replace('0x', '').rjust(64, '0')


def payout_digest(p: dict, chain_id: int) -> bytes:
    """EIP-712 digest exactly as ConfioPayrollVault.payoutDigest computes it."""
    struct_hash = keccak(abi_encode(
        ['bytes32', 'address', 'address', 'uint256', 'uint256', 'bool',
         'uint256', 'bytes32', 'uint256'],
        [PAYOUT_TYPEHASH, p['business'], p['recipient'], int(p['net_shares']),
         int(p['fee_shares']), bool(p['redeem_to_usdt']), int(p['min_usdt_out']),
         bytes.fromhex(p['item_id'][2:]), int(p['deadline'])],
    ))
    domain_separator = keccak(abi_encode(
        ['bytes32', 'bytes32', 'bytes32', 'uint256', 'address'],
        [P_DOMAIN_TYPEHASH, P_NAME_HASH, P_VERSION_HASH, chain_id, _payroll_address()],
    ))
    return keccak(b'\x19\x01' + domain_separator + struct_hash)


def payout_calldata(p: dict, signature_hex: str) -> str:
    """ABI-encode ConfioPayrollVault.payout(Payout, bytes)."""
    encoded = abi_encode(
        ['(address,address,uint256,uint256,bool,uint256,bytes32,uint256)', 'bytes'],
        [(p['business'], p['recipient'], int(p['net_shares']), int(p['fee_shares']),
          bool(p['redeem_to_usdt']), int(p['min_usdt_out']),
          bytes.fromhex(p['item_id'][2:]), int(p['deadline'])),
         bytes.fromhex(signature_hex.replace('0x', ''))],
    )
    return '0x' + SEL_PAYOUT + encoded.hex()


def item_id_bytes32(internal_id: str) -> str:
    """Deterministic bytes32 for a PayrollItem — keccak of the internal id
    (uniform width regardless of id format; the contract replay-keys on it
    per business)."""
    return '0x' + keccak(text=internal_id).hex()


def _eth_call(to: str, data: str) -> str:
    from cusd_plus.sponsor_7702 import _rpc
    return _rpc('eth_call', [{'to': to, 'data': data}, 'latest'])


def escrow_shares_raw(business_addr: str) -> int:
    out = _eth_call(_payroll_address(), '0x' + SEL_ESCROW_SHARES + _addr_word(business_addr))
    return int(out, 16) if out and out != '0x' else 0


def is_onchain_delegate(business_addr: str, delegate_addr: str) -> bool:
    out = _eth_call(
        _payroll_address(),
        '0x' + SEL_IS_DELEGATE + _addr_word(business_addr) + _addr_word(delegate_addr))
    return bool(int(out, 16)) if out and out != '0x' else False


# ── Shared context resolution ────────────────────────────────────────────

def _business_context(user, jwt_ctx):
    """Resolve (business, business_account, business_addr, signer_addr,
    error). signer_addr is the EXECUTING USER's own personal EVM address —
    the key that will sign the payout digest."""
    from users.models import Account

    if jwt_ctx.get('account_type') != 'business' or not jwt_ctx.get('business_id'):
        return None, None, None, None, 'business_context_required'
    business_account = Account.objects.filter(
        business_id=jwt_ctx['business_id'], account_type='business',
        account_index=jwt_ctx.get('account_index', 0),
        deleted_at__isnull=True).select_related('business').first()
    if not business_account:
        return None, None, None, None, 'business_account_not_found'
    business_addr = (business_account.bsc_address or '').lower()
    if not business_addr:
        return None, None, None, None, 'business_no_bsc_address'
    personal = user.accounts.filter(
        account_type='personal', account_index=0, deleted_at__isnull=True).first()
    signer_addr = ((getattr(personal, 'bsc_address', None) or '') or '').lower()
    return business_account.business, business_account, business_addr, signer_addr, None


def _flags_error():
    if not getattr(settings, 'BSC_PAYROLL_ENABLED', False):
        return 'bsc_payroll_disabled'
    if not _payroll_address():
        return 'payroll_vault_not_configured'
    if not _vault_address():
        return 'vault_not_configured'
    return None


# ── Admin ops (business EOA via 7702) ────────────────────────────────────

def build_admin_calls(action: str, shares: int = 0, delegate_addr: str = '',
                      allowed: bool = True, business_addr: str = '') -> list:
    """Canonical batches for the three business ops. Deterministic from
    integer/address params — submit rebuilds and the signature must match."""
    payroll = _payroll_address()
    vault = _vault_address()
    if action == 'fund':
        return [
            {'to': vault, 'value': '0',
             'data': '0x' + '095ea7b3' + _addr_word(payroll) + _uint_word(shares)},
            {'to': payroll, 'value': '0',
             'data': '0x' + SEL_PAYROLL_DEPOSIT + _uint_word(shares)},
        ]
    if action == 'withdraw':
        # Destination pinned to the business's own EOA — a compromised
        # session cannot exfiltrate the float elsewhere.
        return [{'to': payroll, 'value': '0',
                 'data': '0x' + SEL_PAYROLL_WITHDRAW + _uint_word(shares)
                         + _addr_word(business_addr)}]
    if action == 'set_delegate':
        return [{'to': payroll, 'value': '0',
                 'data': '0x' + SEL_PAYROLL_SET_DELEGATE + _addr_word(delegate_addr)
                         + _uint_word(1 if allowed else 0)}]
    raise ValueError(f'unknown admin action {action}')


def prepare_bsc_payroll_admin(user, jwt_ctx, action: str, amount=None,
                              delegate_user_id=None, allowed: bool = True) -> dict:
    from cusd_plus import vault as cp_vault
    from django.contrib.auth import get_user_model

    err = _flags_error()
    if err and action != 'withdraw':
        # Withdraw must survive the kill switch (exits are never gated) as
        # long as the vault addresses exist to talk to.
        return {'success': False, 'error': err}
    if action == 'withdraw' and not _payroll_address():
        return {'success': False, 'error': 'payroll_vault_not_configured'}

    business, business_account, business_addr, _signer, err = _business_context(user, jwt_ctx)
    if err:
        return {'success': False, 'error': err}

    if action in ('fund', 'withdraw'):
        try:
            amount_usd = Decimal(str(amount))
        except Exception:  # noqa: BLE001
            return {'success': False, 'error': 'invalid_amount'}
        if amount_usd <= 0:
            return {'success': False, 'error': 'invalid_amount'}
        try:
            pps_wad = cp_vault.p_plus_wad()
        except Exception as exc:  # noqa: BLE001
            logger.warning('[PAYROLL][BSC] pps read failed: %s', exc)
            return {'success': False, 'error': 'balance_unavailable'}
        shares = (int(amount_usd * WAD) * WAD) // pps_wad
        if shares <= 0:
            return {'success': False, 'error': 'invalid_amount'}
        if action == 'fund':
            held = cp_vault.erc20_balance_raw(_vault_address(), business_addr)
            if held < shares:
                return {'success': False, 'error': 'insufficient_balance'}
        else:
            if escrow_shares_raw(business_addr) < shares:
                return {'success': False, 'error': 'insufficient_escrow'}
        calls = build_admin_calls(action, shares=shares, business_addr=business_addr)
        from cusd_plus.sponsor_7702 import intent_id_hex
        return {'success': True, 'calls': calls, 'shares': str(shares),
                'intent_id': intent_id_hex(f'payroll_{action}', business_account.id)}

    if action == 'set_delegate':
        User = get_user_model()
        delegate_user = User.objects.filter(id=delegate_user_id).first()
        if not delegate_user:
            return {'success': False, 'error': 'delegate_not_found'}
        d_account = delegate_user.accounts.filter(
            account_type='personal', account_index=0, deleted_at__isnull=True).first()
        delegate_addr = ((getattr(d_account, 'bsc_address', None) or '') or '').lower()
        if not delegate_addr:
            return {'success': False, 'error': 'delegate_no_bsc_address'}
        calls = build_admin_calls('set_delegate', delegate_addr=delegate_addr,
                                  allowed=allowed)
        from cusd_plus.sponsor_7702 import intent_id_hex
        return {'success': True, 'calls': calls, 'delegate_address': delegate_addr,
                'intent_id': intent_id_hex(f'payroll_{action}', business_account.id)}

    return {'success': False, 'error': 'unknown_action'}


def submit_bsc_payroll_admin(user, jwt_ctx, action: str, nonce, deadline,
                             intent_signature, authorization=None,
                             shares=None, delegate_address='',
                             allowed: bool = True) -> dict:
    """Rebuild the canonical batch from integer params and relay it. The
    signature only verifies against the server's own bytes."""
    from cusd_plus import sponsor_7702

    err = _flags_error()
    if err and action != 'withdraw':
        return {'success': False, 'error': err}

    business, business_account, business_addr, _signer, err = _business_context(user, jwt_ctx)
    if err:
        return {'success': False, 'error': err}

    try:
        if action in ('fund', 'withdraw'):
            shares_int = int(shares or 0)
            if shares_int <= 0:
                return {'success': False, 'error': 'invalid_amount'}
            calls = build_admin_calls(action, shares=shares_int,
                                      business_addr=business_addr)
        elif action == 'set_delegate':
            delegate_addr = (delegate_address or '').lower()
            from users.models import Account
            if not Account.objects.filter(
                    bsc_address__iexact=delegate_addr,
                    deleted_at__isnull=True).exists():
                # Only addresses of real Confío accounts can enter the
                # allowlist through this rail.
                return {'success': False, 'error': 'delegate_not_found'}
            calls = build_admin_calls('set_delegate', delegate_addr=delegate_addr,
                                      allowed=allowed)
        else:
            return {'success': False, 'error': 'unknown_action'}

        now = int(time.time())
        if not (now + 30 <= int(deadline) <= now + 1800):
            return {'success': False, 'error': 'bad_deadline'}

        chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))
        intent_id = sponsor_7702.intent_id_for(f'payroll_{action}', business_account.id)
        digest = sponsor_7702.intent_digest(
            calls, int(nonce), int(deadline), business_addr, chain_id, intent_id)
        signer = sponsor_7702.recover_intent_signer(digest, intent_signature)
        if signer != business_addr:
            return {'success': False, 'error': 'bad_intent_signature'}

        auth_dict = None
        if not sponsor_7702.is_delegated(business_addr):
            if authorization is None:
                return {'success': False, 'error': 'authorization_required',
                        'authorization_required': True}
            auth_dict = sponsor_7702.normalize_and_validate_authorization(
                authorization, business_addr, chain_id)

        tx_hash, batch = sponsor_7702.send_sponsored_batch(
            user, business_addr, calls, int(nonce), int(deadline),
            intent_signature, auth_dict, f'payroll_{action}', source_id=business_account.id)
    except sponsor_7702.PolicyError as exc:
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        return {'success': False, 'error': exc.code}
    except Exception as exc:  # noqa: BLE001
        logger.exception('[PAYROLL][BSC] admin %s failed', action)
        return {'success': False, 'error': str(exc)[:200]}

    try:
        from cusd_plus.vault import invalidate_position
        invalidate_position(business_addr)
    except Exception:  # noqa: BLE001
        pass
    return {'success': True, 'transaction_hash': tx_hash}


# ── Payout (delegate-signed, sponsor-broadcast) ──────────────────────────

def _notify_recipient_needs_app(recipient_user, business) -> None:
    try:
        from notifications import utils as notif_utils
        from notifications.models import NotificationType as NotifType
        notif_utils.create_notification(
            user=recipient_user,
            account=None,
            business=None,
            notification_type=NotifType.PAYROLL_RECEIVED,
            title='Tu pago te está esperando',
            message=(
                f'{business.name} quiere pagarte tu nómina. '
                'Abre Confío para activar tu cuenta y poder recibirla.'
            ),
            data={'transaction_type': 'payroll_blocked', 'reason': 'no_bsc_address'},
        )
    except Exception:  # noqa: BLE001
        logger.exception('payroll recipient-needs-app notification failed')


def prepare_bsc_payroll_payout(user, jwt_ctx, item) -> dict:
    from cusd_plus import vault as cp_vault
    from cusd_plus.eligibility import is_ondo_eligible

    err = _flags_error()
    if err:
        return {'success': False, 'error': err}

    business, business_account, business_addr, signer_addr, err = _business_context(user, jwt_ctx)
    if err:
        return {'success': False, 'error': err}
    if item.run.business_id != business.id:
        return {'success': False, 'error': 'not_your_payroll'}
    if item.status not in ('PENDING', 'PREPARED', 'FAILED'):
        return {'success': False, 'error': 'item_not_pending'}
    if not signer_addr:
        return {'success': False, 'error': 'no_bsc_address'}

    recipient_addr = ((item.recipient_account.bsc_address or '') or '').lower()
    if not recipient_addr:
        _notify_recipient_needs_app(item.recipient_user, business)
        return {'success': False, 'error': 'recipient_no_bsc_address'}

    # The signature only helps if the contract will accept it: allowlist
    # membership is checked here (cheap read) AND enforced on-chain.
    if signer_addr != business_addr and not is_onchain_delegate(business_addr, signer_addr):
        return {'success': False, 'error': 'not_onchain_delegate'}

    try:
        pps_wad = cp_vault.p_plus_wad()
    except Exception as exc:  # noqa: BLE001
        logger.warning('[PAYROLL][BSC] pps read failed: %s', exc)
        return {'success': False, 'error': 'balance_unavailable'}

    net_wei = int(Decimal(item.net_amount) * WAD)
    fee_wei = int(Decimal(item.fee_amount or 0) * WAD)
    if net_wei <= 0:
        return {'success': False, 'error': 'invalid_amount'}
    net_shares = (net_wei * WAD) // pps_wad
    fee_shares = (fee_wei * WAD) // pps_wad
    if net_shares <= 0:
        return {'success': False, 'error': 'invalid_amount'}

    if escrow_shares_raw(business_addr) < net_shares + fee_shares:
        return {'success': False, 'error': 'insufficient_escrow'}

    # Schedule and cap were decorative on this rail: neither BSC prepare nor
    # submit consulted them and the contract carries no window or cap state.
    # Enforced here so the normal path honours what the business configured.
    #
    # Honest about its reach: the payout authorization we sign is valid for
    # PAYOUT_DEADLINE_S, so a delegate holding one could call the contract
    # directly inside that window regardless. Real enforcement would need the
    # cap in ConfioPayrollVault; this is the guardrail, not the lock.
    from django.utils import timezone
    run = item.run
    scheduled_at = getattr(run, 'scheduled_at', None)
    if scheduled_at and scheduled_at > timezone.now():
        return {'success': False, 'error': 'run_not_due'}
    cap_amount = getattr(run, 'cap_amount', None)
    if cap_amount:
        from django.db.models import Sum
        paid = run.items.filter(
            status__in=('SUBMITTED', 'CONFIRMED'), deleted_at__isnull=True,
        ).exclude(id=item.id).aggregate(t=Sum('gross_amount'))['t'] or Decimal('0')
        if paid + Decimal(item.gross_amount or 0) > Decimal(cap_amount):
            logger.warning('[PAYROLL][BSC] run %s would exceed its cap %s (already %s)',
                           run.id, cap_amount, paid)
            return {'success': False, 'error': 'run_cap_exceeded'}

    recipient_eligible = is_ondo_eligible(item.recipient_user)
    redeem = not recipient_eligible
    # Ondo refuses redemptions under $1. Unlike a payment there is no change
    # to leave behind — the employee is owed an exact wage — so catch it here
    # rather than letting the sponsored transaction revert on chain, burn gas
    # and mark the item FAILED.
    if redeem and net_wei < ONDO_MIN_REDEEM_WEI:
        logger.info('[PAYROLL][BSC] %s: %s wage to an Ondo-ineligible recipient is '
                    'below the $1 redemption floor', item.internal_id, item.net_amount)
        return {'success': False, 'error': 'wage_below_redeem_minimum'}
    min_usdt_out = (net_wei * REDEEM_MIN_OUT_BPS) // 10_000 if redeem else 0

    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))
    payout = {
        'business': business_addr,
        'recipient': recipient_addr,
        'net_shares': str(net_shares),
        'fee_shares': str(fee_shares),
        'redeem_to_usdt': redeem,
        'min_usdt_out': str(min_usdt_out),
        'item_id': item_id_bytes32(item.internal_id),
        'deadline': int(time.time()) + PAYOUT_DEADLINE_S,
        'expected_signer': signer_addr,
        'chain_id': chain_id,
    }
    digest = payout_digest(payout, chain_id)

    data = dict(item.blockchain_data or {})
    data['bsc_payout'] = payout
    item.blockchain_data = data
    item.token_type = 'CUSD_PLUS' if not redeem else 'USDT'
    item.status = 'PREPARED'
    item.save(update_fields=['blockchain_data', 'token_type', 'status', 'updated_at'])

    return {
        'success': True,
        'digest': '0x' + digest.hex(),
        'deadline': payout['deadline'],
        'redeem_to_usdt': redeem,
    }


def submit_bsc_payroll_payout(user, jwt_ctx, item, signature: str) -> dict:
    from cusd_plus import sponsor_7702
    from cusd_plus.sponsor_7702 import (
        PolicyError,
        _rpc,
        acquire_sponsor_nonce_lock,
        release_sponsor_nonce_lock,
    )
    from blockchain.models import SponsoredBatch

    err = _flags_error()
    if err:
        return {'success': False, 'error': err}

    business, business_account, business_addr, _signer, err = _business_context(user, jwt_ctx)
    if err:
        return {'success': False, 'error': err}
    if item.run.business_id != business.id:
        return {'success': False, 'error': 'not_your_payroll'}
    if item.status != 'PREPARED':
        return {'success': False, 'error': 'item_not_prepared'}

    payout = (item.blockchain_data or {}).get('bsc_payout')
    if not payout or payout.get('business') != business_addr:
        return {'success': False, 'error': 'payout_not_prepared'}
    if int(payout['deadline']) < int(time.time()) + 15:
        return {'success': False, 'error': 'payout_expired'}

    chain_id = int(payout.get('chain_id') or getattr(settings, 'BSC_CHAIN_ID', 56))
    digest = payout_digest(payout, chain_id)
    signer = sponsor_7702.recover_intent_signer(digest, signature)
    if not signer or signer != payout.get('expected_signer'):
        return {'success': False, 'error': 'bad_payout_signature'}

    calldata = payout_calldata(payout, signature)
    payroll_addr = _payroll_address()

    from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
    signer_kms = get_bsc_sponsor_signer_from_settings()
    sponsor = signer_kms.address

    # Pre-flight the exact call before spending sponsor gas (bad sig,
    # consumed item, thin escrow all surface here).
    try:
        _rpc('eth_call', [{'from': sponsor, 'to': payroll_addr, 'data': calldata}, 'latest'])
    except Exception as exc:  # noqa: BLE001
        logger.warning('[PAYROLL][BSC] payout simulation reverted for %s: %s',
                       item.internal_id, exc)
        return {'success': False, 'error': 'simulation_reverted'}

    gas = GAS_PAYOUT_REDEEM if payout['redeem_to_usdt'] else GAS_PAYOUT_TRANSFER
    gas_price = max(int(_rpc('eth_gasPrice', []), 16),
                    int(getattr(settings, 'CUSD_PLUS_GAS_PRICE_FLOOR_WEI', 100_000_000)))
    price_cap = int(getattr(settings, 'CUSD_PLUS_7702_MAX_GAS_PRICE_WEI', 5_000_000_000))
    if gas_price > price_cap:
        return {'success': False, 'error': 'gas_price_too_high'}
    fee_per_gas = min((gas_price * 12) // 10, price_cap)

    if not acquire_sponsor_nonce_lock():
        return {'success': False, 'error': 'sponsor_busy'}
    try:
        sponsor_nonce = int(_rpc('eth_getTransactionCount', [sponsor, 'pending']), 16)
        sponsor_balance = int(_rpc('eth_getBalance', [sponsor, 'latest']), 16)
        if sponsor_balance < (gas * fee_per_gas * 11) // 10:
            logger.error('sponsor BNB too low for payroll payout — refill needed')
            return {'success': False, 'error': 'sponsor_balance_low'}
        from eth_utils import to_checksum_address
        tx = {
            'type': 2,
            'chainId': chain_id,
            'nonce': sponsor_nonce,
            'maxPriorityFeePerGas': fee_per_gas,
            'maxFeePerGas': fee_per_gas,
            'gas': gas,
            'to': to_checksum_address(payroll_addr),
            'value': 0,
            'data': calldata,
            'accessList': [],
        }
        raw, tx_hash = signer_kms.sign_typed_transaction(tx)
        # Durable BEFORE broadcast (audit 2026-07-31 P1-2). plain-KMS payout,
        # so delegate_nonce=None; the receipt task proves it via the
        # contract's own PaidOut log + finality. On-chain (business,itemId)
        # replay already blocks a double-payout, so a lost-then-retried row
        # cannot double-spend.
        batch = SponsoredBatch.objects.create(
            user=user,
            user_bsc_address=business_addr,
            kind='payroll_payout',
            source_id=item.id,
            num_calls=1,
            calls_json=json.dumps([{'to': payroll_addr, 'value': '0', 'data': calldata}]),
            tx_hash=tx_hash,
            gas_limit=gas,
            max_fee_wei=str(fee_per_gas),
            status='signed',
        )
        # Keep the node's answer: `sent` is read below and was never assigned,
        # so every successful payout raised NameError AFTER the money moved —
        # item stuck at PREPARED with no hash, confirmer refusing it (it takes
        # only SUBMITTED), run never completing, and the scanner recording the
        # salary as a generic external deposit because no PayrollItem carried
        # the hash to prove ownership. For a correctly signed transaction this
        # equals tx_hash; the fallback covers a node that answers with null.
        sent = _rpc('eth_sendRawTransaction', [raw])
        batch.status = 'sent'
        batch.save(update_fields=['status', 'updated_at'])
    except Exception as exc:  # noqa: BLE001
        logger.exception('[PAYROLL][BSC] payout broadcast failed for %s', item.internal_id)
        return {'success': False, 'error': str(exc)[:200]}
    finally:
        release_sponsor_nonce_lock()

    # RECORD BEFORE SCHEDULING. Anything between the broadcast and this save
    # can fail — a broker outage on apply_async, the process dying — and the
    # money has already moved. The item would stay PREPARED with no hash and
    # no recipient_address, which strands it permanently: the reconciler only
    # sweeps batches still in 'signed', the confirmer refuses anything not
    # SUBMITTED, and the scanner then books the wage as an external deposit
    # because nothing carries the hash that proves payroll owns it.
    #
    # The locally computed hash is AUTHORITATIVE: it is derived from the
    # signed payload, while the node's answer is only a claim. A node
    # returning something else must not desync item.transaction_hash from
    # batch.tx_hash, which would strand the confirmer forever.
    from django.utils import timezone
    if sent and str(sent).lower() != str(tx_hash).lower():
        logger.error(
            '[PAYROLL][BSC] node returned %s for a transaction signed as %s — '
            'keeping the signed hash', sent, tx_hash)
    item.transaction_hash = tx_hash
    item.status = 'SUBMITTED'
    item.executed_by_user = user
    item.executed_at = timezone.now()
    item.recipient_address = (payout.get('recipient') or '').lower()
    item.save(update_fields=['transaction_hash', 'status', 'executed_by_user',
                             'executed_at', 'recipient_address', 'updated_at'])

    from cusd_plus.tasks import check_sponsored_batch_receipt
    check_sponsored_batch_receipt.apply_async(args=[batch.id], countdown=6)

    try:
        from cusd_plus.vault import invalidate_position
        invalidate_position(payout['recipient'])
    except Exception:  # noqa: BLE001
        pass

    from .tasks import confirm_bsc_payroll_payout
    confirm_bsc_payroll_payout.apply_async(args=[item.id, batch.id], countdown=8)
    return {'success': True, 'transaction_hash': tx_hash}
