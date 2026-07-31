"""
BSC invoice payment flow — via ConfioPayContract (Phase 2 of the cUSD
phase-out; presale/send bsc_flow shape).

Design (Julian, 2026-07-31, superseding the 07-30 contract-less batch):
fees sit IN each contract. A payment is one sponsored 7702 batch, atomic
under ConfioBatchDelegate.execute():

    [ token.approve(payContract, gross),
      payContract.pay(invoiceId, token, gross, merchant) ]

The CONTRACT computes fee = ceil(gross * 0.9%) (same ceiling-division
semantics as the Algorand builder and payment_fee_wei below), sends
net = gross − fee to the merchant, accrues the fee in itself per token
(owner Safe collects), and replay-guards the invoiceId on-chain. `token`
follows the payer's funding source: cUSD+ vault shares (converted at the
live share price) or raw USDT.

Merchant token note (v1 divergence from the send flow's redeem-to-
ineligible rule): the merchant receives the SAME token the payer spent.
Holding cUSD+ is compliant secondary-market acquisition regardless of geo
(the deemed-representations model; only MINTING is geo-gated), a business
"geo" is ill-defined (eligibility is a personal-phone attribute), and the
merchant's account screen already shows and redeems vault balances.
"""
import json
import logging
import time
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

WAD = 10 ** 18
FEE_BPS = 90
BPS = 10_000


def _uint_word(v: int) -> str:
    return format(int(v), 'x').rjust(64, '0')


def _addr_word(addr: str) -> str:
    return addr.lower().replace('0x', '').rjust(64, '0')


def _vault_address() -> str:
    return (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()


def _pay_contract() -> str:
    return (getattr(settings, 'BSC_PAY_CONTRACT_ADDRESS', '') or '').lower()


def invoice_id_bytes32(internal_id: str) -> str:
    """Deterministic bytes32 replay key for an invoice (uniform width;
    the contract stores invoicePaid[id])."""
    from eth_utils import keccak
    return '0x' + keccak(text=internal_id).hex()


def payment_fee_wei(gross_wei: int) -> int:
    """0.9% ceiling division — wei mirror of the Algorand builder's
    (amount*90 + 9999) // 10000 (payment_transaction_builder.py)."""
    return (gross_wei * FEE_BPS + BPS - 1) // BPS


def _notify_merchant_needs_app(invoice, payer_user) -> None:
    """Business registration is OWNER-only (users/schema.py guard), so the
    nudge goes to the invoice creator — in practice the owner or cashier
    who can relay it. Opening the app as the owner IS the registration."""
    try:
        from notifications import utils as notif_utils
        from notifications.models import NotificationType as NotifType
        notif_utils.create_notification(
            user=invoice.created_by_user,
            account=invoice.merchant_account,
            business=invoice.merchant_business,
            notification_type=NotifType.PAYMENT_RECEIVED,
            title='Un cliente quiere pagarte',
            message=(
                'Alguien intentó pagarte con dólares digitales. El dueño del '
                'negocio debe abrir Confío para activar los cobros.'
            ),
            data={'transaction_type': 'payment_blocked', 'reason': 'no_bsc_address'},
        )
    except Exception:  # noqa: BLE001
        logger.exception('merchant-needs-app notification failed')


def prepare_bsc_payment(user, jwt_ctx, invoice, idempotency_key: str = '') -> dict:
    from cusd_plus import vault as cp_vault
    from cusd_plus.sponsor_7702 import SEL_APPROVE, SEL_PAY, USDT_BSC
    from users.models import Account
    from .models import PaymentTransaction

    vault_addr = _vault_address()
    pay_contract = _pay_contract()
    if not vault_addr:
        return {'success': False, 'error': 'vault_not_configured'}
    if not pay_contract:
        return {'success': False, 'error': 'pay_contract_not_configured'}
    if not getattr(settings, 'BSC_PAY_ENABLED', False):
        return {'success': False, 'error': 'bsc_pay_disabled'}

    # Invoice gates (the QR is never trusted — this row is).
    if invoice.status != 'PENDING':
        return {'success': False, 'error': 'invoice_not_pending'}
    if getattr(invoice, 'is_expired', False):
        return {'success': False, 'error': 'invoice_expired'}
    if (invoice.token_type or '').upper() != 'CUSD':
        # BSC pays dollar invoices; CONFIO invoices stay on Algorand.
        return {'success': False, 'error': 'invoice_not_dollar'}

    # Payer account from the JWT context only.
    if jwt_ctx['account_type'] == 'business' and jwt_ctx.get('business_id'):
        if jwt_ctx['business_id'] == invoice.merchant_business_id:
            return {'success': False, 'error': 'self_pay_not_allowed'}
        payer_account = Account.objects.filter(
            business_id=jwt_ctx['business_id'], account_type='business',
            account_index=jwt_ctx.get('account_index', 0)).first()
        payer_business = payer_account.business if payer_account else None
    else:
        payer_account = user.accounts.filter(
            account_type='personal',
            account_index=jwt_ctx.get('account_index', 0)).first()
        payer_business = None
    payer_addr = (getattr(payer_account, 'bsc_address', None) or '').lower()
    if not payer_addr:
        return {'success': False, 'error': 'no_bsc_address'}

    # Merchant destination: the business account's registered address.
    merchant_account = Account.objects.filter(
        business=invoice.merchant_business, account_type='business',
    ).order_by('account_index').first()
    merchant_addr = (getattr(merchant_account, 'bsc_address', None) or '').lower()
    if not merchant_addr:
        _notify_merchant_needs_app(invoice, user)
        return {'success': False, 'error': 'merchant_no_bsc_address'}

    gross_usd = Decimal(str(invoice.amount))
    gross_wei = int(gross_usd * WAD)
    fee_wei = payment_fee_wei(gross_wei)
    net_wei = gross_wei - fee_wei
    if net_wei <= 0 or fee_wei <= 0:
        return {'success': False, 'error': 'invalid_amount'}

    # Funding source: prefer the yield position; raw USDT is the fallback.
    try:
        pps_wad = cp_vault.p_plus_wad()
        shares_raw = cp_vault.erc20_balance_raw(vault_addr, payer_addr)
        shares_value_wei = (shares_raw * pps_wad) // WAD
        usdt_raw = cp_vault.usdt_balance_raw(payer_addr, fresh=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning('[PAY][BSC] balance rpc failed: %s', exc)
        return {'success': False, 'error': 'balance_unavailable'}

    if shares_value_wei >= gross_wei:
        kind = 'pay_cusd_plus'
        token_type = 'CUSD_PLUS'
        token = vault_addr
        gross_units = (gross_wei * WAD) // pps_wad  # shares at the live price
    elif usdt_raw >= gross_wei:
        kind = 'pay_usdt'
        token_type = 'USDT'
        token = USDT_BSC
        gross_units = gross_wei
    else:
        return {'success': False, 'error': 'insufficient_balance'}
    if gross_units <= 1:
        # The contract needs at least 1 unit of fee AND 1 of net.
        return {'success': False, 'error': 'invalid_amount'}

    # The contract splits net/fee itself (feeFor = the same ceiling rule);
    # the batch only carries the approval and the pay() call.
    invoice_id32 = invoice_id_bytes32(invoice.internal_id)
    calls = [
        {'to': token, 'value': '0',
         'data': '0x' + SEL_APPROVE + _addr_word(pay_contract) + _uint_word(gross_units)},
        {'to': pay_contract, 'value': '0',
         'data': '0x' + SEL_PAY + invoice_id32[2:] + _addr_word(token)
                 + _uint_word(gross_units) + _addr_word(merchant_addr)},
    ]

    # Idempotent row per (invoice, payer): re-prepare refreshes the batch
    # (prices move) without duplicating rows — the placeholder-hash pattern
    # from the Algorand prepare.
    payment_tx, created = PaymentTransaction.objects.get_or_create(
        invoice=invoice,
        payer_user=user,
        deleted_at__isnull=True,
        defaults={
            'payer_business': payer_business,
            'payer_type': 'business' if payer_business else 'user',
            'payer_display_name': (
                payer_business.name if payer_business
                else (user.get_full_name() or user.username or '')),
            'payer_phone': user.phone_number or '',
            'merchant_account_user': invoice.created_by_user,
            'merchant_business': invoice.merchant_business,
            'merchant_display_name': invoice.merchant_display_name or invoice.merchant_business.name,
            'payer_account': payer_account,
            'merchant_account': invoice.merchant_account,
            'payer_address': payer_addr,
            'merchant_address': merchant_addr,
            'amount': gross_usd,
            'token_type': token_type,
            'description': invoice.description or '',
            'status': 'PENDING_BLOCKCHAIN',
            'transaction_hash': f'pending_blockchain_{invoice.internal_id}_{int(time.time() * 1000)}',
            'idempotency_key': idempotency_key or None,
        },
    )
    if payment_tx.status == 'CONFIRMED':
        return {'success': False, 'error': 'invoice_already_paid'}
    payment_tx.token_type = token_type
    payment_tx.payer_address = payer_addr
    payment_tx.merchant_address = merchant_addr
    payment_tx.blockchain_data = {'bsc_calls': calls, 'kind': kind}
    payment_tx.status = 'PENDING_BLOCKCHAIN'
    payment_tx.save(update_fields=[
        'token_type', 'payer_address', 'merchant_address', 'blockchain_data',
        'status', 'updated_at',
    ])
    # Unified row via the existing payment post_save signal.

    return {
        'success': True,
        'payment_id': payment_tx.internal_id,
        'calls': calls,
        'token_type': token_type,
        'net': str(Decimal(net_wei) / WAD),
        'fee': str(Decimal(fee_wei) / WAD),
    }


def _validate_payment_batch(calls: list, payment_tx) -> None:
    """Defense in depth on the STORED batch: [approve(payContract, gross),
    payContract.pay(invoiceId, token, gross, merchant)] — token allowed,
    approval exactly the pay() amount, invoice id and merchant pinned to
    the stored row (the contract re-enforces all of it on-chain)."""
    from cusd_plus.sponsor_7702 import PolicyError, SEL_APPROVE, SEL_PAY, USDT_BSC

    vault = _vault_address()
    pay_contract = _pay_contract()
    if len(calls) != 2:
        raise PolicyError('bad_batch_size')
    for call in calls:
        if int(call.get('value') or 0) != 0:
            raise PolicyError('value_not_allowed')
        if not (call.get('data') or '').lower().startswith('0x'):
            raise PolicyError('bad_calldata')

    approve, pay = calls
    token = (approve.get('to') or '').lower()
    if token not in (vault, USDT_BSC):
        raise PolicyError('destination_not_allowed')
    a_data = approve['data'].lower()
    if (len(a_data) != 2 + 8 + 128 or a_data[2:10] != SEL_APPROVE
            or a_data[10:74] != _addr_word(pay_contract)):
        raise PolicyError('bad_calldata')
    gross_word = a_data[74:138]

    if (pay.get('to') or '').lower() != pay_contract:
        raise PolicyError('destination_not_allowed')
    p_data = pay['data'].lower()
    invoice_id32 = invoice_id_bytes32(payment_tx.invoice.internal_id)
    if (len(p_data) != 2 + 8 + 256 or p_data[2:10] != SEL_PAY
            or p_data[10:74] != invoice_id32[2:]          # invoiceId
            or p_data[74:138] != _addr_word(token)        # token == approved
            or p_data[138:202] != gross_word              # gross == approval
            or p_data[202:266] != _addr_word(payment_tx.merchant_address)):
        raise PolicyError('bad_calldata')


def submit_bsc_payment(user, payment_tx, nonce, deadline, intent_signature,
                       authorization=None) -> dict:
    from cusd_plus import sponsor_7702

    if payment_tx.payer_user_id != user.id:
        return {'success': False, 'error': 'not_your_payment'}
    if payment_tx.status != 'PENDING_BLOCKCHAIN' or not payment_tx.blockchain_data:
        return {'success': False, 'error': 'payment_not_pending'}
    invoice = payment_tx.invoice
    if invoice.status != 'PENDING' or getattr(invoice, 'is_expired', False):
        return {'success': False, 'error': 'invoice_not_pending'}

    payer_addr = (payment_tx.payer_address or '').lower()
    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))

    now = int(time.time())
    if not (now + 30 <= int(deadline) <= now + 1800):
        return {'success': False, 'error': 'bad_deadline'}

    meta = payment_tx.blockchain_data or {}
    kind = meta.get('kind') or 'pay_usdt'
    calls = meta.get('bsc_calls') or []

    try:
        _validate_payment_batch(calls, payment_tx)

        digest = sponsor_7702.intent_digest(
            calls, int(nonce), int(deadline), payer_addr, chain_id)
        signer = sponsor_7702.recover_intent_signer(digest, intent_signature)
        if signer != payer_addr:
            return {'success': False, 'error': 'bad_intent_signature'}

        auth_dict = None
        if not sponsor_7702.is_delegated(payer_addr):
            if authorization is None:
                return {'success': False, 'error': 'authorization_required',
                        'authorization_required': True}
            auth_dict = sponsor_7702.normalize_and_validate_authorization(
                authorization, payer_addr, chain_id)

        tx_hash, batch = sponsor_7702.send_sponsored_batch(
            user, payer_addr, calls, int(nonce), int(deadline),
            intent_signature, auth_dict, kind)
    except sponsor_7702.PolicyError as exc:
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        return {'success': False, 'error': exc.code}
    except Exception as exc:  # noqa: BLE001 — surface node rejections honestly
        logger.exception('[PAY][BSC] sponsored payment failed for %s', payment_tx.internal_id)
        return {'success': False, 'error': str(exc)[:200]}

    payment_tx.transaction_hash = tx_hash
    payment_tx.status = 'SUBMITTED'
    payment_tx.save(update_fields=['transaction_hash', 'status', 'updated_at'])

    try:
        from cusd_plus.vault import invalidate_position
        invalidate_position(payer_addr)
        invalidate_position(payment_tx.merchant_address or '')
    except Exception:  # noqa: BLE001
        pass

    from .tasks import confirm_bsc_payment
    confirm_bsc_payment.apply_async(args=[payment_tx.id, batch.id], countdown=8)

    return {'success': True, 'transaction_hash': tx_hash}
