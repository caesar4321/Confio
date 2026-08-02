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
(owner Safe collects), and replay-guards the invoiceId on-chain.

Two charge denominations (2026-08-01, ChargeScreen migration off Algorand):

  DOLLAR invoice (token_type CUSD_PLUS; legacy CUSD rows still settle here)
      `token` follows the PAYER's funding source — cUSD+ vault shares
      converted at the live share price, or raw USDT. USDT is not a charge
      option; it is the fallback that keeps a raw-USDT holder (including
      anyone geo-ineligible to mint cUSD+) able to pay at all.
  CONFIO invoice (token_type CONFIO)
      the re-issued BEP-20 moves directly, and `amount` is a token COUNT,
      not USD. Same 0.9% fee and the same on-chain invoice guard.

Merchant token rule: the merchant receives the same token the payer spent,
EXCEPT that an Ondo-ineligible merchant is never handed cUSD+.

The v1 rule allowed it, reasoning that holding cUSD+ is compliant
secondary-market acquisition (only MINTING is geo-gated) and that the
merchant's own screen shows and redeems vault balances. The second half was
false: for an ineligible holder the home screen renders only the USDT figure
and drops the vault balance, so a real payment landed as an invisible
position its owner could not operate. Product decision 2026-08-02: an
ineligible merchant should not receive or handle cUSD+ at all.

The MERCHANT's geo decides the destination token; the payer is always
carried there, never refused. The pay contract moves ONE token and has no
redeem path, so when the merchant cannot hold cUSD+ and the payer is funded
from savings, the batch grows a leading conversion:

    [ vault.redeemToUsdt(shares, minOut, PAYER),
      USDT.approve(payContract, gross),
      payContract.pay(invoiceId, USDT, gross, merchant) ]

Ondo refuses redemptions under $1, so the conversion takes at least that
floor and leaves the change with the payer as USDT — a 50-cent invoice must
not dead-end on a dollar minimum. The redeem credits the PAYER and the
validator pins that: crediting anyone else would be an exfiltration
primitive dressed as a payment.

The mirror case needs no work: an ineligible PAYER already pays in USDT, and
an eligible merchant's USDT auto-mints to cUSD+ through the existing savings
resume.
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

# Ondo's Instant Manager refuses redemptions under $1, so a conversion for an
# ineligible merchant converts at least this much and leaves the change with
# the payer as USDT.
ONDO_MIN_REDEEM_WEI = 10 ** 18
# The predicted redeem output is a prediction: pPlus only rises, but the chain
# floors twice, so minOut sits just under it. Mirrors send/bsc_flow.
REDEEM_SLIPPAGE_BPS = 50


def _uint_word(v: int) -> str:
    return format(int(v), 'x').rjust(64, '0')


def _addr_word(addr: str) -> str:
    return addr.lower().replace('0x', '').rjust(64, '0')


def _vault_address() -> str:
    return (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()


def _pay_contract() -> str:
    return (getattr(settings, 'BSC_PAY_CONTRACT_ADDRESS', '') or '').lower()


def _confio_token_address() -> str:
    return (getattr(settings, 'BSC_CONFIO_TOKEN_ADDRESS', '') or '').lower()


# Invoice token_type → what the BSC rail settles. 'CUSD' is the legacy
# dollar wire value; it means the same thing as CUSD_PLUS here — the DOLLAR,
# whose on-chain token the payer's funding source decides. Since the rail is
# pinned at creation, a CUSD invoice is always ALGORAND and cannot reach this
# module; 'CUSD' stays in the tuple only so a hand-edited row is settled
# correctly rather than mispriced.
DOLLAR_INVOICE_TOKENS = ('CUSD', 'CUSD_PLUS')


def invoice_id_bytes32(internal_id: str) -> str:
    """Deterministic bytes32 replay key for an invoice (uniform width;
    the contract keys paymentDone on it plus the payment terms)."""
    from eth_utils import keccak
    return '0x' + keccak(text=internal_id).hex()


def payment_fee_wei(gross_wei: int) -> int:
    """0.9% ceiling division — wei mirror of the Algorand builder's
    (amount*90 + 9999) // 10000 (payment_transaction_builder.py)."""
    return (gross_wei * FEE_BPS + BPS - 1) // BPS


# ── Server-signed payment authorization (audit 2026-07-31 P1) ─────────────
# The contract's invoice guard is GLOBAL on invoiceId and can only be
# consumed with the backend's EIP-712 signature over the exact terms — so a
# griefer can't brick an invoice and two honest payers can't both settle it.
# The backend signer is the sponsor KMS key (also the deployed
# paymentSigner); rotate on-chain via setPaymentSigner if the key changes.
from eth_utils import keccak, to_checksum_address  # noqa: E402
from eth_abi import encode as _abi_encode, decode as _abi_decode  # noqa: E402

# The DEPLOYED contract decides which of these is correct, so the backend must
# not switch until the new one is live. BSC_PAY_CONTRACT_V4 is the flag that
# flips both together; signing v4 against the v3 contract reverts every
# payment with "bad authorization".
_PAY_TYPEHASH_V3 = keccak(
    text='Pay(bytes32 invoiceId,address payer,address token,uint256 gross,address merchant,uint256 deadline)')
_PAY_TYPEHASH_V4 = keccak(
    text='Pay(bytes32 invoiceId,address payer,address token,uint256 gross,address merchant,bool redeemToUsdt,uint256 minUsdtOut,uint256 deadline)')


def _pay_contract_v4() -> bool:
    """NOT YET USABLE — the digest is only one third of the v4 switch.

    Codex audit 2026-08-02 [P2]: enabling this today is a deterministic BSC
    payment outage, because prepare still ABI-encodes the six-argument v3
    pay(), SEL_PAY is still the v3 selector, and _validate_payment_batch
    still decodes the v3 shape. The typehash would flip while the calldata
    did not. Those three must land with the flag; until they do this raises
    rather than silently breaking every payment.
    """
    enabled = bool(getattr(settings, 'BSC_PAY_CONTRACT_V4', False))
    if enabled:
        raise RuntimeError(
            'BSC_PAY_CONTRACT_V4 is set but the v4 calldata path is not built: '
            'prepare still encodes the v3 pay() signature and SEL_PAY is the '
            'v3 selector. Ship the selector, encoder and validator together '
            'with this flag.')
    return False
_PAY_DOMAIN_TYPEHASH = keccak(
    text='EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)')
_PAY_NAME_HASH = keccak(text='ConfioPay')
_PAY_VERSION_HASH = keccak(text='1')

# Server-signed authorization lifetime — the payer's 7702 batch must land
# before this expires (the contract reverts "authorization expired"). Wide
# enough for any realistic prepare→sign→submit; a stale one just reverts,
# and the global invoiceDone guard means it can never double-settle.
PAY_AUTH_TTL = 3600


def _pay_domain_separator(pay_contract: str, chain_id: int) -> bytes:
    return keccak(_abi_encode(
        ['bytes32', 'bytes32', 'bytes32', 'uint256', 'address'],
        [_PAY_DOMAIN_TYPEHASH, _PAY_NAME_HASH, _PAY_VERSION_HASH,
         int(chain_id), to_checksum_address(pay_contract)]))


def pay_authorization_digest(pay_contract: str, chain_id: int, invoice_id32: str,
                             payer: str, token: str, gross: int, merchant: str,
                             deadline: int, redeem_to_usdt: bool = False,
                             min_usdt_out: int = 0) -> bytes:
    """The EIP-712 digest ConfioPayContract.pay() verifies against
    paymentSigner. Recomputed byte-for-byte here and in the validator."""
    if _pay_contract_v4():
        struct_hash = keccak(_abi_encode(
            ['bytes32', 'bytes32', 'address', 'address', 'uint256', 'address',
             'bool', 'uint256', 'uint256'],
            [_PAY_TYPEHASH_V4, bytes.fromhex(invoice_id32[2:]),
             to_checksum_address(payer), to_checksum_address(token), int(gross),
             to_checksum_address(merchant), bool(redeem_to_usdt),
             int(min_usdt_out), int(deadline)]))
    else:
        struct_hash = keccak(_abi_encode(
            ['bytes32', 'bytes32', 'address', 'address', 'uint256', 'address', 'uint256'],
            [_PAY_TYPEHASH_V3, bytes.fromhex(invoice_id32[2:]),
             to_checksum_address(payer), to_checksum_address(token), int(gross),
             to_checksum_address(merchant), int(deadline)]))
    return keccak(b'\x19\x01' + _pay_domain_separator(pay_contract, chain_id) + struct_hash)


def _sign_pay_authorization(digest: bytes):
    """Sign the pay digest with the sponsor KMS key. Returns (sig_hex,
    signer_addr); signer_addr must equal the on-chain paymentSigner."""
    from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
    signer = get_bsc_sponsor_signer_from_settings()
    v, r, s = signer.sign_digest(digest)  # v in {0,1}
    sig = r.to_bytes(32, 'big') + s.to_bytes(32, 'big') + bytes([27 + int(v)])
    return '0x' + sig.hex(), signer.address


def _recover_pay_signer(digest: bytes, sig_hex: str) -> str:
    from eth_account import Account
    return Account._recover_hash(digest, signature=bytes.fromhex(sig_hex[2:].lower())).lower()


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
    from cusd_plus.sponsor_7702 import (SEL_APPROVE, SEL_PAY,
                                        SEL_REDEEM_TO_USDT, USDT_BSC)
    redeem_leg = None
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
    # The invoice names its rail (Codex audit 2026-08-01 [P1]). token_type
    # cannot: 'CONFIO' is the wire value on BOTH sides of the migration, so
    # keying off it left the same PENDING row preparable here AND on the
    # Algorand mutation at once — and invoiceDone is per-chain, blind to an
    # Algorand group. One authority, checked on both rails.
    if getattr(invoice, 'settlement_chain', 'ALGORAND') != 'BSC':
        return {'success': False, 'error': 'invoice_not_bsc'}
    invoice_token = (invoice.token_type or '').upper()
    if invoice_token not in DOLLAR_INVOICE_TOKENS and invoice_token != 'CONFIO':
        return {'success': False, 'error': 'unsupported_token'}

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

    # `gross_amount` is USD on a dollar invoice and a CONFIO COUNT on a
    # CONFIO one; gross_wei is that amount in the token's 18 decimals.
    gross_amount = Decimal(str(invoice.amount))
    gross_wei = int(gross_amount * WAD)
    fee_wei = payment_fee_wei(gross_wei)
    net_wei = gross_wei - fee_wei
    if net_wei <= 0 or fee_wei <= 0:
        return {'success': False, 'error': 'invalid_amount'}

    if invoice_token == 'CONFIO':
        # The token IS the denomination — no funding fork, no share price.
        confio_addr = _confio_token_address()
        if not confio_addr:
            return {'success': False, 'error': 'confio_not_configured'}
        try:
            confio_raw = cp_vault.erc20_balance_raw(confio_addr, payer_addr)
        except Exception as exc:  # noqa: BLE001
            logger.warning('[PAY][BSC] balance rpc failed: %s', exc)
            return {'success': False, 'error': 'balance_unavailable'}
        if confio_raw < gross_wei:
            return {'success': False, 'error': 'insufficient_balance'}
        kind = 'pay_confio'
        token_type = 'CONFIO'
        token = confio_addr
        gross_units = gross_wei
    else:
        # Funding source: prefer the yield position; raw USDT is the fallback.
        try:
            pps_wad = cp_vault.p_plus_wad()
            shares_raw = cp_vault.erc20_balance_raw(vault_addr, payer_addr)
            shares_value_wei = (shares_raw * pps_wad) // WAD
            usdt_raw = cp_vault.usdt_balance_raw(payer_addr, fresh=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning('[PAY][BSC] balance rpc failed: %s', exc)
            return {'success': False, 'error': 'balance_unavailable'}

        # An ineligible merchant must never be handed cUSD+. The pay contract
        # moves ONE token — payer's token straight through to merchant, no
        # redeem leg — so the only way to keep shares away from them is to
        # refuse the cUSD+ rail for this payment entirely.
        #
        # Phone-only on purpose: this is the RECIPIENT, not the caller, so
        # there is no request of theirs to read an IP from (see
        # cusd_plus/eligibility.is_ondo_eligible).
        #
        # This reverses the v1 "merchant receives the same token the payer
        # spent" rule for ineligible merchants only. That rule assumed the
        # merchant's account screen shows and redeems vault balances; for an
        # ineligible holder it does neither, so the money looked stuck.
        from cusd_plus.eligibility import is_ondo_eligible
        merchant_user = getattr(merchant_account, 'user', None)
        merchant_eligible = bool(merchant_user) and is_ondo_eligible(merchant_user)

        if merchant_eligible and shares_value_wei >= gross_wei:
            kind = 'pay_cusd_plus'
            token_type = 'CUSD_PLUS'
            token = vault_addr
            gross_units = (gross_wei * WAD) // pps_wad  # shares at the live price
        elif not merchant_eligible and usdt_raw < gross_wei and shares_value_wei > 0:
            # The merchant cannot hold cUSD+, so the payer converts on the way
            # through: redeem to their OWN address, then pay in USDT. Same
            # shape as the presale buy's funding leg, and it means an
            # ineligible merchant never costs the payer a refusal.
            #
            # Ondo rejects redemptions under $1, so convert at least that
            # floor even when the invoice is smaller and leave the change as
            # the payer's USDT — refusing a 50-cent payment because the floor
            # is a dollar would be the same dead end in a different place.
            shortfall = gross_wei - usdt_raw
            target_out = max(shortfall, ONDO_MIN_REDEEM_WEI)
            oracle_p_wad = cp_vault.last_oracle_price_wad()
            shares_needed = -(-(target_out * WAD) // pps_wad)  # ceil
            if shares_needed > shares_raw:
                shares_needed = shares_raw
            predicted = cp_vault.redeem_usdt_out(shares_needed, pps_wad, oracle_p_wad)
            if predicted < shortfall or predicted < ONDO_MIN_REDEEM_WEI:
                # Not enough savings to clear the invoice or the Ondo floor.
                # Ordinary insufficient funds, not a policy refusal.
                return {'success': False, 'error': 'insufficient_balance'}
            kind = 'pay_usdt'
            token_type = 'USDT'
            token = USDT_BSC
            gross_units = gross_wei
            redeem_leg = {
                'to': vault_addr, 'value': '0',
                'data': '0x' + SEL_REDEEM_TO_USDT + _uint_word(shares_needed)
                        + _uint_word(predicted * (10_000 - REDEEM_SLIPPAGE_BPS) // 10_000)
                        + _addr_word(payer_addr),
            }
            logger.info('[PAY][BSC] invoice %s: merchant is Ondo-ineligible — redeeming '
                        '%s shares to USDT for the payer before paying',
                        invoice.internal_id, shares_needed)
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
    # the batch carries the approval and the server-authorized pay() call.
    invoice_id32 = invoice_id_bytes32(invoice.internal_id)
    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))
    pay_deadline = int(time.time()) + PAY_AUTH_TTL
    digest = pay_authorization_digest(
        pay_contract, chain_id, invoice_id32, payer_addr, token,
        gross_units, merchant_addr, pay_deadline)
    try:
        auth_sig, signer_addr = _sign_pay_authorization(digest)
    except Exception:  # noqa: BLE001
        logger.exception('[PAY][BSC] authorization signing failed for %s', invoice.internal_id)
        return {'success': False, 'error': 'authorization_signing_failed'}
    pay_args = _abi_encode(
        ['bytes32', 'address', 'uint256', 'address', 'uint256', 'bytes'],
        [bytes.fromhex(invoice_id32[2:]), to_checksum_address(token), int(gross_units),
         to_checksum_address(merchant_addr), pay_deadline, bytes.fromhex(auth_sig[2:])])
    calls = ([redeem_leg] if redeem_leg else []) + [
        {'to': token, 'value': '0',
         'data': '0x' + SEL_APPROVE + _addr_word(pay_contract) + _uint_word(gross_units)},
        {'to': pay_contract, 'value': '0',
         'data': '0x' + SEL_PAY + pay_args.hex()},
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
            'amount': gross_amount,
            'token_type': token_type,
            'description': invoice.description or '',
            'status': 'PENDING_BLOCKCHAIN',
            'transaction_hash': f'pending_blockchain_{invoice.internal_id}_{int(time.time() * 1000)}',
            'idempotency_key': idempotency_key or None,
        },
    )
    if payment_tx.status == 'CONFIRMED':
        return {'success': False, 'error': 'invoice_already_paid'}
    # Never rebuild an in-flight payment (audit 2026-07-31 P1): a re-prepare
    # while SUBMITTED would reset the row to PENDING and let a second submit
    # broadcast a duplicate batch. The chain's global invoiceDone would
    # revert the loser, but we refuse to waste a sponsor tx over it.
    if payment_tx.status == 'SUBMITTED':
        return {'success': False, 'error': 'payment_in_progress'}
    payment_tx.token_type = token_type
    payment_tx.payer_address = payer_addr
    payment_tx.merchant_address = merchant_addr
    payment_tx.blockchain_data = {
        'bsc_calls': calls, 'kind': kind,
        'pay_deadline': pay_deadline, 'pay_signer': signer_addr,
    }
    payment_tx.status = 'PENDING_BLOCKCHAIN'
    payment_tx.save(update_fields=[
        'token_type', 'payer_address', 'merchant_address', 'blockchain_data',
        'status', 'updated_at',
    ])
    # Unified row via the existing payment post_save signal.

    from cusd_plus.sponsor_7702 import intent_id_hex
    return {
        'success': True,
        'payment_id': payment_tx.internal_id,
        'calls': calls,
        'token_type': token_type,
        'net': str(Decimal(net_wei) / WAD),
        'fee': str(Decimal(fee_wei) / WAD),
        'intent_id': intent_id_hex(kind, payment_tx.id),
    }


def _payer_still_authorized(user, payment_tx) -> bool:
    """Is this user STILL allowed to spend from the payer account?

    prepare ran the full JWT business gate; submit only checked that the row
    belonged to the same user. Between the two, an employee can be
    deactivated, demoted, or have send_funds revoked — and the prepared batch
    would still broadcast. Re-check at the point money actually moves.

    Mirrors get_jwt_business_context_with_validation deliberately: the Account
    is ownership, is_active is the deactivation signal, and an explicit False
    override denies. There is no request here, so the IP-bearing gate itself
    cannot be reused.
    """
    biz_id = getattr(payment_tx, 'payer_business_id', None)
    if not biz_id:
        return True  # personal payer — payer_user_id was already matched
    from users.models import Account
    from users.models_employee import BusinessEmployee
    from users.jwt_context import check_role_permission

    if Account.objects.filter(
            user=user, business_id=biz_id, account_type='business',
            deleted_at__isnull=True).exists():
        return True
    emp = BusinessEmployee.objects.filter(
        user=user, business_id=biz_id, is_active=True,
        deleted_at__isnull=True).first()
    if emp is None:
        return False
    overrides = emp.permissions or {}
    if 'send_funds' in overrides and not overrides['send_funds']:
        return False
    return check_role_permission(emp.role, 'send_funds')


def _invoice_terms_unchanged(invoice, payment_tx) -> bool:
    """Do the invoice's terms still match what the payer authorized?

    Only settlement_chain was immutable; amount, token_type and the merchant
    could all be edited after preparation while batch validation compared
    against the payment row's OWN snapshot. The old amount could then settle
    to the old address and mark the modified invoice PAID — payer, invoice,
    ledger and recipient each describing a different transaction.
    """
    from decimal import Decimal
    try:
        if Decimal(str(invoice.amount)) != Decimal(str(payment_tx.amount)):
            return False
    except Exception:  # noqa: BLE001 — unparseable means do not proceed
        return False
    # The invoice's DENOMINATION must not have changed class. A dollar
    # invoice settles in cUSD+ or USDT depending on the payer's funding, so
    # comparing it to payment_tx.token_type directly would be wrong; what
    # must hold is that a dollar invoice is still a dollar invoice and a
    # CONFIO invoice still a CONFIO one.
    settled = (payment_tx.token_type or '').upper()
    invoice_token = (invoice.token_type or '').upper()
    if settled == 'CONFIO':
        if invoice_token != 'CONFIO':
            return False
    elif invoice_token not in DOLLAR_INVOICE_TOKENS:
        return False
    if invoice.merchant_business_id != payment_tx.merchant_business_id:
        return False
    if invoice.merchant_account_id != payment_tx.merchant_account_id:
        return False
    return True


def _validate_payment_batch(calls: list, payment_tx) -> None:
    """Defense in depth on the STORED batch:
    [approve(payContract, gross),
     payContract.pay(invoiceId, token, gross, merchant, deadline, authSig)].

    A third, LEADING call is allowed when the merchant cannot hold cUSD+ and
    the payer converted savings first:
    [vault.redeemToUsdt(shares, minOut, payer), approve(...), pay(...)].

    Every field is pinned to the stored row, the approval matches the pay()
    amount, the deadline hasn't lapsed, and the embedded server authorization
    recovers to the expected paymentSigner — the contract re-enforces all of
    it on-chain, but a bad batch never reaches the sponsor."""
    payer_addr = (getattr(payment_tx, 'payer_address', '') or '').lower()
    if not payer_addr:
        raise PolicyError('payer_address_missing')
    from cusd_plus.sponsor_7702 import (PolicyError, SEL_APPROVE, SEL_PAY,
                                        SEL_REDEEM_TO_USDT, USDT_BSC)

    vault = _vault_address()
    pay_contract = _pay_contract()
    # Token pinned to the row's KIND, not merely to the contract's allowlist:
    # a CONFIO payment row can only ever move CONFIO (send/bsc_flow shape).
    expected_token = {
        'pay_cusd_plus': vault,
        'pay_usdt': USDT_BSC,
        'pay_confio': _confio_token_address(),
    }.get((payment_tx.blockchain_data or {}).get('kind'))
    if len(calls) not in (2, 3):
        raise PolicyError('bad_batch_size')
    for call in calls:
        if int(call.get('value') or 0) != 0:
            raise PolicyError('value_not_allowed')
        if not (call.get('data') or '').lower().startswith('0x'):
            raise PolicyError('bad_calldata')

    # Three calls means the payer converted savings on the way through,
    # because this merchant cannot hold cUSD+. Validate that leg as strictly
    # as the rest: it must be redeemToUsdt on OUR vault, paying the PAYER —
    # a redeem crediting anyone else would be an exfiltration primitive
    # dressed as a payment.
    if len(calls) == 3:
        redeem, approve, pay = calls
        if (redeem.get('to') or '').lower() != _vault_address():
            raise PolicyError('destination_not_allowed')
        r_data = (redeem.get('data') or '').lower()
        if len(r_data) != 2 + 8 + 192 or r_data[2:10] != SEL_REDEEM_TO_USDT:
            raise PolicyError('bad_calldata')
        if r_data[138:202] != _addr_word(payer_addr):
            raise PolicyError('redeem_recipient_not_allowed')
    else:
        approve, pay = calls
    token = (approve.get('to') or '').lower()
    if not expected_token or token != expected_token:
        raise PolicyError('destination_not_allowed')
    a_data = approve['data'].lower()
    if (len(a_data) != 2 + 8 + 128 or a_data[2:10] != SEL_APPROVE
            or a_data[10:74] != _addr_word(pay_contract)):
        raise PolicyError('bad_calldata')
    gross = int(a_data[74:138], 16)

    if (pay.get('to') or '').lower() != pay_contract:
        raise PolicyError('destination_not_allowed')
    p_data = pay['data'].lower()
    if p_data[2:10] != SEL_PAY:
        raise PolicyError('bad_calldata')
    try:
        invoice_id_b, d_token, d_gross, d_merchant, d_deadline, auth_sig = _abi_decode(
            ['bytes32', 'address', 'uint256', 'address', 'uint256', 'bytes'],
            bytes.fromhex(p_data[10:]))
    except Exception:  # noqa: BLE001
        raise PolicyError('bad_calldata')

    invoice_id32 = invoice_id_bytes32(payment_tx.invoice.internal_id)
    meta = payment_tx.blockchain_data or {}
    if ('0x' + invoice_id_b.hex() != invoice_id32          # invoiceId
            or d_token.lower() != token                    # token == approved
            or int(d_gross) != gross                        # gross == approval
            or d_merchant.lower() != (payment_tx.merchant_address or '').lower()):
        raise PolicyError('bad_calldata')
    if int(d_deadline) != int(meta.get('pay_deadline') or 0):
        raise PolicyError('bad_calldata')
    if int(d_deadline) <= int(time.time()):
        raise PolicyError('authorization_expired')

    # Re-verify the server's own authorization recovers to the paymentSigner.
    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))
    digest = pay_authorization_digest(
        pay_contract, chain_id, invoice_id32, payment_tx.payer_address, token,
        gross, payment_tx.merchant_address, int(d_deadline))
    try:
        recovered = _recover_pay_signer(digest, '0x' + auth_sig.hex())
    except Exception:  # noqa: BLE001
        raise PolicyError('bad_authorization')
    expected = (meta.get('pay_signer') or '').lower()
    if not expected or recovered != expected:
        raise PolicyError('bad_authorization')


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
    # Rail re-checked at BROADCAST time, mirroring the Algorand submit: the
    # prepare-time check alone leaves a window an admin/ORM edit could use
    # to point a prepared invoice at the other chain (Codex audit [P1]).
    if getattr(invoice, 'settlement_chain', 'ALGORAND') != 'BSC':
        return {'success': False, 'error': 'invoice_not_bsc'}
    # The invoice can be edited between prepare and submit; only the rail was
    # re-checked. Everything the payer agreed to is re-checked here.
    if not _invoice_terms_unchanged(invoice, payment_tx):
        logger.warning('[PAY][BSC] invoice %s changed after preparation — refusing',
                       invoice.internal_id)
        return {'success': False, 'error': 'invoice_terms_changed'}
    # And the payer's authority can be revoked in that same window.
    if not _payer_still_authorized(user, payment_tx):
        logger.warning('[PAY][BSC] user %s no longer authorized to spend from the '
                       'payer account for invoice %s', user.id, invoice.internal_id)
        return {'success': False, 'error': 'not_authorized'}

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

        intent_id = sponsor_7702.intent_id_for(kind, payment_tx.id)
        digest = sponsor_7702.intent_digest(
            calls, int(nonce), int(deadline), payer_addr, chain_id, intent_id)
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
            intent_signature, auth_dict, kind, source_id=payment_tx.id)
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

    # See send/bsc_flow.py: sponsor-observed execution, not settlement.
    return {'success': True, 'transaction_hash': tx_hash,
            'execution': getattr(batch, 'executed_early', None)}
