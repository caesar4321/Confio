import { gql } from '@apollo/client';

// Venezuelan Pago Móvil send (provider chosen by the server). Its own operations: an older server
// without these fields fails only this screen, never a shared query.

const ORDER_FIELDS = `
  success error nextStep orderId status statusDetail phase
  usdAmount usdtAmount estimatedVes vesAmount rate fundingTxHash bankReference canCancel canFund wallet
  beneficiary { cedula phone bankCode bankName }
`;

export const VE_ACTIVE_SEND = gql`query VePagoMovilActiveSend {
  vePagomovilActiveSend { ${ORDER_FIELDS} }
}`;

export const VE_SEND_ORDER = gql`query VePagoMovilSendOrder($orderId: String!) {
  vePagomovilSendOrder(orderId: $orderId) { ${ORDER_FIELDS} }
}`;

export const VE_SEND_QUOTE = gql`query VePagoMovilSendQuote($usdAmount: String!) {
  vePagomovilSendQuote(usdAmount: $usdAmount) {
    success error usdAmount usdtAmount confioFeeUsd processorFeeUsd estimatedVes rate minUsd maxUsd
  }
}`;

export const CREATE_VE_SEND = gql`mutation CreateVePagoMovilSend(
  $usdAmount: String!, $cedula: String!, $phone: String!, $bankCode: String!
) {
  createVePagomovilSend(usdAmount: $usdAmount, cedula: $cedula, phone: $phone, bankCode: $bankCode) {
    ${ORDER_FIELDS}
  }
}`;

export const START_VE_SEND_FUNDING = gql`mutation StartVePagoMovilSendFunding($orderId: String!) {
  startVePagomovilSendFunding(orderId: $orderId) {
    ${ORDER_FIELDS}
    funding { depositAddress network depositAmountWei grossDebitAmountWei expiresAt }
  }
}`;

export const REPORT_VE_SEND_FUNDING = gql`mutation ReportVePagoMovilSendFunding($orderId: String!, $txHash: String) {
  reportVePagomovilSendFunding(orderId: $orderId, txHash: $txHash) { ${ORDER_FIELDS} }
}`;

export const CANCEL_VE_SEND = gql`mutation CancelVePagoMovilSend($orderId: String!) {
  cancelVePagomovilSend(orderId: $orderId) { ${ORDER_FIELDS} }
}`;

export interface VeSendFunding {
  depositAddress: string;
  network: string;
  depositAmountWei: string;
  grossDebitAmountWei?: string | null;
  /** Unix seconds: never fund after this (a bridge quote deadline). */
  expiresAt?: number | null;
}

export interface VeSendOrder {
  success: boolean;
  error?: string | null;
  nextStep?: string | null;
  orderId?: string | null;
  status?: string | null;
  statusDetail?: string | null;
  phase?: string | null;
  usdAmount?: string | null;
  usdtAmount?: string | null;
  estimatedVes?: string | null;
  vesAmount?: string | null;
  rate?: string | null;
  fundingTxHash?: string | null;
  bankReference?: string | null;
  canCancel?: boolean | null;
  canFund?: boolean | null;
  wallet?: string | null;
  beneficiary?: { cedula: string; phone: string; bankCode: string; bankName: string } | null;
  funding?: VeSendFunding | null;
}

export interface VeSendQuote {
  success: boolean;
  error?: string | null;
  usdAmount?: string | null;
  usdtAmount?: string | null;
  confioFeeUsd?: string | null;
  processorFeeUsd?: string | null;
  estimatedVes?: string | null;
  rate?: string | null;
  minUsd?: string | null;
  maxUsd?: string | null;
}

/** The vouched target in the shape the audited Retiro funding path reads. */
export const fundingPaymentDetails = (funding: VeSendFunding) => ({
  confioDepositAddress: funding.depositAddress,
  confioDepositNetwork: funding.network,
  confioDepositAmountWei: funding.depositAmountWei,
  ...(funding.grossDebitAmountWei ? { confioGrossDebitAmountWei: funding.grossDebitAmountWei } : {}),
});

/** 0 created/funding, 1 dollars sent, 2 converting, 3 delivered. */
export function sendStage(order: VeSendOrder): number {
  if (order.status === 'COMPLETED') return 3;
  const phase = order.phase || '';
  if (['funded', 'settled', 'paying', 'payout_pending', 'payout_failed', 'payout_review'].includes(phase)) return 2;
  if (phase === 'funding_reported') return 1;
  return 0;
}

/** What the person sees; never a provider leg name. */
export function sendCopy(order: VeSendOrder): { title: string; body: string } {
  const detail = order.statusDetail || '';
  if (order.status === 'COMPLETED') {
    return { title: 'Bolívares entregados', body: 'El Pago Móvil llegó a la cuenta de destino.' };
  }
  if (order.status === 'FAILED') {
    return detail === 'cancelled_by_user'
      ? { title: 'Envío cancelado', body: 'No se envió nada. Tu dinero sigue en tu cuenta.' }
      : { title: 'El envío no salió', body: 'No se envió nada. Tu dinero sigue en tu cuenta.' };
  }
  if (detail.startsWith('needs_review')) {
    return { title: 'Estamos revisando tu envío', body: 'Tu dinero está seguro. Nuestro equipo está terminando el envío.' };
  }
  if (order.phase === 'funding_reported') {
    return { title: 'Enviando tus dólares', body: 'Confirmando la transferencia. No cierres esta pantalla.' };
  }
  if (order.phase === 'funded' || order.phase === 'settled' || detail === 'waiting_balance') {
    return { title: 'Convirtiendo a bolívares', body: 'Tus dólares llegaron. Estamos preparando el Pago Móvil.' };
  }
  if (order.phase === 'paying' || order.phase === 'payout_pending') {
    return { title: 'Pagando por Pago Móvil', body: 'El banco está acreditando los bolívares.' };
  }
  return { title: 'Listo para enviar', body: '' };
}
