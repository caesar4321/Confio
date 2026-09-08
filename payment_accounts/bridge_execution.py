"""Prepare once, authorize once, persist before broadcast, reconcile on servers."""
import json
import time
from decimal import Decimal, localcontext

from django.conf import settings
from django.db import transaction, connection
from django.db.models import Max, Q
from django.utils import timezone

from .allbridge_next import NextClient, NextError, TOKENS, address, uint
from .bridge import verified_destination
from .bridge_binding import IntentsClient, deposit_call, validate_binding
from . import bridge_chain as chain
from .models import PaymentBridgeQuote, PaymentBridgeTransfer
from .services import PaymentAccountError, _require_provider_enabled


def execution_enabled(source_token):
    flag = 'PAYMENT_BRIDGE_BSC_ENABLED' if source_token == 'BSC:USDT' else 'PAYMENT_BRIDGE_POLYGON_ENABLED'
    if source_token == 'BSC:USDT' and not getattr(settings, 'CUSD_PLUS_7702_ENABLED', False):
        raise PaymentAccountError('BSC sponsorship is not enabled')
    if not getattr(settings, flag, False):
        raise PaymentAccountError('Bridge execution is not enabled for this direction')


def check_owner(quote, owner):
    if quote.confio_account_id != owner.pk or owner.deleted_at:
        raise PaymentAccountError('Bridge not found')
    if address(owner.bsc_address) != quote.source_address:
        raise PaymentAccountError('Bridge wallet changed')


def current_provider(quote, owner):
    instruction = quote.funding_instruction
    account = instruction.financial_account
    if account.provider not in {'infinia', 'cobre'} or account.status != 'active' or account.provider_profile.status != 'active':
        raise PaymentAccountError('Provider account is not active')
    if instruction.status != 'active' or (instruction.expires_at and instruction.expires_at <= timezone.now()):
        raise PaymentAccountError('Provider instruction is not active')
    _require_provider_enabled(account.provider)
    from .bridge import enforce_and_record, context_from_identity
    identity = account.provider_profile.identity_verification
    if not identity or identity.status != 'verified':
        raise PaymentAccountError('Verified identity required')
    enforce_and_record(confio_account=owner, provider=account.provider, scope='conversion',
                       context=context_from_identity(identity, account_country=account.country))
    if quote.source_token_id == 'BSC:USDT':
        if verified_destination(quote.funding_instruction, owner) != quote.destination_address:
            raise PaymentAccountError('Provider destination changed')
    elif quote.destination_address != quote.source_address:
        raise PaymentAccountError('Inbound bridge must return to the active wallet')


def _word(value):
    return f'{value:064x}'


def funding_calls(owner, amount):
    """Redeem only the missing USDT, charging the existing perimeter once."""
    from cusd_plus import vault, cusd_vault
    from cusd_plus.sponsor_7702 import SEL_CUSD_REDEEM, SEL_UNWRAP_TO_CUSD

    wallet_usdt = max(0, chain.token_balance('BSC:USDT', owner.bsc_address)
                      - vault.reserved_usdt_wei(owner.user, owner.bsc_address))
    wallet_used = min(wallet_usdt, amount)
    missing = amount - wallet_used
    if not missing:
        return [], {'wallet_usdt_units': str(wallet_used), 'gross_redeem_units': '0', 'fee_units': '0'}
    cusd_vault.require_operational()
    bps = cusd_vault.current_fee_bps()
    if not 0 <= bps <= 90:
        raise NextError('Unexpected conversion fee')
    gross = (missing * 10000 + (10000 - bps) - 1) // (10000 - bps)
    preview = cusd_vault.preview_redeem_wei(gross)
    if preview.net_wei < missing:
        raise NextError('Conversion output is insufficient')
    cusd = address(cusd_vault.vault_address())
    cusd_balance = vault.erc20_balance_raw(cusd, owner.bsc_address)
    calls = []
    recipient = address(owner.bsc_address)[2:].rjust(64, '0')
    if cusd_balance < gross:
        needed = gross - cusd_balance
        plus = address(vault.vault_address())
        pps = vault.p_plus_wad(fresh=True)
        oracle = vault.current_oracle_price_wad(fresh=True)
        if pps <= 0 or oracle <= 0:
            raise NextError('Invalid savings price')
        redemption_target = max(needed, vault.ONDO_MIN_REDEEM_WEI)
        shares = (redemption_target * 10**18 + pps - 1) // pps
        for _ in range(8):
            if vault.redeem_gross_usdt_out(shares, pps, oracle) >= redemption_target:
                break
            shares += 1
        output = vault.redeem_gross_usdt_out(shares, pps, oracle)
        if output < max(needed, vault.ONDO_MIN_REDEEM_WEI):
            raise NextError('Savings redemption is below its minimum')
        if shares > vault.erc20_balance_raw(plus, owner.bsc_address):
            raise NextError('Insufficient dollar balance')
        calls.append({'to': plus, 'value': '0', 'data': '0x' + SEL_UNWRAP_TO_CUSD
                      + _word(shares) + _word(needed) + recipient})
    calls.append({'to': cusd, 'value': '0', 'data': '0x' + SEL_CUSD_REDEEM
                  + _word(gross) + _word(missing) + recipient})
    return calls, {'wallet_usdt_units': str(wallet_used), 'gross_redeem_units': str(gross),
                   'fee_units': str(preview.fee_wei)}


def prepare_bridge(owner, quote_id, route_index=0, *, client=None, intents=None):
    client, intents = client or NextClient(), intents or IntentsClient()
    with transaction.atomic():
        # One wallet preparation at a time, so reservations cannot overlap.
        owner = type(owner).objects.select_for_update().get(pk=owner.pk)
        q = PaymentBridgeQuote.objects.select_for_update().select_related(
            'funding_instruction__financial_account__provider_profile',
        ).get(internal_id=quote_id, confio_account=owner)
        check_owner(q, owner)
        execution_enabled(q.source_token_id)
        previous = PaymentBridgeTransfer.objects.filter(quote=q).first()
        if previous:
            return previous
        current_provider(q, owner)
        if PaymentBridgeTransfer.objects.filter(quote__source_address=q.source_address).filter(
                Q(status__in=['submitted', 'bridging', 'needs_review']) |
                Q(status='prepared', deadline__gt=int(time.time()))).exists():
            raise NextError('An existing bridge is pending; check its status first')
        if q.expires_at <= timezone.now():
            raise NextError('Quote expired; request a fresh quote')
        if type(route_index) is not int or not 0 <= route_index < len(q.routes):
            raise NextError('Invalid bridge route')
        route = q.routes[route_index]
        if route['messenger'] != 'near-intents':
            raise NextError('This bridge messenger is not enabled for execution')
        source_chain = q.source_token_id.split(':')[0]
        chain.require_chain(source_chain)
        build = client.build(route, source_address=q.source_address, destination_address=q.destination_address)
        deposit, call = deposit_call(build, q.source_token_id, q.amount_units)
        minimum = uint(build['amountOutMin'], positive=True)
        accepted_min = uint(route.get('amountOutMin', str(uint(route['amountOut']) * 99 // 100)), positive=True)
        if minimum < accepted_min:
            raise NextError('Bridge price changed; request a fresh quote')
        status = intents.status(deposit)
        now = int(time.time())
        deadline = min(now + 600, validate_binding(status, intents.tokens(), q, deposit,
                       minimum=str(minimum), now=now) - 30)
        funding = {'wallet_usdt_units': '0', 'fee_units': '0', 'gross_redeem_units': '0'}
        if source_chain == 'BSC':
            prefix, funding = funding_calls(owner, int(q.amount_units))
        else:
            prefix = []
            if chain.token_balance(q.source_token_id, q.source_address) < int(q.amount_units):
                raise NextError('Polygon USDC has not arrived in the wallet yet')
            domain = chain.rpc('POL', 'eth_call', [{'to': chain.USDC,
                 'data': '0x' + __import__('eth_utils').keccak(text='DOMAIN_SEPARATOR()')[:4].hex()}, 'latest'])
            if domain.lower() != '0x' + chain.authorization_domain().hex():
                raise NextError('Unsupported USDC authorization domain')
        if q.expires_at <= timezone.now():
            raise NextError('Quote expired during preparation; request a fresh quote')
        return PaymentBridgeTransfer.objects.create(
            quote=q, deposit_address=deposit, amount_out_min=str(minimum),
            amount_out=build['amountOut'], deadline=deadline, calls=prefix + [call],
            binding={'quoteResponse': status['quoteResponse'], 'funding': funding},
        )


def _adopt_bsc_batch(t):
    from blockchain.models import SponsoredBatch
    batch = SponsoredBatch.objects.filter(
        user=t.quote.confio_account.user, client_request_id='bridge:' + str(t.internal_id),
    ).first()
    if batch:
        if batch.kind != 'payment_bridge' or json.loads(batch.calls_json) != t.calls:
            raise NextError('Bridge batch mismatch')
        with transaction.atomic():
            locked = PaymentBridgeTransfer.objects.select_for_update().get(pk=t.pk)
            if not locked.source_tx_hash and locked.status == 'prepared':
                locked.batch, locked.source_tx_hash, locked.status = batch, batch.tx_hash, 'submitted'
                locked.save(update_fields=['batch', 'source_tx_hash', 'status', 'updated_at'])
            t.refresh_from_db()
    return batch


def submit_bridge(owner, transfer_id, signature, *, nonce='0', authorization=None):
    from cusd_plus import sponsor_7702 as sponsor
    # Do NOT hold an outer transaction across BSC sponsor broadcast. Its signed
    # batch must commit independently before any eth_sendRawTransaction call.
    t = PaymentBridgeTransfer.objects.select_related('quote__confio_account').get(
        internal_id=transfer_id, quote__confio_account=owner)
    check_owner(t.quote, owner)
    if t.status != 'prepared' or t.source_tx_hash:
        return t
    if t.quote.source_token_id == 'BSC:USDT' and _adopt_bsc_batch(t):
        return t
    execution_enabled(t.quote.source_token_id)
    current_provider(t.quote, owner)
    if int(time.time()) >= t.deadline - 30:
        raise NextError('Bridge authorization expired')
    if t.quote.source_token_id == 'POL:USDC':
        _submit_polygon(t, signature)
        t.refresh_from_db()
    else:
        chain.require_chain('BSC')
        intent_id = sponsor.intent_id_for('payment_bridge', client_request_id='bridge:' + str(t.internal_id))
        digest = sponsor.intent_digest(t.calls, uint(str(nonce)), t.deadline,
                                       t.quote.source_address, 56, intent_id)
        if sponsor.recover_intent_signer(digest, signature) != t.quote.source_address:
            raise NextError('Invalid bridge signature')
        auth = None
        if not sponsor.is_delegated(t.quote.source_address):
            if authorization is None:
                raise NextError('authorization_required')
            auth = sponsor.normalize_and_validate_authorization(authorization, t.quote.source_address, 56)
        def persist_signed(batch, raw):
            persisted = PaymentBridgeTransfer.objects.filter(pk=t.pk, status='prepared', source_tx_hash='').update(
                batch=batch, signed_raw_tx=raw, source_tx_hash=batch.tx_hash, status='submitted', updated_at=timezone.now())
            if persisted != 1:
                raise NextError('Bridge state changed before submission')

        try:
            sponsor.send_sponsored_batch(owner.user, t.quote.source_address, t.calls,
                int(nonce), t.deadline, signature, auth, 'payment_bridge', source_id=t.pk,
                client_request_id='bridge:' + str(t.internal_id), intent_id=intent_id, persist_signed=persist_signed)
        except Exception:
            if not _adopt_bsc_batch(t):
                raise
        else:
            _adopt_bsc_batch(t)
    q = t.quote
    type(q.money_flow).objects.filter(pk=q.money_flow_id, status='created').update(
        status='processing', updated_at=timezone.now())
    return t


def reconcile_bridge(t, *, intents=None):
    """Only finalized token receipts count as delivery. Never manufacture credit."""
    intents = intents or IntentsClient()
    q = t.quote
    if t.status == 'delivered':
        reconcile_provider_credit(t)
        return t
    if not t.source_tx_hash and q.source_token_id == 'BSC:USDT':
        _adopt_bsc_batch(t)
    if not t.source_tx_hash:
        with transaction.atomic():
            locked = PaymentBridgeTransfer.objects.select_for_update().get(pk=t.pk)
            if locked.source_tx_hash:
                return locked  # A submit won the race; reconcile next tick.
            if locked.status == 'prepared' and locked.deadline < int(time.time()):
                locked.status = 'expired'
                locked.save(update_fields=['status', 'updated_at'])
                q.money_flow.status = 'failed'
                q.money_flow.save(update_fields=['status', 'updated_at'])
            return locked
    source_chain = q.source_token_id.split(':')[0]
    source = chain.final_receipt(source_chain, t.source_tx_hash)
    if not source:
        if int(time.time()) > t.deadline + 3600:
            PaymentBridgeTransfer.objects.filter(pk=t.pk).exclude(status__in=['delivered', 'refunded', 'failed']).update(
                status='needs_review', failure_code='source_confirmation_delayed', updated_at=timezone.now())
        # Polygon owns a dedicated sponsor nonce stream. Replaying even an
        # expired authorization consumes its nonce (via a revert) instead of
        # stranding every later sponsor transaction behind a missing nonce.
        if t.signed_raw_tx and (source_chain == 'POL' or int(time.time()) < t.deadline):
            try:
                chain.rpc(source_chain, 'eth_sendRawTransaction', [t.signed_raw_tx])
            except Exception:
                pass
        return t
    transferred = chain.received_units(source, q.source_token_id, t.deposit_address, q.source_address)
    if transferred != int(q.amount_units):
        t.status = 'failed' if transferred == 0 else 'needs_review'
        t.failure_code = 'source_transfer_mismatch'
    else:
        # Record the canonical on-chain perimeter fee even when the generic
        # sponsored-batch worker has not yet processed the bridge's source.
        if t.batch_id:
            from cusd_plus.tasks import _reconcile_cusd_fee_event
            _reconcile_cusd_fee_event(batch=t.batch, receipt=source)
        t.status, t.failure_code = 'bridging', ''
        status = intents.status(t.deposit_address)
        if status.get('quoteResponse', {}).get('quoteRequest') != t.binding['quoteResponse']['quoteRequest']:
            raise NextError('Bridge status binding changed')
        details = status.get('swapDetails') or {}
        hashes = {v['hash'].lower() for v in details.get('originChainTxHashes', [])}
        if status.get('status') == 'SUCCESS' and t.source_tx_hash.lower() in hashes:
            outputs = details.get('destinationChainTxHashes', [])
            if not outputs or len(outputs) > 5:
                raise NextError('Invalid bridge destination evidence')
            if len(outputs) > 1 and q.destination_token_id == 'POL:USDC':
                # Provider credit is currently a single ledger fact/hash. Never
                # treat one installment as credit for a whole split delivery.
                t.status, t.failure_code = 'needs_review', 'split_provider_delivery'
                return _record_bridge_result(t)
            seen, total = set(), 0
            for tx in outputs:
                tx_hash = tx['hash'].lower()
                if tx_hash in seen:
                    raise NextError('Duplicate bridge destination evidence')
                seen.add(tx_hash)
                receipt = chain.final_receipt(q.destination_token_id.split(':')[0], tx_hash)
                if not receipt:
                    return t
                total += chain.received_units(receipt, q.destination_token_id, q.destination_address)
            expected = uint(details.get('amountOut'), positive=True)
            if total != expected or total < int(t.amount_out_min):
                t.status, t.failure_code = 'needs_review', 'destination_amount_mismatch'
            else:
                t.status, t.actual_out_units = 'delivered', str(total)
                t.destination_tx_hash = outputs[0]['hash']
        elif status.get('status') in {'FAILED', 'REFUNDED', 'INCOMPLETE_DEPOSIT'}:
            # A status string alone does not prove a refund hit the wallet.
            t.status, t.failure_code = 'needs_review', 'bridge_' + status['status'].lower()
    return _record_bridge_result(t)


def _record_bridge_result(t):
    q = t.quote
    with transaction.atomic():
        locked = PaymentBridgeTransfer.objects.select_for_update().get(pk=t.pk)
        if locked.status in {'delivered', 'failed', 'refunded'}:
            return locked
        t.save(update_fields=['status', 'failure_code', 'actual_out_units', 'destination_tx_hash', 'updated_at'])
        flow = q.money_flow
        # Outbound bridge delivery is not provider credit. Inbound completes
        # this USDT-targeted flow; the existing USDT -> cUSD conversion is separate.
        flow.status = 'needs_review' if t.status == 'needs_review' else ('failed' if t.status == 'failed' else 'processing')
        if t.status == 'delivered' and q.destination_token_id == 'BSC:USDT':
            flow.status = 'succeeded'
        flow.metadata = dict(flow.metadata, stage=t.status)
        if t.status == 'delivered':
            with localcontext() as ctx:
                ctx.prec = 80
                flow.target_amount = Decimal(t.actual_out_units) / Decimal(10)**TOKENS[q.destination_token_id][1]
        flow.save(update_fields=['status', 'metadata', 'target_amount', 'updated_at'])
    if t.status == 'delivered':
        reconcile_provider_credit(t)
    return t


def _submit_polygon(t, signature):
    from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
    from eth_utils import to_checksum_address, keccak
    calldata = chain.authorization_calldata(t, signature)
    chain.require_chain('POL')
    signer = get_bsc_sponsor_signer_from_settings()
    sponsor = address(signer.address)
    with transaction.atomic():
        t = PaymentBridgeTransfer.objects.select_for_update().get(pk=t.pk)
        if t.source_tx_hash:
            return
        if t.status != 'prepared' or int(time.time()) >= t.deadline - 30:
            raise NextError('Bridge authorization expired or state changed')
        # All Polygon sponsor use in this integration serializes nonce allocation.
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(137, 77023009)')
        pending = int(chain.rpc('POL', 'eth_getTransactionCount', [sponsor, 'pending']), 16)
        maximum = PaymentBridgeTransfer.objects.filter(sponsor_address=sponsor).aggregate(n=Max('sponsor_nonce'))['n']
        sponsor_nonce = max(pending, maximum + 1 if maximum is not None else 0)
        gas = 180000
        price = int(chain.rpc('POL', 'eth_gasPrice', []), 16) * 12 // 10
        if price <= 0 or price > int(getattr(settings, 'PAYMENT_BRIDGE_POLYGON_MAX_GAS_PRICE_WEI', 500000000000)):
            raise NextError('Polygon gas price exceeds sponsor cap')
        tx = {'type': 2, 'chainId': 137, 'nonce': sponsor_nonce,
              'maxPriorityFeePerGas': price, 'maxFeePerGas': price, 'gas': gas,
              'to': to_checksum_address(chain.USDC), 'value': 0, 'data': calldata, 'accessList': []}
        chain.rpc('POL', 'eth_call', [{'from': sponsor, 'to': chain.USDC, 'data': calldata, 'gas': hex(gas)}, 'latest'])
        raw, tx_hash = signer.sign_typed_transaction(tx)
        if '0x' + keccak(bytes.fromhex(raw.removeprefix('0x'))).hex() != tx_hash.lower():
            raise NextError('Signed transaction hash mismatch')
        t.signed_raw_tx, t.source_tx_hash = raw, tx_hash
        t.sponsor_address, t.sponsor_nonce, t.status = sponsor, sponsor_nonce, 'submitted'
        t.save(update_fields=['signed_raw_tx', 'source_tx_hash', 'sponsor_address', 'sponsor_nonce', 'status', 'updated_at'])
    # Committed above. A failed or ambiguous broadcast is recovered by the worker.
    try:
        chain.rpc('POL', 'eth_sendRawTransaction', [raw])
    except Exception:
        pass


def reconcile_provider_credit(t):
    """Cobre's documented global_credit binds the credited balance to chain evidence.

    Infinia uses the documented CRYPTO movement's transaction hash and network.
    Never match deposits merely by equal amounts or arrival times.
    """
    from .models import LedgerEntry
    q = t.quote
    account = q.funding_instruction.financial_account
    if t.provider_credit_id or t.status != 'delivered' or q.destination_token_id != 'POL:USDC' or account.provider not in {'cobre', 'infinia'}:
        return
    # The stablecoin credit can be rounded or off-ramped to USD by Cobre.
    # Its own ledger amount is authoritative; don't replace it with bridge output.
    matches = []
    if account.provider == 'infinia':
        candidates = LedgerEntry.objects.filter(provider='infinia', financial_account=account,
            direction='credit', amount__gt=0, asset='USDC_POL',
            provider_data__third_party__transaction_hash__iexact=t.destination_tx_hash)
        for entry in candidates:
            third = entry.provider_data.get('third_party') or {}
            if (third.get('type') == 'CRYPTO' and str(third.get('crypto_network', '')).upper() == 'POLYGON'
                    and (entry.provider_data.get('operation') or {}).get('type') in {None, 'PAYIN', 'CREDIT'}):
                matches.append(entry)
    else:
        candidates = LedgerEntry.objects.filter(
            provider='cobre', financial_account=account, direction='credit', amount__gt=0,
            asset__in=['USD_STABLE', 'USD'],
        ).filter(Q(provider_data__content__metadata__tracking_key__iexact=t.destination_tx_hash) |
                 Q(provider_data__metadata__tracking_key__iexact=t.destination_tx_hash))
        for entry in candidates:
            content = entry.provider_data.get('content') or entry.provider_data
            meta = content.get('metadata') or {}
            if (content.get('type') == 'global_credit' and content.get('credit_debit_type') == 'credit'
                    and meta.get('chain') == 'polygon' and meta.get('token') == 'usdc'
                    and str(meta.get('beneficiary_wallet_address', '')).lower() == q.destination_address):
                matches.append(entry)
    if len(matches) != 1:
        return
    with transaction.atomic():
        locked = PaymentBridgeTransfer.objects.select_for_update().get(pk=t.pk)
        if locked.provider_credit_id:
            return
        locked.provider_credit = matches[0]
        locked.save(update_fields=['provider_credit', 'updated_at'])
        flow = q.money_flow
        flow.status = 'succeeded'
        flow.metadata = dict(flow.metadata, stage='provider_credited', provider_credit_id=str(matches[0].internal_id),
                             provider_credit_asset=matches[0].asset, provider_credit_amount=str(matches[0].amount))
        flow.save(update_fields=['status', 'metadata', 'updated_at'])
        t.provider_credit = matches[0]
