export type TransactionDetailType = 'received' | 'sent' | 'unknown' | 'exchange' | 'payment' | 'deposit' | 'withdrawal' | 'conversion' | 'ramp' | 'reward' | 'presale' | 'payroll' | 'humanitarian';

export interface ReceiptParty {
  id: string;
  phoneKey?: string | null;
  firstName?: string | null;
  lastName?: string | null;
  name?: string | null;
  username?: string | null;
  statusTier?: string | null;
  isReferralVerified?: boolean;
}

export interface UnifiedReceiptSource {
  id?: string;
  internalId?: string | null;
  createdAt?: string | null;
  direction?: string | null;
  senderUser?: ReceiptParty | null;
  counterpartyUser?: ReceiptParty | null;
  senderBusiness?: ReceiptParty | null;
  counterpartyBusiness?: ReceiptParty | null;
  senderPhone?: string | null;
  counterpartyPhone?: string | null;
  feeAmount?: string | null;
  feeBps?: number | null;
  netAmount?: string | null;
}

export interface ReceiptMetadata {
  // id is the source operation UUID, never the unified history row's database ID.
  id: string | undefined;
  internalId: string | undefined;
  createdAt: string | undefined;
  timestamp: string | undefined;
  direction: 'sent' | 'received' | 'unknown';
  fromPhone: string | undefined;
  toPhone: string | undefined;
  senderUser: ReceiptParty | undefined;
  recipientUser: ReceiptParty | undefined;
  senderBusiness: ReceiptParty | undefined;
  recipientBusiness: ReceiptParty | undefined;
  feeAmount: string | undefined;
  feeBps: number | undefined;
  netAmount: string | undefined;
}

// Legacy producers can supply their extra fields while common receipt fields are checked.
export interface TransactionDetailData extends Partial<ReceiptMetadata> {
  type?: TransactionDetailType;
  amount?: string;
  currency?: string;
  from?: string;
  to?: string;
  date?: string;
  time?: string;
  status?: string;
  hash?: string;
  [field: string]: unknown;
}
export interface TransactionDetailParams {
  transactionType: TransactionDetailType;
  transactionData?: TransactionDetailData;
}

export interface TransactionReceiptParams {
  transaction: TransactionDetailData;
  type?: 'payroll' | 'payment' | 'transfer';
}
