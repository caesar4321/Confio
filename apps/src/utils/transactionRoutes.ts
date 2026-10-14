import { unifiedTransactionReceipt } from './transactionReceipt';
import type { UnifiedReceiptSource, TransactionDetailData, TransactionDetailParams, TransactionDetailType, TransactionReceiptParams } from '../types/transactionReceipt';

const DETAIL_TYPES: readonly string[] = ['received', 'sent', 'unknown', 'exchange', 'payment', 'deposit', 'withdrawal', 'conversion', 'ramp', 'reward', 'presale', 'payroll', 'humanitarian'];
const decimal = (value: unknown): string | undefined => typeof value === 'number' && Number.isFinite(value) ? String(value) : text(value);
const text = (value: unknown): string | undefined => typeof value === 'string' && value.trim() ? value.trim() : undefined;

/** Database operation UUIDs and chain hashes are different namespaces. */
export function operationUuid(...values: unknown[]): string | undefined {
  return values.map(text).find(value => value && /^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.test(value));
}

export function transactionTimestamp(...values: unknown[]): string | undefined {
  return values.map(value => typeof value === 'number'
    ? (Number.isFinite(new Date(value).getTime()) ? new Date(value).toISOString() : undefined) : text(value))
    .find(value => value && Number.isFinite(Date.parse(value)));
}

/** Compatibility boundary for persisted notifications and source API records.
 * Preserve source-specific fields; normalize common fields once before navigation.
 * id is an explicitly supplied SOURCE ID. Unified rows must use historyReceiptRoute.
 */
export function normalizeTransactionPayload(source: Record<string, unknown>): TransactionDetailData {
  const internalId = operationUuid(source.internalId, source.internal_id, source.verificationId,
    source.paymentTransactionId, source.payment_transaction_id, source.transaction_id, source.transactionId, source.id);
  const sourceId = decimal(source.id);
  const hash = [source.transactionHash, source.transaction_hash, source.hash, source.txid]
    .map(text).find(value => value && !operationUuid(value) && !/^\d+$/.test(value) && !/^#?pending$/i.test(value));
  const createdAt = transactionTimestamp(source.createdAt, source.created_at, source.timestamp, source.executedAt, source.executed_at);
  return {
    ...source,
    id: internalId || (sourceId && /^\d+$/.test(sourceId) ? sourceId : undefined),
    internalId,
    internal_id: internalId,
    createdAt,
    created_at: createdAt,
    timestamp: createdAt,
    amount: decimal(source.amount),
    currency: text(source.currency) || text(source.tokenType) || text(source.token_type),
    status: text(source.status),
    from: text(source.from) || text(source.senderName) || text(source.sender_name),
    to: text(source.to) || text(source.recipientName) || text(source.recipient_name),
    fromPhone: text(source.fromPhone) || text(source.senderPhone) || text(source.sender_phone),
    toPhone: text(source.toPhone) || text(source.recipientPhone) || text(source.recipient_phone),
    feeAmount: decimal(source.feeAmount) || decimal(source.fee_amount),
    feeBps: typeof (source.feeBps ?? source.fee_bps) === 'number' ? (source.feeBps ?? source.fee_bps) as number : undefined,
    netAmount: decimal(source.netAmount) || decimal(source.net_amount),
    hash,
    transactionHash: hash,
    transaction_hash: hash,
  };
}

export function transactionPerspective(type: string, source: Record<string, unknown>): 'sent' | 'received' | 'unknown' {
  if (type === 'sent' || type === 'received') return type;
  if (source.direction === 'sent' || source.direction === 'received') return source.direction;
  const notification = text(source.notification_type) || text(source.notificationType) || '';
  if (['SEND_RECEIVED', 'INVITE_RECEIVED', 'SEND_FROM_EXTERNAL', 'PAYMENT_RECEIVED', 'PAYROLL_RECEIVED', 'INVOICE_PAID'].includes(notification)) return 'received';
  if (['SEND_SENT', 'SEND_INVITATION_SENT', 'PAYMENT_SENT', 'PAYROLL_SENT'].includes(notification)) return 'sent';
  const amount = decimal(source.amount);
  if (amount?.startsWith('-')) return 'sent';
  if (amount?.startsWith('+')) return 'received';
  return 'unknown';
}

/** Apply the viewer's direction to authoritative gross amounts, including refetches. */
export function receiptAmount(amount: unknown, type: string, source: Record<string, unknown>): string | undefined {
  const value = decimal(amount);
  if (!value || !['send', 'sent', 'received', 'payment', 'payroll'].includes(type)) return value;
  const direction = transactionPerspective(type, source);
  if (direction === 'unknown') return value;
  return `${direction === 'sent' ? '-' : '+'}${value.replace(/^[+-]/, '')}`;
}

export function transactionDetailRoute(input: { transactionType: string; transactionData: Record<string, unknown> }): TransactionDetailParams {
  const raw = input.transactionType.toLowerCase();
  const perspective = transactionPerspective(raw, input.transactionData);
  const type = raw === 'send' ? (perspective === 'unknown' ? 'sent' : perspective) : DETAIL_TYPES.includes(raw) ? raw as TransactionDetailType : 'unknown';
  const data = normalizeTransactionPayload(input.transactionData);
  return {transactionType: type, transactionData: {...data,
    amount: receiptAmount(data.amount, type, input.transactionData),
    type, transaction_type: type, transactionType: type}};
}

export function transactionReceiptRoute(input: TransactionReceiptParams): TransactionReceiptParams {
  const transaction = normalizeTransactionPayload(input.transaction);
  return { ...input, transaction: {
    ...transaction,
    status: transaction.status || 'pending',
    date: transactionTimestamp(transaction.createdAt, input.transaction.date),
    verificationId: operationUuid(input.transaction.verificationId, transaction.internalId),
  }};
}

export function paymentSuccessDetailRoute(source: Record<string, unknown>): TransactionDetailParams {
  const amount = text(source.amount);
  return transactionDetailRoute({transactionType: 'payment', transactionData: {
    ...source,
    id: operationUuid(source.internalId, source.internal_id),
    amount: amount ? `-${amount.replace(/^[+-]/, '')}` : undefined,
    to: text(source.merchant) || text(source.recipient),
    merchantName: text(source.merchant) || text(source.recipient),
    status: text(source.status) || 'pending',
  }});
}

/** A ramp history item is a unified row, not a source transaction record. */
export function unifiedDetailRoute(input: {transactionType: string; transactionData: UnifiedReceiptSource & Record<string, unknown>}): TransactionDetailParams {
  const route = transactionDetailRoute(input);
  return {...route, transactionData: {...route.transactionData, ...unifiedTransactionReceipt(input.transactionData)}};
}
