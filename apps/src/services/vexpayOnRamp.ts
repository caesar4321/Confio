import { gql } from '@apollo/client';

// Venezuelan Pago Móvil top-up (VEXPay). Its own operations: an older server
// without these fields fails only this screen, never a shared query.

const ORDER_FIELDS = `
  success error nextStep orderId status statusDetail method
  usdAmount vesAmount estimatedUsdt deliveredUsdt otpRequested txHash canConfirm canCancel
  receivingAccount { bankCode bankName phone identification }
`;

export const VEXPAY_ACTIVE_ON_RAMP_ORDER = gql`query VexpayActiveOnRampOrder {
  vexpayActiveOnRampOrder { ${ORDER_FIELDS} }
}`;

export const VEXPAY_ON_RAMP_ORDER = gql`query VexpayOnRampOrder($orderId: String!) {
  vexpayOnRampOrder(orderId: $orderId) { ${ORDER_FIELDS} }
}`;

export const VEXPAY_ON_RAMP_QUOTE = gql`query VexpayOnRampQuote($usdAmount: String!) {
  vexpayOnRampQuote(usdAmount: $usdAmount) {
    success error usdAmount vesAmount rate estimatedUsdt minUsd maxUsd processorFeeUsd confioFeeUsd
  }
}`;

export const VEXPAY_BANKS = gql`query VexpayBanks { vexpayBanks { code name } }`;

export const CREATE_VEXPAY_ON_RAMP = gql`mutation CreateVexpayOnRamp(
  $usdAmount: String!, $method: String!, $cedula: String!, $phone: String!, $bankCode: String!
) {
  createVexpayOnRamp(usdAmount: $usdAmount, method: $method, cedula: $cedula, phone: $phone, bankCode: $bankCode) {
    ${ORDER_FIELDS}
  }
}`;

export const CONFIRM_VEXPAY_C2P = gql`mutation ConfirmVexpayC2p($orderId: String!, $otp: String!) {
  confirmVexpayC2p(orderId: $orderId, otp: $otp) { ${ORDER_FIELDS} }
}`;

export const CANCEL_VEXPAY_ON_RAMP = gql`mutation CancelVexpayOnRamp($orderId: String!) {
  cancelVexpayOnRamp(orderId: $orderId) { ${ORDER_FIELDS} }
}`;

export const VERIFY_VEXPAY_PAGO_MOVIL = gql`mutation VerifyVexpayPagoMovil($orderId: String!, $reference: String!, $paymentDate: String) {
  verifyVexpayPagoMovil(orderId: $orderId, reference: $reference, paymentDate: $paymentDate) { ${ORDER_FIELDS} }
}`;

/** YYYY-MM-DD (device-local) for today minus `daysAgo`. */
export function isoDaysAgo(daysAgo: number, now: Date = new Date()): string {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - daysAgo);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** 'DD/MM/AAAA' → 'YYYY-MM-DD', or null. */
export function parseDayMonthYear(value: string): string | null {
  const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(value.trim());
  if (!m) return null;
  const pad = (n: string) => n.padStart(2, '0');
  return `${m[3]}-${pad(m[2])}-${pad(m[1])}`;
}

export type VexpayMethod = 'pago_movil' | 'c2p';

export interface VexpayOrder {
  success: boolean;
  error?: string | null;
  nextStep?: string | null;
  orderId?: string | null;
  status?: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED' | string | null;
  statusDetail?: string | null;
  method?: VexpayMethod | string | null;
  usdAmount?: string | null;
  vesAmount?: string | null;
  estimatedUsdt?: string | null;
  deliveredUsdt?: string | null;
  otpRequested?: boolean | null;
  txHash?: string | null;
  canConfirm?: boolean | null;
  canCancel?: boolean | null;
  receivingAccount?: { bankCode: string; bankName: string; phone: string; identification: string } | null;
}

export interface VexpayQuote {
  success: boolean;
  error?: string | null;
  usdAmount?: string | null;
  vesAmount?: string | null;
  rate?: string | null;
  estimatedUsdt?: string | null;
  minUsd?: string | null;
  maxUsd?: string | null;
  processorFeeUsd?: string | null;
  confioFeeUsd?: string | null;
}

/** What the person sees while an order is in flight; never a provider leg name. */
export function vexpayProgressCopy(order: VexpayOrder): { title: string; body: string } {
  const detail = order.statusDetail || '';
  if (order.status === 'COMPLETED') {
    // VEXPay delivered; Confío's conversion credits the balance shortly after.
    return order.deliveredUsdt
      ? { title: 'Recarga completada', body: 'Tus dólares ya están en tu cuenta Confío.' }
      : { title: 'Pago enviado a tu cuenta', body: 'Estamos acreditando tus dólares; aparecerán en unos minutos.' };
  }
  if (order.status === 'FAILED' && detail === 'cancelled_by_user') {
    return { title: 'Recarga cancelada', body: 'Cancelaste esta recarga.' };
  }
  if (order.status === 'FAILED') {
    return detail.startsWith('expired')
      ? { title: 'La recarga expiró', body: 'No recibimos el pago a tiempo. Si ya pagaste, contacta a soporte con la referencia.' }
      : { title: 'La recarga no se completó', body: 'El banco no confirmó el pago. Si se debitó dinero, contacta a soporte.' };
  }
  if (detail.startsWith('needs_review')) {
    return { title: 'Estamos revisando tu recarga', body: 'Recibimos tu pago. Nuestro equipo está terminando la recarga; no hagas otro pago.' };
  }
  if (detail === 'onward_waiting_release') {
    return { title: 'Pago recibido', body: 'Tus dólares están en camino. Este paso puede tardar unas horas.' };
  }
  if (detail === 'bank_confirming' || detail.endsWith('_ambiguous') || detail === 'submission_unconfirmed') {
    return { title: 'Confirmando tu pago', body: 'Tu banco está confirmando el pago. No hagas otro pago.' };
  }
  if (order.status === 'PROCESSING') {
    return { title: 'Pago recibido', body: 'Estamos convirtiendo tus bolívares a dólares. No hagas otro pago.' };
  }
  return { title: 'Esperando tu pago', body: '' };
}

const STATUS_RANK: Record<string, number> = { PENDING: 0, PROCESSING: 1, COMPLETED: 2, FAILED: 2 };

/**
 * A response that would move the same order backwards (a slow poll landing
 * after a confirmation) must never reopen the payment form.
 */
export function isOrderRegression(current: VexpayOrder | null, next: VexpayOrder): boolean {
  if (!current || !next || current.orderId !== next.orderId) return false;
  const now = STATUS_RANK[current.status || ''] ?? 0;
  const then = STATUS_RANK[next.status || ''] ?? 0;
  // The server returning an unmatched verification to claimable (the bank
  // has not seen the transfer yet, or the amount needs correcting) is a real
  // move back to the form, not a stale read.
  const reopened = next.status === 'PENDING' && next.canConfirm === true
    && (next.statusDetail || '').startsWith('verify_') && current.status === 'PROCESSING';
  return then < now && !reopened;
}
