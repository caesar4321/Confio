import { gql } from '@apollo/client';

// QR Bolivia (provider chosen by the server): get paid with a Bolivian QR and pay any Bolivian QR.
// Its own operations: an older server without these fields fails only these screens.

const RECEIVE_FIELDS = `
  success error nextStep orderId status phase bobAmount usdEstimate usdReceived rate feeBob
  qrText qrImage expiresAt cancelled createdAt
`;

const SEND_FIELDS = `
  success error nextStep orderId status statusDetail phase usdAmount usdtAmount bobAmount
  holderName bankName accountLast4 fundingTxHash bankReference canCancel canFund wallet
`;

export const BOLIVIA_QR_KOYWE_REPLACED = gql`query BoliviaQrKoyweReplaced {
  boliviaQrKoyweReplaced { topUp withdraw }
}`;

export const BOLIVIA_QR_RECEIVE_QUOTE = gql`query BoliviaQrReceiveQuote($bobAmount: String!) {
  boliviaQrReceiveQuote(bobAmount: $bobAmount) { success error bobAmount usdEstimate rate feeBob }
}`;

export const BOLIVIA_QR_ACTIVE_RECEIVE = gql`query BoliviaQrActiveReceive {
  boliviaQrActiveReceive { ${RECEIVE_FIELDS} }
}`;

export const BOLIVIA_QR_RECEIVE_ORDER = gql`query BoliviaQrReceiveOrder($orderId: String!) {
  boliviaQrReceiveOrder(orderId: $orderId) { ${RECEIVE_FIELDS} }
}`;

export const CREATE_BOLIVIA_QR_RECEIVE = gql`mutation CreateBoliviaQrReceive($bobAmount: String!) {
  createBoliviaQrReceive(bobAmount: $bobAmount) { ${RECEIVE_FIELDS} }
}`;

export const CANCEL_BOLIVIA_QR_RECEIVE = gql`mutation CancelBoliviaQrReceive($orderId: String!) {
  cancelBoliviaQrReceive(orderId: $orderId) { ${RECEIVE_FIELDS} }
}`;

export const BOLIVIA_QR_SEND_QUOTE = gql`query BoliviaQrSendQuote($qrText: String!, $bobAmount: String) {
  boliviaQrSendQuote(qrText: $qrText, bobAmount: $bobAmount) {
    success error bobAmount usdAmount usdtAmount confioFeeUsd rate
    recipient { holderName bankName accountLast4 amount fixedAmount expiresOn }
  }
}`;

export const BOLIVIA_QR_ACTIVE_SEND = gql`query BoliviaQrActiveSend {
  boliviaQrActiveSend { ${SEND_FIELDS} }
}`;

export const BOLIVIA_QR_SEND_ORDER = gql`query BoliviaQrSendOrder($orderId: String!) {
  boliviaQrSendOrder(orderId: $orderId) { ${SEND_FIELDS} }
}`;

export const CREATE_BOLIVIA_QR_SEND = gql`mutation CreateBoliviaQrSend(
  $qrText: String!, $bobAmount: String, $maxUsdAmount: String!
) {
  createBoliviaQrSend(qrText: $qrText, bobAmount: $bobAmount, maxUsdAmount: $maxUsdAmount) { ${SEND_FIELDS} }
}`;

export const START_BOLIVIA_QR_SEND_FUNDING = gql`mutation StartBoliviaQrSendFunding($orderId: String!) {
  startBoliviaQrSendFunding(orderId: $orderId) {
    ${SEND_FIELDS}
    funding { depositAddress network depositAmountWei grossDebitAmountWei expiresAt }
  }
}`;

export const REPORT_BOLIVIA_QR_SEND_FUNDING = gql`mutation ReportBoliviaQrSendFunding($orderId: String!, $txHash: String) {
  reportBoliviaQrSendFunding(orderId: $orderId, txHash: $txHash) { ${SEND_FIELDS} }
}`;

export const CANCEL_BOLIVIA_QR_SEND = gql`mutation CancelBoliviaQrSend($orderId: String!) {
  cancelBoliviaQrSend(orderId: $orderId) { ${SEND_FIELDS} }
}`;

export interface BoliviaQrReceiveOrder {
  success: boolean;
  error?: string | null;
  nextStep?: string | null;
  orderId?: string | null;
  status?: string | null;
  phase?: string | null;
  bobAmount?: string | null;
  usdEstimate?: string | null;
  usdReceived?: string | null;
  rate?: string | null;
  feeBob?: string | null;
  qrText?: string | null;
  qrImage?: string | null;
  expiresAt?: string | null;
  cancelled?: boolean | null;
  createdAt?: string | null;
}

export interface BoliviaQrReceiveQuote {
  success: boolean;
  error?: string | null;
  bobAmount?: string | null;
  usdEstimate?: string | null;
  rate?: string | null;
  feeBob?: string | null;
}

export interface BoliviaQrRecipient {
  holderName?: string | null;
  bankName?: string | null;
  accountLast4?: string | null;
  amount?: string | null;
  fixedAmount?: boolean | null;
  expiresOn?: string | null;
}

export interface BoliviaQrSendQuote {
  success: boolean;
  error?: string | null;
  recipient?: BoliviaQrRecipient | null;
  bobAmount?: string | null;
  usdAmount?: string | null;
  usdtAmount?: string | null;
  confioFeeUsd?: string | null;
  rate?: string | null;
}

export interface BoliviaQrFunding {
  depositAddress: string;
  network: string;
  depositAmountWei: string;
  grossDebitAmountWei?: string | null;
  /** Unix seconds: never fund after this (a bridge quote deadline). */
  expiresAt?: number | null;
}

export interface BoliviaQrSendOrder {
  success: boolean;
  error?: string | null;
  nextStep?: string | null;
  orderId?: string | null;
  status?: string | null;
  statusDetail?: string | null;
  phase?: string | null;
  usdAmount?: string | null;
  usdtAmount?: string | null;
  bobAmount?: string | null;
  holderName?: string | null;
  bankName?: string | null;
  accountLast4?: string | null;
  fundingTxHash?: string | null;
  bankReference?: string | null;
  canCancel?: boolean | null;
  canFund?: boolean | null;
  wallet?: string | null;
  funding?: BoliviaQrFunding | null;
}

/** An image URI for a provider QR (base64 PNG with or without a data: prefix). */
export const qrImageUri = (value?: string | null) => {
  const raw = String(value || '').trim();
  if (!raw) return '';
  return raw.startsWith('data:') ? raw : `data:image/png;base64,${raw}`;
};

/** Where an open order stands, in the person's words. */
export function receiveCopy(order: BoliviaQrReceiveOrder): { title: string; body: string } {
  switch (order.phase) {
    case 'qr_ready':
      return { title: 'Tu QR está listo', body: 'Muéstralo o compártelo. Se paga desde cualquier banco o billetera de Bolivia.' };
    case 'paid':
    case 'delivering':
      return { title: 'Pago recibido', body: 'Estamos acreditando tus dólares. Suele tardar unos minutos.' };
    case 'completed':
      return { title: 'Listo', body: 'Los dólares ya están en tu saldo.' };
    case 'expired':
      return { title: 'El QR venció', body: 'Nadie lo pagó a tiempo. Crea uno nuevo cuando quieras.' };
    case 'review':
      return { title: 'Estamos revisando tu pago', body: 'Recibimos el pago y lo estamos verificando. Te avisaremos.' };
    default:
      return { title: 'No se completó', body: 'Este QR no se pudo usar. Crea uno nuevo.' };
  }
}

export function sendCopy(order: BoliviaQrSendOrder): { title: string; body: string } {
  const phase = order.phase || '';
  if (order.status === 'COMPLETED') return { title: 'Pago realizado', body: 'El QR quedó pagado.' };
  if (order.status === 'FAILED') return { title: 'No se completó', body: 'Este pago no salió de tu saldo.' };
  if (phase === 'awaiting_funding') return { title: 'Confirma el pago', body: 'Revisa los datos y confirma.' };
  if (phase === 'payout_review' || phase === 'payout_failed') {
    return { title: 'Estamos revisando tu pago', body: 'Tus dólares están seguros. Te avisaremos apenas se complete.' };
  }
  return { title: 'Pagando…', body: 'Tus dólares salieron de tu saldo. El QR se paga en unos minutos.' };
}
