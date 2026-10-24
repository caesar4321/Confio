import { gql } from '@apollo/client';

// Venezuelan Pago Móvil send (VEXPay). Its own operations: an older server
// without these fields fails only this screen, never a shared query.

const ORDER_FIELDS = `
  success error nextStep orderId status statusDetail phase
  usdAmount usdtAmount estimatedVes vesAmount rate fundingTxHash bankReference canCancel canFund wallet
  beneficiary { cedula phone bankCode bankName }
`;

export const VEXPAY_ACTIVE_OFF_RAMP_ORDER = gql`query VexpayActiveOffRampOrder {
  vexpayActiveOffRampOrder { ${ORDER_FIELDS} }
}`;

export const VEXPAY_OFF_RAMP_ORDER = gql`query VexpayOffRampOrder($orderId: String!) {
  vexpayOffRampOrder(orderId: $orderId) { ${ORDER_FIELDS} }
}`;

export const VEXPAY_OFF_RAMP_QUOTE = gql`query VexpayOffRampQuote($usdAmount: String!) {
  vexpayOffRampQuote(usdAmount: $usdAmount) {
    success error usdAmount usdtAmount confioFeeUsd processorFeeUsd estimatedVes rate minUsd maxUsd
  }
}`;

export const CREATE_VEXPAY_OFF_RAMP = gql`mutation CreateVexpayOffRamp(
  $usdAmount: String!, $cedula: String!, $phone: String!, $bankCode: String!
) {
  createVexpayOffRamp(usdAmount: $usdAmount, cedula: $cedula, phone: $phone, bankCode: $bankCode) {
    ${ORDER_FIELDS}
  }
}`;

export const START_VEXPAY_OFF_RAMP_FUNDING = gql`mutation StartVexpayOffRampFunding($orderId: String!) {
  startVexpayOffRampFunding(orderId: $orderId) {
    ${ORDER_FIELDS}
    funding { depositAddress network depositAmountWei grossDebitAmountWei }
  }
}`;

export const REPORT_VEXPAY_OFF_RAMP_FUNDING = gql`mutation ReportVexpayOffRampFunding($orderId: String!, $txHash: String) {
  reportVexpayOffRampFunding(orderId: $orderId, txHash: $txHash) { ${ORDER_FIELDS} }
}`;

export const CANCEL_VEXPAY_OFF_RAMP = gql`mutation CancelVexpayOffRamp($orderId: String!) {
  cancelVexpayOffRamp(orderId: $orderId) { ${ORDER_FIELDS} }
}`;

export interface VexpayFunding {
  depositAddress: string;
  network: string;
  depositAmountWei: string;
  grossDebitAmountWei?: string | null;
}

export interface VexpaySendOrder {
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
  funding?: VexpayFunding | null;
}

export interface VexpaySendQuote {
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
export const fundingPaymentDetails = (funding: VexpayFunding) => ({
  confioDepositAddress: funding.depositAddress,
  confioDepositNetwork: funding.network,
  confioDepositAmountWei: funding.depositAmountWei,
  ...(funding.grossDebitAmountWei ? { confioGrossDebitAmountWei: funding.grossDebitAmountWei } : {}),
});

/** 0 created/funding, 1 dollars sent, 2 converting, 3 delivered. */
export function sendStage(order: VexpaySendOrder): number {
  if (order.status === 'COMPLETED') return 3;
  const phase = order.phase || '';
  if (['converted', 'paying', 'credit_pending', 'credit_failed', 'credit_review'].includes(phase)) return 2;
  if (phase === 'funded') return 2;
  if (phase === 'funding_reported') return 1;
  return 0;
}

/** What the person sees; never a provider leg name. */
export function vexpaySendCopy(order: VexpaySendOrder): { title: string; body: string } {
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
  if (order.phase === 'funded' || order.phase === 'converted' || detail === 'waiting_balance') {
    return { title: 'Convirtiendo a bolívares', body: 'Puede tardar hasta unas horas en horario bancario.' };
  }
  if (order.phase === 'paying' || order.phase === 'credit_pending') {
    return { title: 'Pagando por Pago Móvil', body: 'El banco está acreditando los bolívares.' };
  }
  return { title: 'Listo para enviar', body: '' };
}
