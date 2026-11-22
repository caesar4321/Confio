// A payment prepared for the person to approve: in the chat (Confio
// Assistant read a code they pasted, or they sent the chat a QR image) and,
// later, from anywhere a code comes in. The server owns every figure
// (payment_accounts/payment_intents.py): the card and the approval sheet are
// drawn only from its row, never from the assistant's words, and nothing
// moves until the person approves on the sheet and signs with this phone.
import { gql } from '@apollo/client';
import { FIELDS as BRIDGE_FIELDS } from './paymentBridge';

export type PaymentIntent = {
  id: string;
  // quoted | awaiting_signature | paying | paid | refunding | refunded |
  // failed | under_review | expired | cancelled
  status: string;
  statusReason: string;
  methodId: string;
  // local_charge | local_transfer | ramp_order | confio_send
  family: string;
  destinationId?: string | null;
  payeeName: string;
  payeeLevel: string;
  payeeAccount: string;
  payeeDocument: string;
  institution: string;
  amountExact: boolean;
  amountLocal: string;
  minimumLocal?: string | null;
  currency: string;
  totalUsd: string;
  feeUsd: string;
  rate: string;
  chargeExpiresAt?: string | null;
  expiresAt: string;
  displayHash: string;
  journeyId?: string | null;
  orderId?: string | null;
  messageId?: string | null;
};

const INTENT = `
  id status statusReason methodId family destinationId payeeName payeeLevel payeeAccount payeeDocument institution
  amountExact amountLocal minimumLocal currency totalUsd feeUsd rate chargeExpiresAt expiresAt displayHash
  journeyId orderId messageId
`;

export const GET_MESSAGE_PAYMENT_INTENT = gql`
  query AssistantPaymentIntent($messageId: ID!) {
    assistantPaymentIntent(messageId: $messageId) { ${INTENT} }
  }
`;
const PREPARE = gql`
  mutation PreparePaymentIntent($code: String, $source: String!, $inChat: Boolean, $request: PaymentRequestInput) {
    preparePaymentIntent(code: $code, source: $source, inChat: $inChat, request: $request) {
      success errors errorCode intent { ${INTENT} }
    }
  }
`;
const CONFIRM = gql`
  mutation ConfirmPaymentIntent($id: UUID!, $displayHash: String!) {
    confirmPaymentIntent(id: $id, displayHash: $displayHash) {
      success errors errorCode nextStep signKind
      requestId localAccountId cryptoAccountId minimumFxOutput orderId
      transfer { ...PaymentBridgeFields }
      send { success error sendId tokenType intentId calls { to valueWei data } }
      intent { ${INTENT} }
    }
  }
  ${BRIDGE_FIELDS}
`;
const REQUOTE = gql`
  mutation RequotePaymentIntent($id: UUID!) {
    requotePaymentIntent(id: $id) { success errors errorCode intent { ${INTENT} } }
  }
`;
const CANCEL = gql`
  mutation CancelPaymentIntent($id: UUID!) {
    cancelPaymentIntent(id: $id) { success errors errorCode intent { ${INTENT} } }
  }
`;
const TRACK = gql`
  mutation TrackPaymentIntent($id: UUID!, $event: String!) {
    trackPaymentIntent(id: $id, event: $event) { success }
  }
`;

/** A refusal the person can read; `code` picks what the card offers next. */
export class PaymentIntentError extends Error {
  code: string;
  intent: PaymentIntent | null;
  /** The answer may not have arrived: the payment may or may not be on its way. */
  unsettled: boolean;

  constructor(message: string, code = '', intent: PaymentIntent | null = null, unsettled = false) {
    super(message);
    this.code = code;
    this.intent = intent;
    this.unsettled = unsettled;
  }
}

const client = async () => (await import('../apollo/client')).apolloClient;

/** A payment code the person handed the chat (a QR image, a pasted code)
 * becomes a card in the thread. Moves nothing. */
export async function preparePaymentInChat(code: string, source: 'shared_qr' | 'pasted_code'): Promise<PaymentIntent> {
  const { data } = await (await client()).mutate({ mutation: PREPARE, variables: { code, source, inChat: true } });
  const result = data?.preparePaymentIntent;
  if (!result?.success || !result.intent) {
    throw new PaymentIntentError(result?.errors?.[0] || 'No pude preparar el pago.', result?.errorCode || '');
  }
  return result.intent;
}

/** Details the person typed into a form in the chat (never an account id,
 * a name to show or a price: those are the rail's answer) become a card in
 * the thread. Moves nothing. */
export async function prepareRequestInChat(request: {
  methodId: string; phone?: string; cedula?: string; bankCode?: string; holderName?: string; amountUsd?: string;
}): Promise<PaymentIntent> {
  const { data } = await (await client()).mutate({ mutation: PREPARE, variables: { source: 'form', inChat: true, request } });
  const result = data?.preparePaymentIntent;
  if (!result?.success || !result.intent) {
    throw new PaymentIntentError(result?.errors?.[0] || 'No pude preparar el pago.', result?.errorCode || '');
  }
  return result.intent;
}

/** New figures for a card whose quote ran out. */
export async function requotePaymentIntent(id: string): Promise<PaymentIntent> {
  const { data } = await (await client()).mutate({ mutation: REQUOTE, variables: { id } });
  const result = data?.requotePaymentIntent;
  if (!result?.success || !result.intent) {
    throw new PaymentIntentError(result?.errors?.[0] || 'No pude cotizar de nuevo.', result?.errorCode || '');
  }
  return result.intent;
}

export async function cancelPaymentIntent(id: string): Promise<PaymentIntent | null> {
  const { data } = await (await client()).mutate({ mutation: CANCEL, variables: { id } });
  return data?.cancelPaymentIntent?.intent ?? null;
}

/** Funnel steps only the app sees. Never fails the thing it counts. */
export function trackPaymentIntent(id: string, event: 'card_shown' | 'sheet_opened'): void {
  void client().then((c) => c.mutate({ mutation: TRACK, variables: { id, event } })).catch(() => {});
}

export type PaidResult = { journeyId?: string; orderId?: string; handoff?: 'order' };

/**
 * The person approved these exact figures on the sheet. In order: the server
 * confirms nothing changed (and hands back what to sign), Confío Face, then
 * the rail's own signing flow, the same one its screen uses. `onStage` says
 * where it is for the sheet.
 */
export async function approvePaymentIntent(
  intent: PaymentIntent,
  onStage: (stage: 'checking' | 'face' | 'signing') => void = () => {},
): Promise<PaidResult> {
  const apollo = await client();
  const confirm = async () => {
    const { data } = await apollo.mutate({ mutation: CONFIRM, variables: { id: intent.id, displayHash: intent.displayHash } });
    return data?.confirmPaymentIntent;
  };
  onStage('checking');
  let confirmed = await confirm();
  const { ensureFaceCheck, isFaceStepUpRequired } = await import('./faceStepUp');
  if (!confirmed?.success && confirmed?.nextStep === 'verification') {
    // The rail wants the person verified first: that is its own screen.
    throw new PaymentIntentError(
      confirmed.errors?.[0] || 'Primero verifica tu identidad para hacer este pago.', 'verification',
      confirmed.intent ?? null);
  }
  if (!confirmed?.success && isFaceStepUpRequired(confirmed?.nextStep)) {
    // The rail wants Confío Face first: show it, then once more.
    onStage('face');
    if (!(await ensureFaceCheck('withdrawal'))) {
      throw new PaymentIntentError('Necesitas confirmar con tu rostro para pagar.', 'face', confirmed.intent ?? null);
    }
    onStage('checking');
    confirmed = await confirm();
  }
  if (!confirmed?.success) {
    throw new PaymentIntentError(
      confirmed?.errors?.[0] || 'No pude confirmar el pago.', confirmed?.errorCode || '', confirmed?.intent ?? null);
  }

  if (confirmed.signKind === 'journey_bridge') {
    const transfer = confirmed.transfer;
    const tooLate = () => BigInt(transfer.deadline) <= BigInt(Math.floor(Date.now() / 1000) + 45);
    onStage('face');
    const { requestRampCriticalAuth } = await import('../utils/rampFlow');
    const { USD_UNIT } = await import('../utils/rampFormat');
    const authenticated = await requestRampCriticalAuth({
      amount: Number(intent.totalUsd), assetUnit: USD_UNIT, actionLabel: 'envío',
    });
    if (!authenticated) {
      throw new PaymentIntentError('Necesitas confirmar con tu rostro para pagar.', 'face', confirmed.intent ?? null);
    }
    // Authentication can take a while: a transfer past its deadline can no
    // longer be signed, so nothing may be opened for it.
    if (tooLate()) {
      throw new PaymentIntentError('La cotización venció. Cotiza de nuevo para ver el monto actual.', 'expired');
    }
    onStage('signing');
    const { createInfiniaJourney } = await import('./infiniaJourney');
    const { authorizePaymentBridge } = await import('./paymentBridge');
    let journeyId: string | undefined;
    try {
      const journey = await createInfiniaJourney({
        direction: 'to_bank',
        requestId: confirmed.requestId,
        localAccountId: confirmed.localAccountId,
        cryptoAccountId: confirmed.cryptoAccountId,
        minimumFxOutput: confirmed.minimumFxOutput,
        bridgeId: transfer.internalId,
        destinationId: intent.destinationId,
      });
      journeyId = journey.internalId;
      await authorizePaymentBridge(transfer);
    } catch (error: any) {
      if (journeyId || error?.networkError) {
        // The server may have taken it even though no answer arrived: its
        // status is the only way forward, never a second payment.
        throw new PaymentIntentError(
          'No pudimos confirmar si tu pago salió. Revisa su estado antes de pagar otra vez.', 'unsettled', null, true);
      }
      throw new PaymentIntentError(error?.message || 'No pudimos confirmar el pago. Intenta de nuevo.');
    }
    return { journeyId };
  }

  if (confirmed.signKind === 'bsc_send') {
    onStage('signing');
    const { submitPreparedBscSend, BSC_SEND_ERRORS } = await import('./bscSend');
    try {
      await submitPreparedBscSend(confirmed.send);
    } catch (error: any) {
      if (error?.networkError) {
        throw new PaymentIntentError(
          'No pudimos confirmar si tu envío salió. Revisa su estado antes de enviar otra vez.', 'unsettled', null, true);
      }
      throw new PaymentIntentError(BSC_SEND_ERRORS[error?.message] || 'No pudimos enviar. Intenta de nuevo.');
    }
    return { orderId: confirmed.orderId ?? undefined };
  }

  if (confirmed.signKind === 'ramp_order' && intent.methodId === 've_pagomovil_send' && confirmed.orderId) {
    // The Pago Móvil order exists now: fund it from this phone, as its own
    // screen does (services/vePagoMovilSendFunding).
    onStage('signing');
    const { fundVePagoMovilSend, NothingSentError } = await import('./vePagoMovilSendFunding');
    try {
      const outcome = await fundVePagoMovilSend(confirmed.orderId);
      if (outcome === 'unknown') {
        throw new PaymentIntentError(
          'No pudimos confirmar si tus dólares salieron. No envíes de nuevo: revisa el estado en unos minutos.',
          'unsettled', null, true);
      }
    } catch (error: any) {
      if (error instanceof PaymentIntentError) {
        throw error;
      }
      if (error instanceof NothingSentError) {
        // The order stays open and unfunded: its status says so, and it can be cancelled there.
        throw new PaymentIntentError(error.message, 'not_funded', null, true);
      }
      throw new PaymentIntentError(
        'No pudimos confirmar si tus dólares salieron. No envíes de nuevo: revisa el estado en unos minutos.',
        'unsettled', null, true);
    }
    return { orderId: confirmed.orderId };
  }

  // An order on a rail whose funding is still its own screen's (QR Bolivia):
  // it exists now, and that screen finishes it.
  return { orderId: confirmed.orderId ?? undefined, handoff: 'order' };
}

// ── What the card and the sheet say ──

/** How far anyone vouches for the payee's name, in the person's words. */
export function payeeLevelLine(intent: Pick<PaymentIntent, 'payeeLevel' | 'institution'>): { text: string; verified: boolean } {
  const bank = intent.institution || 'su banco';
  switch (intent.payeeLevel) {
    // Verified is only a name someone stands behind. A signed charge or a
    // known institution vouches for the charge, never for the name on it.
    case 'holder_verified': return { text: 'Titular verificado por el banco', verified: true };
    case 'confio_account': return { text: 'Cuenta de Confío', verified: true };
    case 'provider_named': return { text: `Nombre confirmado por ${bank}`, verified: true };
    case 'institution_charge': return { text: `Cobro emitido por ${bank}. El nombre no está verificado`, verified: false };
    case 'institution_amount': return { text: `Monto fijado por ${bank}. El nombre lo escribió quien cobra: no está verificado`, verified: false };
    case 'saved_payee': return { text: 'De tu Agenda. El nombre no está verificado', verified: false };
    case 'signed_charge': return { text: 'Cobro firmado por quien cobra', verified: false };
    case 'signed_amount': return { text: 'Monto firmado por quien cobra', verified: false };
    case 'self_reported': return { text: 'Sin verificar: el nombre lo escribió quien cobra', verified: false };
    default: return { text: 'Sin verificar', verified: false };
  }
}

/** What the card is doing, by the server's status. `open`: it can still be approved. */
export function intentState(intent: Pick<PaymentIntent, 'status' | 'expiresAt'>, now = Date.now()): {
  key: 'open' | 'unsigned' | 'expired' | 'paying' | 'paid' | 'refunded' | 'failed' | 'review' | 'cancelled';
  label: string;
} {
  const expired = Date.parse(intent.expiresAt) <= now;
  switch (intent.status) {
    case 'quoted': return expired ? { key: 'expired', label: 'La cotización venció' } : { key: 'open', label: '' };
    // Confirmed, not signed (the face check was closed, the app was left):
    // nothing moved, and it can still be signed or dropped.
    case 'awaiting_signature': return { key: 'unsigned', label: 'Falta tu firma: todavía no se pagó nada' };
    case 'paying': return { key: 'paying', label: 'Pagando…' };
    case 'paid': return { key: 'paid', label: 'Pagado' };
    case 'refunding': return { key: 'paying', label: 'Devolviendo tu dinero…' };
    case 'refunded': return { key: 'refunded', label: 'No se pagó: te devolvimos el dinero' };
    case 'failed': return { key: 'failed', label: 'No se pudo pagar' };
    case 'under_review': return { key: 'review', label: 'En revisión' };
    case 'cancelled': return { key: 'cancelled', label: 'Cancelado' };
    default: return { key: 'expired', label: 'La cotización venció' };
  }
}

/** "4:12" left on a quote; '' once it is over. */
export function timeLeft(expiresAt: string, now = Date.now()): string {
  const seconds = Math.floor((Date.parse(expiresAt) - now) / 1000);
  if (!(seconds > 0)) {
    return '';
  }
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
