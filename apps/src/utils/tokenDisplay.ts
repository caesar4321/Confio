// Display names for the tokens that appear on receipts, success screens and
// transaction details.
//
// This existed as five identical private copies across the payment/receipt
// screens, none of which knew about the BSC tokens — so a cUSD+ receipt showed
// the raw wire value "CUSD_PLUS" as its denomination. One table, one place to
// add the next token.

const TOKEN_LABELS: Record<string, string> = {
  CUSD: 'cUSD',
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
  return key === 'usdc_to_cusd' || key === 'to_savings';
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
const BSC_TOKENS = new Set(['CUSD_PLUS', 'CUSD+', 'USDT']);

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
