from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from eth_abi import decode
from eth_utils import keccak

from blockchain.models import PAYMENT_BATCH_KINDS, SponsoredBatch
from payments.bsc_flow import invoice_id_bytes32, payment_fee_wei

from .models import BillingPayment, BillingPaymentStatus, SettlementLeg


PAYMENT_MADE_V3 = 'PaymentMade(bytes32,address,address,address,uint256,uint256)'
PAYMENT_MADE_V4 = (
    'PaymentMade(bytes32,address,address,address,uint256,uint256,bool,uint256)'
)
PAYMENT_MADE_TOPICS = {
    '0x' + keccak(text=PAYMENT_MADE_V3).hex(): 'v3',
    '0x' + keccak(text=PAYMENT_MADE_V4).hex(): 'v4-cusd-routing',
}


class SettlementEvidenceError(ValueError):
    """The finalized receipt contradicts the payment we intended to settle."""


@dataclass(frozen=True)
class ParsedPaymentMade:
    contract_version: str
    contract_address: str
    invoice_id_bytes32: str
    payer_address: str
    receiver_address: str
    input_token_address: str
    gross_units: int
    fee_units: int
    routed: bool
    output_units: int
    transaction_hash: str
    block_number: int
    block_hash: str
    transaction_index: int
    log_index: int

    @property
    def input_net_units(self):
        return self.gross_units - self.fee_units


def _hex_int(value, field):
    try:
        if isinstance(value, int):
            return value
        return int(value, 16)
    except (TypeError, ValueError) as exc:
        raise SettlementEvidenceError(f'invalid {field}') from exc


def _topic_address(topic, field):
    raw = (topic or '').lower().removeprefix('0x')
    if len(raw) != 64 or any(ch not in '0123456789abcdef' for ch in raw):
        raise SettlementEvidenceError(f'invalid {field}')
    return '0x' + raw[-40:]


def _normalized_hash(value, field):
    normalized = (value or '').lower()
    if (len(normalized) != 66 or not normalized.startswith('0x')
            or any(ch not in '0123456789abcdef' for ch in normalized[2:])):
        raise SettlementEvidenceError(f'invalid {field}')
    return normalized


def _token_metadata(address):
    from cusd_plus.sponsor_7702 import USDT_BSC

    candidates = (
        ('CUSD_PLUS', getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '')),
        ('CUSD', getattr(settings, 'CUSD_VAULT_ADDRESS', '')),
        ('USDT', USDT_BSC),
        ('CONFIO', getattr(settings, 'BSC_CONFIO_TOKEN_ADDRESS', '')),
    )
    normalized = (address or '').lower()
    for symbol, configured in candidates:
        if configured and normalized == configured.lower():
            # All assets accepted by the current BSC Pay rail use 18 base
            # decimals. This is explicit evidence metadata, not display math.
            return symbol, 18
    raise SettlementEvidenceError('payment event used an unconfigured token')


def _parse_candidate(log, receipt, batch):
    if log.get('removed'):
        raise SettlementEvidenceError('PaymentMade log was removed')
    # The immutable leg must describe the same finalized receipt, not a
    # provider's stale log from another block. Once persisted it cannot be
    # overwritten on retry, so reject contradictory metadata up front.
    for field in ('transactionHash', 'blockHash', 'blockNumber', 'transactionIndex'):
        if field in log and field in receipt:
            if field in ('blockNumber', 'transactionIndex'):
                matches = _hex_int(log[field], field) == _hex_int(receipt[field], field)
            else:
                matches = _normalized_hash(log[field], field) == _normalized_hash(receipt[field], field)
            if not matches:
                raise SettlementEvidenceError(f'PaymentMade receipt {field} mismatch')
    topics = log.get('topics') or []
    if len(topics) != 4:
        raise SettlementEvidenceError('PaymentMade has invalid indexed fields')
    topic0 = (topics[0] or '').lower()
    version = PAYMENT_MADE_TOPICS.get(topic0)
    if version is None:
        raise SettlementEvidenceError('unknown PaymentMade version')

    try:
        raw = bytes.fromhex((log.get('data') or '0x').removeprefix('0x'))
        if version == 'v3':
            token, gross, fee = decode(
                ['address', 'uint256', 'uint256'], raw)
            routed, output = False, int(gross) - int(fee)
        else:
            token, gross, fee, routed, routed_out = decode(
                ['address', 'uint256', 'uint256', 'bool', 'uint256'], raw)
            if not routed and routed_out:
                raise SettlementEvidenceError(
                    'unrouted PaymentMade has a routed output')
            output = int(routed_out) if routed else int(gross) - int(fee)
    except Exception as exc:  # noqa: BLE001 - malformed provider evidence
        raise SettlementEvidenceError('PaymentMade data is malformed') from exc

    tx_hash = _normalized_hash(
        log.get('transactionHash') or receipt.get('transactionHash') or batch.tx_hash,
        'transaction hash',
    )
    return ParsedPaymentMade(
        contract_version=version,
        contract_address=(log.get('address') or '').lower(),
        invoice_id_bytes32=_normalized_hash(topics[1], 'invoice id'),
        payer_address=_topic_address(topics[2], 'payer'),
        receiver_address=_topic_address(topics[3], 'merchant'),
        input_token_address=token.lower(),
        gross_units=int(gross),
        fee_units=int(fee),
        routed=bool(routed),
        output_units=int(output),
        transaction_hash=tx_hash,
        block_number=_hex_int(
            log.get('blockNumber') or receipt.get('blockNumber'), 'block number'),
        block_hash=_normalized_hash(
            log.get('blockHash') or receipt.get('blockHash'), 'block hash'),
        transaction_index=_hex_int(
            log.get('transactionIndex') or receipt.get('transactionIndex') or '0x0',
            'transaction index',
        ),
        log_index=_hex_int(log.get('logIndex'), 'log index'),
    )


def parse_payment_made(receipt, batch, legacy_payment):
    """Return the one authoritative Pay event, rejecting absence/ambiguity."""
    if receipt.get('status') != '0x1':
        raise SettlementEvidenceError('payment receipt is not successful')
    if ('transactionHash' in receipt
            and _normalized_hash(receipt['transactionHash'], 'transaction hash')
            != (batch.tx_hash or '').lower()):
        raise SettlementEvidenceError('payment receipt transaction hash mismatch')
    pay_contract = (getattr(settings, 'BSC_PAY_CONTRACT_ADDRESS', '') or '').lower()
    if not pay_contract:
        raise SettlementEvidenceError('pay contract is not configured')
    candidates = []
    for log in receipt.get('logs') or []:
        topics = log.get('topics') or []
        if ((log.get('address') or '').lower() == pay_contract
                and topics and (topics[0] or '').lower() in PAYMENT_MADE_TOPICS):
            candidates.append(_parse_candidate(log, receipt, batch))
    if len(candidates) != 1:
        raise SettlementEvidenceError(
            f'expected one PaymentMade event, found {len(candidates)}')
    event = candidates[0]

    expected_invoice = invoice_id_bytes32(legacy_payment.invoice.internal_id).lower()
    expected = {
        'invoice id': (event.invoice_id_bytes32, expected_invoice),
        'payer': (event.payer_address, (legacy_payment.payer_address or '').lower()),
        'merchant': (
            event.receiver_address, (legacy_payment.merchant_address or '').lower()),
        'transaction hash': (event.transaction_hash, (batch.tx_hash or '').lower()),
    }
    for field, (actual, wanted) in expected.items():
        if not wanted or actual != wanted:
            raise SettlementEvidenceError(f'PaymentMade {field} mismatch')
    if event.contract_address != pay_contract:
        raise SettlementEvidenceError('PaymentMade contract mismatch')
    if event.fee_units != payment_fee_wei(event.gross_units):
        raise SettlementEvidenceError('PaymentMade fee mismatch')
    if event.gross_units <= event.fee_units:
        raise SettlementEvidenceError('PaymentMade has no receiver value')
    if event.routed and event.output_units <= 0:
        raise SettlementEvidenceError('routed PaymentMade has no output')
    expected_routing = bool(
        (legacy_payment.blockchain_data or {}).get('v4_redeem'))
    if event.routed != expected_routing:
        raise SettlementEvidenceError('PaymentMade routing mismatch')
    return event


def _leg_values(event, billing_payment):
    input_symbol, input_decimals = _token_metadata(event.input_token_address)
    expected_symbol = billing_payment.settlement_asset.upper()
    if input_symbol != expected_symbol:
        raise SettlementEvidenceError('PaymentMade settlement asset mismatch')
    if input_decimals != billing_payment.settlement_decimals:
        raise SettlementEvidenceError('PaymentMade settlement decimals mismatch')
    if event.gross_units != int(billing_payment.gross_units):
        raise SettlementEvidenceError('PaymentMade gross mismatch')
    if event.fee_units != int(billing_payment.fee_units):
        raise SettlementEvidenceError('PaymentMade stored fee mismatch')
    if event.input_net_units != int(billing_payment.receiver_net_units):
        raise SettlementEvidenceError('PaymentMade stored net mismatch')

    if event.routed:
        output_address = (getattr(settings, 'CUSD_VAULT_ADDRESS', '') or '').lower()
        if not output_address:
            raise SettlementEvidenceError('routed output token is not configured')
        output_symbol, output_decimals = _token_metadata(output_address)
    else:
        output_address = event.input_token_address
        output_symbol, output_decimals = input_symbol, input_decimals
    return {
        'billing_payment': billing_payment,
        'chain_id': int(getattr(settings, 'BSC_CHAIN_ID', 56)),
        'contract_version': event.contract_version,
        'contract_address': event.contract_address,
        'invoice_id_bytes32': event.invoice_id_bytes32,
        'payer_address': event.payer_address,
        'receiver_address': event.receiver_address,
        'input_token_address': event.input_token_address,
        'input_token_symbol': input_symbol,
        'input_token_decimals': input_decimals,
        'gross_units': event.gross_units,
        'fee_token_address': event.input_token_address,
        'fee_units': event.fee_units,
        'output_token_address': output_address,
        'output_token_symbol': output_symbol,
        'output_token_decimals': output_decimals,
        'output_units': event.output_units,
        'routed': event.routed,
        'receiver_net_units': event.input_net_units,
        'transaction_hash': event.transaction_hash,
        'block_number': event.block_number,
        'block_hash': event.block_hash,
        'transaction_index': event.transaction_index,
        'log_index': event.log_index,
    }


@transaction.atomic
def persist_finalized_payment_settlement(*, batch_id, receipt):
    """Persist exact finalized Pay evidence before making a batch terminal.

    Legacy payments without a BillingPayment remain supported and return
    None. A billing-linked payment must match the event byte-for-byte.
    """
    batch = SponsoredBatch.objects.select_for_update().get(id=batch_id)
    if batch.kind not in PAYMENT_BATCH_KINDS or batch.source_id is None:
        return None
    billing_payment = (
        BillingPayment.objects.select_for_update()
        .select_related('legacy_payment__invoice')
        .filter(legacy_payment_id=batch.source_id)
        .first()
    )
    if billing_payment is None:
        return None
    if billing_payment.status not in (
            BillingPaymentStatus.PROCESSING, BillingPaymentStatus.CONFIRMED):
        raise SettlementEvidenceError(
            f'billing payment cannot accept settlement in {billing_payment.status}')

    event = parse_payment_made(receipt, batch, billing_payment.legacy_payment)
    values = _leg_values(event, billing_payment)
    expected_asset = {
        'pay_cusd_plus': 'CUSD_PLUS',
        'pay_cusd': 'CUSD',
        'pay_usdt': 'USDT',
        'pay_confio': 'CONFIO',
    }.get(batch.kind)
    if values['input_token_symbol'] != expected_asset:
        raise SettlementEvidenceError('PaymentMade token does not match batch kind')
    lookup = {
        'chain_id': values['chain_id'],
        'transaction_hash': values['transaction_hash'],
        'log_index': values['log_index'],
    }
    leg, created = SettlementLeg.objects.get_or_create(
        **lookup, defaults=values)
    if not created:
        expected = {key: value for key, value in values.items()
                    if key != 'billing_payment'}
        for field, value in expected.items():
            actual = getattr(leg, field)
            if str(actual).lower() != str(value).lower():
                raise SettlementEvidenceError(
                    f'existing settlement evidence differs at {field}')
        if leg.billing_payment_id != billing_payment.id:
            raise SettlementEvidenceError(
                'settlement event already belongs to another payment')
    return leg
