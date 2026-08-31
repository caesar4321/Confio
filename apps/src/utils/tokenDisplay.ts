// Display names for the tokens that appear on receipts, success screens and
// transaction details.
//
// This existed as five identical private copies across the payment/receipt
// screens, none of which knew about the BSC tokens — so a cUSD+ receipt showed
// the raw wire value "CUSD_PLUS" as its denomination. One table, one place to
// add the next token.

const TOKEN_LABELS: Record<string, string> = {
  CUSD: 'cUSD',
  CUSD_BSC: 'cUSD',
  CUSD_PLUS: 'cUSD+',
  CONFIO: 'CONFIO',
  USDC: 'USDC',
  USDT: 'USDT',
};

/**
 * Wire value ("CUSD_PLUS") → what a user should read ("cUSD+").
 *
 * Unknown tokens pass through unchanged: a new server-side token shows its
 * raw symbol rather than vanishing from a receipt. Already-formatted input
 * ("cUSD+") also passes through, so this is safe to apply twice.
 */
export const formatTokenLabel = (currency?: string | null): string => {
  const raw = String(currency ?? '').trim();
  if (!raw) return '';
  const key = raw.toUpperCase().replace(/[\s-]/g, '_');
  return TOKEN_LABELS[key] ?? raw;
};

/** Dollar-denominated tokens take a "$"; CONFIO is a token COUNT and never does. */
export const isDollarToken = (currency?: string | null): boolean =>
  formatTokenLabel(currency) !== 'CONFIO';

/**
 * The full amount string for a receipt: "$12.34 cUSD+" or "10 CONFIO".
 */
export const formatTokenAmount = (
  amount: string | number,
  currency?: string | null,
): string => {
  const label = formatTokenLabel(currency);
  const value = String(amount ?? '').trim();
  return isDollarToken(currency) ? `$${value} ${label}`.trim() : `${value} ${label}`.trim();
};

/**
 * The token pair behind each conversion type, and which side the viewer's
 * account receives.
 *
 * This lived as ~8 copies of the same two-arm ternary across the list mapper
 * and the detail screen, all of which knew only the legacy USDC pair. A
 * savings conversion matched no arm, so it fell through to `undefined` and
 * rendered as a bare "-2.99" with no denomination at all. One table.
 */
const CONVERSION_PAIRS: Record<string, { from: string; to: string }> = {
  usdc_to_cusd: { from: 'USDC', to: 'cUSD' },
  cusd_to_usdc: { from: 'cUSD', to: 'USDC' },
  to_savings: { from: 'USDT', to: 'cUSD+' },
  from_savings: { from: 'cUSD+', to: 'USDT' },
  usdt_to_cusd: { from: 'USDT', to: 'cUSD' },
  cusd_to_usdt: { from: 'cUSD', to: 'USDT' },
};

export const conversionPair = (
  conversionType?: string | null,
): { from: string; to: string } | undefined =>
  CONVERSION_PAIRS[String(conversionType ?? '').trim().toLowerCase()];

/**
 * True when the conversion ADDS to the account it is being viewed from.
 *
 * A conversion touches two tokens but appears once, in the account holding
 * the destination token — so `to_savings` is money arriving in cUSD+ (+) and
 * `from_savings` is money leaving it (−). Unknown types return false rather
 * than guessing a credit.
 */
export const isConversionIncoming = (conversionType?: string | null): boolean => {
  const key = String(conversionType ?? '').trim().toLowerCase();
  return key === 'usdc_to_cusd' || key === 'to_savings' || key === 'usdt_to_cusd';
};

/**
 * Which token a "send this person money back" action should preselect, given
 * the currency of the transaction being viewed.
 *
 * The route only accepts the three the user can CHOOSE — there is no 'usdt'
 * send, because a cUSD+ send is a dollar-value send and the server picks the
 * rail (transfer vs redeem-to-USDT) from the recipient. So a USDT receipt maps
 * to 'cusd_plus'. Call sites used to guess `=== 'cusd' ? 'cusd' : 'confio'`,
 * which offered to send CONFIO after receiving dollars.
 */
export type SendTokenParam = 'cusd' | 'confio' | 'cusd_plus';

export const sendTokenParamFor = (currency?: string | null): SendTokenParam => {
  switch (formatTokenLabel(currency).toUpperCase()) {
    case 'CONFIO':
      return 'confio';
    case 'CUSD':
    // USDC is the Algorand-rail dollar and auto-converts into cUSD, so the
    // equivalent send is cUSD — same chain, same money.
    case 'USDC':
      return 'cusd';
    case 'CUSD+':
    case 'USDT':
      return 'cusd_plus';
    default:
      // Unknown/absent: the primary dollar is the safe default — never CONFIO,
      // which is a governance token and not what anyone just received.
      return 'cusd_plus';
  }
};

/** Tokens that settle on BNB Smart Chain rather than Algorand. */
const BSC_TOKENS = new Set(['CUSD_BSC', 'CUSD_PLUS', 'CUSD+', 'USDT']);

/**
 * Which block explorer can actually show this transaction.
 *
 * Every call site hardcoded Pera (Algorand), so a cUSD+/USDT transaction
 * linked to an explorer that has never heard of its hash. The token decides;
 * the hash SHAPE is the fallback when the token is missing or unfamiliar
 * (an EVM hash is 0x + 64 hex, an Algorand txid never is).
 */
export const explorerFor = (
  tokenLabel?: string | null,
  hash?: string | null,
): { name: string; base: string } => {
  const token = String(tokenLabel ?? '').trim().toUpperCase();
  const looksEvm = /^0x[0-9a-fA-F]{64}$/.test(String(hash ?? '').trim());
  if (BSC_TOKENS.has(token) || looksEvm) {
    return { name: 'BscScan', base: 'https://bscscan.com' };
  }
  return {
    name: 'Pera Explorer',
    base: __DEV__ ? 'https://testnet.explorer.perawallet.app' : 'https://explorer.perawallet.app',
  };
};

/** Full explorer URL for a transaction, or null when there is no hash yet. */
export const explorerTxUrl = (
  tokenLabel?: string | null, hash?: string | null,
): string | null => {
  const h = String(hash ?? '').trim();
  if (!h) return null;
  return `${explorerFor(tokenLabel, h).base}/tx/${encodeURIComponent(h)}`;
};

type ReceiptUser = {
  firstName?: string | null;
  lastName?: string | null;
  username?: string | null;
  phone?: string | null;
  phoneCountry?: string | null;
  phoneNumber?: string | null;
};

const pickReceiptText = (...values: unknown[]): string => {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
};

const GENERIC_RECEIPT_IDENTITIES = new Set([
  'billetera externa',
  'external wallet',
  'remitente',
  'destinatario',
  'usuario',
  'desconocido',
  'contacto',
]);

const isFullWalletAddress = (value: string): boolean =>
  /^0x[0-9a-f]{40}$/i.test(value) ||
  /^[A-Z2-7]{58}$/.test(value);

const isLossyWalletIdentity = (value: string): boolean =>
  /^[A-Za-z0-9]{4,}(?:\.\.\.|…)[A-Za-z0-9]*$/.test(value);

const pickReceiptIdentity = (...values: unknown[]): string => {
  let lossyWalletFallback = '';
  for (const value of values) {
    if (typeof value !== 'string') continue;
    const clean = value.trim();
    const normalized = clean.toLowerCase();
    if (!clean || GENERIC_RECEIPT_IDENTITIES.has(normalized)) continue;
    if (/^(?:billetera\s+)?extern[oa]\s*\(/i.test(clean)) continue;
    if (isLossyWalletIdentity(clean)) {
      lossyWalletFallback ||= clean;
      continue;
    }
    return isFullWalletAddress(clean) ? receiptAddressName(clean) : clean;
  }
  return lossyWalletFallback;
};

const receiptUserName = (user?: ReceiptUser | null): string => {
  if (!user) return '';
  const fullName = [user.firstName, user.lastName]
    .filter((value): value is string => typeof value === 'string' && Boolean(value.trim()))
    .map(value => value.trim())
    .join(' ');
  return fullName || pickReceiptText(user.username);
};

const receiptAddressName = (address: unknown): string => {
  if (typeof address !== 'string' || !address.trim()) return '';
  const clean = address.trim();
  if (clean.length <= 16) return clean;
  return `${clean.slice(0, 8)}…${clean.slice(-8)}`;
};

export type TransferReceiptParticipants = {
  senderName: string;
  recipientName: string;
  senderUsername?: string;
  recipientUsername?: string;
  senderPhone?: string;
  recipientPhone?: string;
  senderAddress?: string;
  recipientAddress?: string;
  isOutgoing: boolean;
  isIncoming: boolean;
};

const receiptUserPhone = (user?: ReceiptUser | null): string => {
  if (!user) return '';
  if (typeof user.phone === 'string' && user.phone.trim()) return user.phone.trim();
  const country = String(user.phoneCountry || '').trim().replace(/^\+/, '');
  const number = String(user.phoneNumber || '').trim();
  return country && number ? `${country}:${number}` : number;
};

/** Resolve the two real identities shown on an official transfer receipt. */
export const resolveTransferReceiptParticipants = (
  transaction: any,
  authenticatedUser?: ReceiptUser | null,
): TransferReceiptParticipants => {
  const outgoingDirections = new Set(['sent', 'send', 'withdrawal']);
  const incomingDirections = new Set(['received', 'receive', 'deposit']);
  const directionCandidates = [
    transaction?.type,
    transaction?.transactionType,
    transaction?.transaction_type,
    transaction?.direction,
  ].map(value => String(value || '').toLowerCase());
  const direction = directionCandidates.find(
    value => outgoingDirections.has(value) || incomingDirections.has(value),
  ) || '';
  const amount = String(transaction?.amount || '').trim();
  const directionIsOutgoing = outgoingDirections.has(direction);
  const directionIsIncoming = incomingDirections.has(direction);
  const hasKnownDirection = directionIsOutgoing || directionIsIncoming;
  const isOutgoing = directionIsOutgoing || (!hasKnownDirection && amount.startsWith('-'));
  const isIncoming = directionIsIncoming || (!hasKnownDirection && amount.startsWith('+'));
  const authenticatedName = receiptUserName(authenticatedUser);
  const senderBusiness = transaction?.senderBusiness || transaction?.payerBusiness;
  const recipientBusiness = transaction?.recipientBusiness || transaction?.merchantBusiness;
  const senderUser = senderBusiness || (isOutgoing
    ? authenticatedUser
    : (transaction?.senderUser || transaction?.counterpartyUser));
  const recipientUser = recipientBusiness || (isIncoming
    ? authenticatedUser
    : (transaction?.recipientUser || transaction?.counterpartyUser));
  const senderAddress = pickReceiptText(
    transaction?.senderAddress,
    transaction?.sender_address,
    transaction?.fromAddress,
    transaction?.from_address,
    transaction?.sourceAddress,
  );
  const recipientAddress = pickReceiptText(
    transaction?.recipientAddress,
    transaction?.recipient_address,
    transaction?.toAddress,
    transaction?.to_address,
    transaction?.destinationAddress,
  );

  const senderName = pickReceiptIdentity(
    senderBusiness?.name,
    isOutgoing ? authenticatedName : '',
    transaction?.senderDisplayName,
    transaction?.sender_name,
    transaction?.senderName,
    transaction?.fromName,
    transaction?.from,
    receiptUserName(transaction?.senderUser),
    isIncoming ? receiptUserName(transaction?.counterpartyUser) : '',
    senderAddress,
  ) || 'Usuario';

  const recipientName = pickReceiptIdentity(
    recipientBusiness?.name,
    isIncoming ? authenticatedName : '',
    transaction?.recipientDisplayName,
    transaction?.recipient_name,
    transaction?.recipientName,
    transaction?.toName,
    transaction?.to,
    receiptUserName(transaction?.recipientUser),
    isOutgoing ? receiptUserName(transaction?.counterpartyUser) : '',
    recipientAddress,
  ) || 'Usuario';

  return {
    senderName,
    recipientName,
    senderUsername: pickReceiptText(senderUser?.username),
    recipientUsername: pickReceiptText(recipientUser?.username),
    senderPhone: pickReceiptText(
      receiptUserPhone(senderUser),
      transaction?.senderPhone,
      transaction?.sender_phone,
    ),
    recipientPhone: pickReceiptText(
      receiptUserPhone(recipientUser),
      transaction?.recipientPhone,
      transaction?.recipient_phone,
    ),
    senderAddress,
    recipientAddress,
    isOutgoing,
    isIncoming,
  };
};
