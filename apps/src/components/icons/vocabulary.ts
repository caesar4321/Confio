// One icon vocabulary for both money lists.
//
// The notification list and the transaction ledger describe the same events,
// but each had grown its own ad-hoc map: a received send was `download` in one
// and `arrow-down` in the other, `repeat` covered both conversions and ramps,
// and `credit-card` covered a payment sent and a payment received alike. The
// rule here is one line long:
//
//   the glyph says WHAT happened, the color says WHICH WAY the money went.
//
// So a payment is a shopping bag whichever way it points, and emerald always
// means money arrived. Events that move no money (security, business, system)
// keep a category color instead, because direction would be a lie.
//
// State lives in a badge, but only in the notification list: a ledger row
// already prints "Pendiente" or "Fallido" next to its amount, so a badge there
// would say it twice.

import { colors } from '../../config/theme';
import { BadgeName } from './glyphs';
import { IconVisual } from './IconChip';

type Tone = { color: string; bg: string };

export const TONES: Record<string, Tone> = {
  moneyIn: { color: colors.primaryDark, bg: colors.primaryLight },
  // Outgoing money is not an alert, so it stays ink on gray rather than red.
  moneyOut: { color: colors.text.primary, bg: colors.neutralDark },
  pending: { color: colors.offRampIcon, bg: colors.offRampLight },
  failure: { color: colors.danger, bg: colors.dangerLight },
  social: { color: colors.secondary, bg: colors.violetLight },
  info: { color: colors.accent, bg: colors.infoLight },
  // External rails — USDC, card ramps — keep the cyan they already had.
  rail: { color: '#06B6D4', bg: '#CFFAFE' },
  // Locked value: presale and stocks.
  invest: { color: '#6366F1', bg: '#EEF2FF' },
  reward: { color: '#D97706', bg: colors.warningLight },
  promo: { color: '#EC4899', bg: '#FCE7F3' },
  care: { color: '#E11D48', bg: '#FFE4E6' },
  neutral: { color: colors.text.secondary, bg: colors.neutralDark },
};

const visual = (glyph: string, tone: keyof typeof TONES, badge?: BadgeName): IconVisual => ({
  glyph,
  ...TONES[tone],
  // A badge takes the glyph's own color, and ink reads as a blob at 17px, so
  // outgoing money says its state in words instead — which those rows do.
  badge: tone === 'moneyOut' ? undefined : badge,
});

// Stages of a local transfer that have stopped moving. Everything else is in
// flight; the message text carries the detail, the badge only has to separate
// waiting from finished.
const LOCAL_TRANSFER_TERMINAL: Record<string, IconVisual> = {
  completed: visual('bank', 'moneyIn', 'done'),
  refunded: visual('bank', 'pending', 'returned'),
  failed: visual('bank', 'failure', 'failed'),
  needs_review: visual('bank', 'pending', 'review'),
};

export const localTransferVisual = (stage?: string | null, incoming?: boolean): IconVisual => {
  const terminal = stage ? LOCAL_TRANSFER_TERMINAL[stage] : undefined;
  if (!terminal) return visual('bank', 'pending', 'pending');
  // An arriving transfer that landed is money in, not just a finished task.
  return terminal.badge === 'done' && incoming ? { ...terminal, badge: 'incoming' } : terminal;
};

const NOTIFICATIONS: Record<string, IconVisual> = {
  // Sends between people
  SEND_RECEIVED: visual('arrow-down', 'moneyIn'),
  SEND_SENT: visual('arrow-up', 'moneyOut'),
  SEND_FROM_EXTERNAL: visual('wallet', 'moneyIn', 'incoming'),
  INVITE_RECEIVED: visual('gift', 'moneyIn'),
  SEND_INVITATION_SENT: visual('user-plus', 'social', 'pending'),
  SEND_INVITATION_CLAIMED: visual('user-check', 'moneyIn', 'done'),
  // An expired invitation is not a failure: the money came back.
  SEND_INVITATION_EXPIRED: visual('user-x', 'pending', 'returned'),

  // Payments and payroll
  PAYMENT_RECEIVED: visual('shopping-bag', 'moneyIn'),
  PAYMENT_SENT: visual('shopping-bag', 'moneyOut'),
  INVOICE_PAID: visual('file-text', 'moneyIn', 'done'),
  PAYROLL_RECEIVED: visual('briefcase', 'moneyIn'),
  PAYROLL_SENT: visual('briefcase', 'moneyOut'),

  // Conversions
  CONVERSION_COMPLETED: visual('swap', 'info', 'done'),
  CONVERSION_FAILED: visual('swap', 'failure', 'failed'),

  // The stablecoin itself moving on an external rail
  USDC_DEPOSIT_PENDING: visual('coin', 'pending', 'pending'),
  USDC_DEPOSIT_COMPLETED: visual('coin', 'moneyIn', 'incoming'),
  USDC_DEPOSIT_FAILED: visual('coin', 'failure', 'failed'),
  USDC_WITHDRAWAL_PENDING: visual('coin', 'pending', 'pending'),
  USDC_WITHDRAWAL_COMPLETED: visual('coin', 'moneyOut'),
  USDC_WITHDRAWAL_FAILED: visual('coin', 'failure', 'failed'),

  // Card ramps
  RAMP_PENDING: visual('card', 'pending', 'pending'),
  RAMP_PROCESSING: visual('card', 'pending', 'pending'),
  RAMP_COMPLETED: visual('card', 'rail', 'done'),
  RAMP_FAILED: visual('card', 'failure', 'failed'),

  // Account and security
  ACCOUNT_VERIFIED: visual('shield', 'moneyIn', 'done'),
  SECURITY_ALERT: visual('shield', 'failure', 'review'),
  NEW_LOGIN: visual('log-in', 'pending'),

  // Business
  BUSINESS_EMPLOYEE_ADDED: visual('users', 'social'),
  BUSINESS_EMPLOYEE_REMOVED: visual('user-minus', 'neutral'),
  BUSINESS_PERMISSION_CHANGED: visual('sliders', 'neutral'),

  // Rewards and progress
  ACHIEVEMENT_EARNED: visual('award', 'reward'),
  REFERRAL_FRIEND_JOINED: visual('user-plus', 'social'),
  REFERRAL_FIRST_TRANSACTION: visual('trending-up', 'moneyIn'),
  REFERRAL_ACTION_REMINDER: visual('target', 'pending'),
  REFERRAL_EVENT_TOP_UP: visual('target', 'social'),
  REFERRAL_EVENT_CONVERSION: visual('target', 'social'),
  REFERRAL_EVENT_SEND: visual('target', 'social'),
  REFERRAL_EVENT_PAYMENT: visual('target', 'social'),
  REFERRAL_EVENT_P2P_TRADE: visual('target', 'social'),
  REFERRAL_REWARD_READY: visual('gift', 'reward'),
  REFERRAL_REWARD_CLAIMED: visual('gift', 'moneyIn', 'done'),

  // $CONFIO
  PRESALE_PURCHASE_CONFIRMED: visual('lock', 'invest', 'done'),
  PRESALE_AVAILABLE: visual('unlock', 'invest'),

  // General
  PROMOTION: visual('tag', 'promo'),
  SYSTEM: visual('info', 'neutral'),
  ANNOUNCEMENT: visual('bell', 'info'),

  // P2P left the product, but stored notices still render. One glyph, state
  // by badge, rather than the eight near-duplicates this map used to carry.
  P2P_OFFER_RECEIVED: visual('users', 'info'),
  P2P_OFFER_ACCEPTED: visual('users', 'info', 'done'),
  P2P_OFFER_REJECTED: visual('users', 'neutral', 'failed'),
  P2P_TRADE_STARTED: visual('users', 'info', 'pending'),
  P2P_PAYMENT_CONFIRMED: visual('users', 'info', 'done'),
  P2P_CRYPTO_RELEASED: visual('users', 'moneyIn', 'done'),
  P2P_TRADE_COMPLETED: visual('users', 'moneyIn', 'done'),
  P2P_TRADE_CANCELLED: visual('users', 'neutral', 'failed'),
  P2P_TRADE_DISPUTED: visual('users', 'pending', 'review'),
  P2P_DISPUTE_RESOLVED: visual('users', 'info', 'done'),
};

export const notificationVisual = (type: string, data?: { stage?: string | null; incoming?: boolean }): IconVisual => {
  if (type === 'LOCAL_TRANSFER_UPDATED') return localTransferVisual(data?.stage, data?.incoming);
  return NOTIFICATIONS[type] || visual('bell', 'neutral');
};

// The ledger's own row kinds. `incoming` comes from the amount's sign, which
// is what the row already uses to color its amount.
export type TransactionKind =
  | 'received' | 'sent' | 'send' | 'payment' | 'payroll' | 'humanitarian' | 'exchange'
  | 'conversion' | 'ramp' | 'reward' | 'presale' | 'stocks' | 'local_transfer'
  | 'deposit' | 'withdrawal';

export const transactionVisual = (kind: TransactionKind | string, incoming: boolean): IconVisual => {
  const direction = incoming ? 'moneyIn' : 'moneyOut';
  switch (kind) {
    case 'received':
      return visual('arrow-down', 'moneyIn');
    case 'sent':
    case 'send':
      return visual('arrow-up', 'moneyOut');
    case 'deposit':
      return visual('coin', 'moneyIn');
    case 'withdrawal':
      return visual('coin', 'moneyOut');
    // A transfer to a bank or payment wallet, which the ledger used to drop
    // through to the default arrow.
    case 'local_transfer':
      return visual('bank', direction);
    case 'payment':
      return visual('shopping-bag', direction);
    case 'payroll':
      return visual('briefcase', direction);
    case 'humanitarian':
      return visual('heart', 'care');
    case 'exchange':
    case 'conversion':
      return visual('swap', 'info');
    case 'ramp':
      return visual('card', 'rail');
    case 'reward':
      return visual('gift', 'reward');
    case 'presale':
      return visual('lock', 'invest');
    case 'stocks':
      return visual('trending-up', 'invest');
    default:
      return visual(incoming ? 'arrow-down' : 'arrow-up', 'neutral');
  }
};
