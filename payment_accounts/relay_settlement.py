"""Relay status locates receipts; canonical receipts prove delivery/refund."""
import re
import time

from .relay import RelayClient, RelayError, CHAINS, PROTOCOL_CHAINS, refund_gas_allowance
from .allbridge_next import TOKENS, NextError
from . import bridge_chain as chain
from .relay_lookups import Held


def hashes(values):
    if not isinstance(values, list) or len(values) > 5:
        raise RelayError('Invalid Relay transaction evidence')
    if any(not isinstance(v, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', v) for v in values):
        raise RelayError('Invalid Relay transaction hash')
    result = [v.lower() for v in values]
    if len(set(result)) != len(result):
        raise RelayError('Duplicate Relay transaction evidence')
    return result


def reconcile_relay(transfer, *, client=None):
    try:
        _reconcile_relay(transfer, client=client)
    except NextError as exc:
        if _contract(transfer) and (isinstance(exc, Held) or getattr(exc, 'status_code', None) == 429):
            # A rate limit says nothing about the transfer: never a delay.
            from .contract_funding import lookup_held
            lookup_held(transfer)
            return
        if int(time.time()) <= transfer.deadline + 3600:
            raise
        transfer.status, transfer.failure_code = 'needs_review', 'relay_settlement_delayed'
    # A success status without final receipts is still unresolved settlement.
    if transfer.status == 'bridging' and int(time.time()) > transfer.deadline + 3600:
        transfer.status, transfer.failure_code = 'needs_review', 'relay_settlement_delayed'


def _contract(transfer):
    """The contract-funding binding of payment_accounts' own bridges and of a
    contract-funded ramps send (ramps.pagoasap_send.settle); {} for every
    caller a wallet funded."""
    if getattr(transfer, 'funding_mode', None) != 'contract':
        return {}
    return (getattr(transfer, 'binding', None) or {}).get('contract_funding') or {}


def _funded(transfer):
    contract = _contract(transfer)
    return max(int(transfer.quote.amount_units), int(contract.get('funded_units') or 0))


def _source_evidence(transfer, inputs):
    """Deposit routes report the sweep, not the user's funding transaction.
    The units that were collected, or 0 while that is not proven."""
    if transfer.source_tx_hash.lower() in inputs:
        return _funded(transfer)
    q = transfer.quote
    try:
        payment = transfer.binding['response']['protocol']['v2']['paymentDetails']
        depository = payment['depository']
        valid = (len(inputs) == 1
                 and payment['chainId'] == PROTOCOL_CHAINS[q.source_token_id]
                 and payment['currency'].lower() == TOKENS[q.source_token_id][0].lower()
                 and str(payment['amount']) == str(q.amount_units)
                 and re.fullmatch(r'0x[0-9a-fA-F]{40}', depository)
                 and int(depository, 16) != 0)
    except (KeyError, TypeError, AttributeError, ValueError):
        valid = False
    if not valid:
        raise RelayError('Relay collection binding is invalid')
    source_chain = q.source_token_id.split(':')[0]
    funding = chain.final_receipt(source_chain, transfer.source_tx_hash)
    collection = chain.final_receipt(source_chain, inputs[0])
    if funding is None or collection is None:
        return 0
    # Canonical receipts must show funding before collection, including when
    # both transactions share a block. Never match an unrelated earlier sweep.
    try:
        position = lambda r: (int(r['blockNumber'], 16), int(r['transactionIndex'], 16))
        ordered = position(collection) > position(funding)
    except (KeyError, TypeError, ValueError):
        raise RelayError('Relay collection ordering is unavailable')
    sender = q.source_address if transfer.funding_mode == 'wallet' else _contract(transfer).get('sender')
    # What the deposit actually received. Exactly the quote, except a
    # contract-funded send (ramps.pagoasap_send) whose already-proven funding
    # carried more (the cUSD vault exits usdtOut >= minUsdtOut): it passes
    # `funded_units`, never below the quote, and the sweep moves that whole
    # balance. Every other caller has no such attribute and is unchanged.
    funded = int(q.amount_units)
    extra = getattr(transfer, 'funded_units', None) or _contract(transfer).get('funded_units')
    if transfer.funding_mode == 'contract' and extra is not None and str(extra).isdigit() \
            and int(extra) > funded:
        funded = int(extra)
    if not ordered or chain.received_units(funding, q.source_token_id, transfer.deposit_address,
                                           sender=sender) != funded:
        raise RelayError('Relay collection does not match funded deposit')
    collected = chain.received_units(collection, q.source_token_id, depository, sender=transfer.deposit_address)
    # A contract-funded transfer is identified by the request Relay
    # bound to our deposit's hash, and its sweep takes the address's whole
    # balance: anyone's dust makes it more, never less. Every other caller is exact.
    if collected < funded or (collected > funded and not _contract(transfer)):
        raise RelayError('Relay collection does not match funded deposit')
    return collected


def _reconcile_relay(transfer, *, client=None):
    q = transfer.quote
    client = client or RelayClient()
    contract = _contract(transfer)
    if contract:
        # A single-use address takes whoever pays first, and the quote-time
        # request can stay 'waiting' after a regenerated one filled. So the
        # request is the one Relay binds to OUR deposit's hash, and no other.
        from .contract_funding import follow_request
        found = follow_request(transfer, client)
        if found is None:
            return  # not seen by Relay yet; the caller escalates after the deadline
        request_id, status = found
    else:
        request_id = transfer.binding['request_id']
        status = client.status(request_id)
    state = status.get('status')
    if contract:
        from .contract_funding import needs_manual_refund, refund_needs_a_human
        if needs_manual_refund(status):
            refund_needs_a_human(transfer, request_id, status['refundFailReason'])
            return
    if contract and state == 'failure':
        return  # not final (Relay moves it to pending or refund); escalates after the deadline
    if state not in {'success', 'refund', 'failure'}:
        if state not in {'waiting', 'depositing', 'pending', 'submitted', 'delayed'}:
            raise RelayError('Unknown Relay settlement status')
        if int(time.time()) > transfer.deadline + 3600:
            transfer.status, transfer.failure_code = 'needs_review', 'relay_settlement_delayed'
        return
    if state == 'failure':
        transfer.status, transfer.failure_code = 'needs_review', 'relay_failure'
        return
    destinations = {CHAINS[q.destination_token_id]}
    if contract and state == 'refund':
        # A later deposit to a single-use address has a request of its own
        # that only refunds, on the origin chain.
        destinations.add(CHAINS[q.source_token_id])
    if (status.get('originChainId') != CHAINS[q.source_token_id]
            or status.get('destinationChainId') not in destinations):
        raise RelayError('Relay status chain mismatch')
    inputs = hashes(status.get('inTxHashes'))
    collected = _source_evidence(transfer, inputs)
    if not collected:
        return
    outputs = hashes(status.get('txHashes'))
    if not outputs:
        raise RelayError('Relay settlement evidence is missing')
    if state == 'success' and q.destination_token_id == 'POL:USDC' and len(outputs) != 1:
        transfer.status, transfer.failure_code = 'needs_review', 'split_provider_delivery'
        return
    token = q.destination_token_id if state == 'success' else q.source_token_id
    recipient = q.destination_address if state == 'success' else q.source_address
    total = 0
    for tx_hash in outputs:
        receipt = chain.final_receipt(token.split(':')[0], tx_hash)
        if receipt is None:
            return
        total += chain.received_units(receipt, token, recipient)
    transfer.binding = dict(transfer.binding, settlement_evidence={
        'status': state, 'source_tx_hash': transfer.source_tx_hash,
        'origin_transaction_hashes': inputs,
        'transaction_hashes': outputs, 'token_id': token, 'recipient': recipient,
        'received_units': str(total),
        **({'request_id': request_id, 'collected_units': str(collected)} if contract else {}),
    })
    if state == 'refund':
        # The receipts above already prove this returned to the user's own
        # source wallet. Relay deducts refund gas by documented design, so
        # demanding exact equality marked every refund needs_review, and that
        # status blocks the wallet from starting any further bridge. Allow the
        # gas deduction; a genuinely short return still requires review.
        deposited = _funded(transfer)
        shortfall = deposited - total
        # A combined sweep returns at most what it collected.
        most = collected if contract else deposited
        complete = total > 0 and total <= most and shortfall <= refund_gas_allowance(q.source_token_id)
        transfer.status = 'refunded' if complete else 'needs_review'
        transfer.failure_code = 'relay_refunded' if complete else 'relay_refund_amount_mismatch'
    elif total < int(transfer.amount_out_min):
        transfer.status, transfer.failure_code = 'needs_review', 'destination_amount_mismatch'
    else:
        transfer.status, transfer.failure_code = 'delivered', ''
        transfer.actual_out_units, transfer.destination_tx_hash = str(total), outputs[0]
