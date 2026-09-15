"""Relay status locates receipts; canonical receipts prove delivery/refund."""
import re
import time

from .relay import RelayClient, RelayError, CHAINS
from .allbridge_next import NextError
from . import bridge_chain as chain


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
    except NextError:
        if int(time.time()) <= transfer.deadline + 3600:
            raise
        transfer.status, transfer.failure_code = 'needs_review', 'relay_settlement_delayed'
    # A success status without final receipts is still unresolved settlement.
    if transfer.status == 'bridging' and int(time.time()) > transfer.deadline + 3600:
        transfer.status, transfer.failure_code = 'needs_review', 'relay_settlement_delayed'


def _reconcile_relay(transfer, *, client=None):
    q = transfer.quote
    status = (client or RelayClient()).status(transfer.binding['request_id'])
    state = status.get('status')
    if state not in {'success', 'refund', 'failure'}:
        if state not in {'waiting', 'depositing', 'pending', 'submitted', 'delayed'}:
            raise RelayError('Unknown Relay settlement status')
        if int(time.time()) > transfer.deadline + 3600:
            transfer.status, transfer.failure_code = 'needs_review', 'relay_settlement_delayed'
        return
    if state == 'failure':
        transfer.status, transfer.failure_code = 'needs_review', 'relay_failure'
        return
    if (status.get('originChainId') != CHAINS[q.source_token_id]
            or status.get('destinationChainId') != CHAINS[q.destination_token_id]):
        raise RelayError('Relay status chain mismatch')
    if transfer.source_tx_hash.lower() not in hashes(status.get('inTxHashes')):
        raise RelayError('Relay status does not include the funded transaction')
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
        'transaction_hashes': outputs, 'token_id': token, 'recipient': recipient,
        'received_units': str(total),
    })
    if state == 'refund':
        # Partial refunds (e.g. execution fees retained) require explicit review.
        transfer.status = 'refunded' if total == int(q.amount_units) else 'needs_review'
        transfer.failure_code = 'relay_refunded' if transfer.status == 'refunded' else 'relay_refund_amount_mismatch'
    elif total < int(transfer.amount_out_min):
        transfer.status, transfer.failure_code = 'needs_review', 'destination_amount_mismatch'
    else:
        transfer.status, transfer.failure_code = 'delivered', ''
        transfer.actual_out_units, transfer.destination_tx_hash = str(total), outputs[0]
