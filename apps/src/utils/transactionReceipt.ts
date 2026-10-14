import type { ReceiptMetadata, UnifiedReceiptSource, TransactionDetailData, TransactionDetailParams, TransactionDetailType } from '../types/transactionReceipt';

export function transferDirection(direction: unknown): 'sent' | 'received' | 'unknown' {
  return direction === 'sent' || direction === 'received' ? direction : 'unknown';
}

/** Carry authoritative metadata through list formatting without using the list row ID. */
export function unifiedTransactionReceipt(tx: UnifiedReceiptSource): ReceiptMetadata {
  const createdAt = tx.createdAt && Number.isFinite(Date.parse(tx.createdAt)) ? tx.createdAt : undefined;
  return {
    // The unified row PK is NOT a SendTransaction PK. Refetch by its operation UUID.
    id: tx.internalId || undefined,
    internalId: tx.internalId || undefined,
    createdAt,
    timestamp: createdAt,
    direction: transferDirection(tx.direction),
    fromPhone: (tx.senderUser?.phoneKey || tx.senderPhone) ?? undefined,
    toPhone: (tx.counterpartyUser?.phoneKey || tx.counterpartyPhone) ?? undefined,
    senderUser: tx.senderUser ?? undefined,
    recipientUser: tx.counterpartyUser ?? undefined,
    senderBusiness: tx.senderBusiness ?? undefined,
    recipientBusiness: tx.counterpartyBusiness ?? undefined,
    feeAmount: tx.feeAmount ?? undefined,
    feeBps: tx.feeBps ?? undefined,
    netAmount: tx.netAmount ?? undefined,
  };
}

/** Presentation may add labels, but cannot overwrite source IDs, dates or identities. */
export function historyReceiptRoute(
  type: TransactionDetailType,
  metadata: ReceiptMetadata,
  presentation: TransactionDetailData & { amount: string; currency: string; status: string },
): TransactionDetailParams {
  return { transactionType: type, transactionData: { ...presentation, ...metadata, type } };
}
