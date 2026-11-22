// Approving a prepared payment: the server confirms, Confío Face, then the
// rail's own signing flow. Nothing is signed for figures that changed.
const mockMutate = jest.fn();
const mockFace = jest.fn(async () => true);
const mockCriticalAuth = jest.fn(async () => true);
const mockCreateJourney = jest.fn(async () => ({ internalId: 'journey-1' }));
const mockAuthorize = jest.fn(async () => ({}));
const mockSubmitSend = jest.fn(async () => ({}));
const mockFundPagoMovil = jest.fn(async (): Promise<'sent' | 'unknown'> => 'sent');

jest.mock('../../apollo/client', () => ({ apolloClient: { mutate: (...args: unknown[]) => mockMutate(...args) } }));
jest.mock('../paymentBridge', () => ({
  FIELDS: require('@apollo/client').gql`fragment PaymentBridgeFields on PaymentBridgeTransferType { internalId }`,
  authorizePaymentBridge: (...args: unknown[]) => mockAuthorize(...(args as [])),
}));
jest.mock('../faceStepUp', () => ({
  ensureFaceCheck: (...args: unknown[]) => mockFace(...(args as [])),
  isFaceStepUpRequired: (step?: string | null) => step === 'face',
}));
jest.mock('../../utils/rampFlow', () => ({ requestRampCriticalAuth: (...args: unknown[]) => mockCriticalAuth(...(args as [])) }));
jest.mock('../../utils/rampFormat', () => ({ USD_UNIT: 'US$' }));
jest.mock('../infiniaJourney', () => ({ createInfiniaJourney: (...args: unknown[]) => mockCreateJourney(...(args as [])) }));
jest.mock('../bscSend', () => ({
  BSC_SEND_ERRORS: { insufficient_balance: 'Saldo insuficiente.' },
  submitPreparedBscSend: (...args: unknown[]) => mockSubmitSend(...(args as [])),
}));

jest.mock('../vePagoMovilSendFunding', () => {
  class NothingSentError extends Error {}
  return { NothingSentError, fundVePagoMovilSend: (...args: unknown[]) => mockFundPagoMovil(...(args as [])) };
});

import {
  PaymentIntentError, approvePaymentIntent, prepareRequestInChat, intentState, payeeLevelLine, preparePaymentInChat, timeLeft,
  type PaymentIntent,
} from '../paymentIntent';

const intent: PaymentIntent = {
  id: 'intent-1', status: 'quoted', statusReason: '', methodId: 'br_qr', family: 'local_charge', destinationId: 'dest-1',
  payeeName: 'Padaria Pão Quente', payeeLevel: 'institution_charge', payeeAccount: '', payeeDocument: '', institution: 'Itaú',
  amountExact: true, amountLocal: '42.50', currency: 'BRL', totalUsd: '8.12', feeUsd: '0.10', rate: '5.30',
  expiresAt: new Date(Date.now() + 240_000).toISOString(), displayHash: 'hash-1',
};
const far = String(Math.floor(Date.now() / 1000) + 600);
const bridge = (over: object = {}) => ({ data: { confirmPaymentIntent: {
  success: true, signKind: 'journey_bridge', transfer: { internalId: 'bridge-1', deadline: far },
  requestId: 'req-1', localAccountId: 'local-1', cryptoAccountId: 'crypto-1', minimumFxOutput: '42.50', ...over,
} } });
const refused = (errorCode: string, message: string, over: object = {}) => ({ data: { confirmPaymentIntent: {
  success: false, errors: [message], errorCode, ...over,
} } });
const stages: string[] = [];
const approve = () => approvePaymentIntent(intent, (s) => { stages.push(s); });

beforeEach(() => {
  jest.clearAllMocks();
  stages.length = 0;
  mockFace.mockResolvedValue(true);
  mockCriticalAuth.mockResolvedValue(true);
  mockCreateJourney.mockResolvedValue({ internalId: 'journey-1' });
  mockAuthorize.mockResolvedValue({});
});

describe('a Pix or QR charge', () => {
  it('confirms the figures the person saw, asks for the face, opens the journey and signs', async () => {
    mockMutate.mockResolvedValueOnce(bridge());
    await expect(approve()).resolves.toEqual({ journeyId: 'journey-1' });
    expect(mockMutate.mock.calls[0][0].variables).toEqual({ id: 'intent-1', displayHash: 'hash-1' });
    expect(mockCriticalAuth).toHaveBeenCalledWith({ amount: 8.12, assetUnit: 'US$', actionLabel: 'envío' });
    expect(mockCreateJourney).toHaveBeenCalledWith({
      direction: 'to_bank', requestId: 'req-1', localAccountId: 'local-1', cryptoAccountId: 'crypto-1',
      minimumFxOutput: '42.50', bridgeId: 'bridge-1', destinationId: 'dest-1',
    });
    expect(mockAuthorize).toHaveBeenCalledWith({ internalId: 'bridge-1', deadline: far });
    expect(stages).toEqual(['checking', 'face', 'signing']);
  });

  it('figures that changed are refused before anything is asked or signed', async () => {
    const current = { ...intent, status: 'expired' };
    mockMutate.mockResolvedValueOnce(refused('charge_changed', 'El comercio cambió este cobro.', { intent: current }));
    const error = await approve().catch((e) => e);
    expect(error).toBeInstanceOf(PaymentIntentError);
    expect(error).toMatchObject({ message: 'El comercio cambió este cobro.', code: 'charge_changed', intent: current, unsettled: false });
    expect(mockCriticalAuth).not.toHaveBeenCalled();
    expect(mockCreateJourney).not.toHaveBeenCalled();
    expect(mockAuthorize).not.toHaveBeenCalled();
  });

  it('no face, no payment', async () => {
    mockMutate.mockResolvedValueOnce(bridge());
    mockCriticalAuth.mockResolvedValue(false);
    await expect(approve()).rejects.toMatchObject({ code: 'face' });
    expect(mockCreateJourney).not.toHaveBeenCalled();
  });

  it('a transfer that ran out while the person authenticated is never opened', async () => {
    mockMutate.mockResolvedValueOnce(bridge({ transfer: { internalId: 'bridge-1', deadline: String(Math.floor(Date.now() / 1000) + 10) } }));
    await expect(approve()).rejects.toMatchObject({ code: 'expired' });
    expect(mockCreateJourney).not.toHaveBeenCalled();
  });

  it('refused before the journey exists: said plainly, safe to try again', async () => {
    mockMutate.mockResolvedValueOnce(bridge());
    mockCreateJourney.mockRejectedValue(new Error('Saldo insuficiente'));
    await expect(approve()).rejects.toMatchObject({ message: 'Saldo insuficiente', unsettled: false });
    expect(mockAuthorize).not.toHaveBeenCalled();
  });

  it('once the journey exists, a failure is "check its status", never "try again"', async () => {
    mockMutate.mockResolvedValueOnce(bridge());
    mockAuthorize.mockRejectedValue(new Error('timeout'));
    await expect(approve()).rejects.toMatchObject({ code: 'unsettled', unsettled: true });
    // The same when the request left the phone and no answer came back.
    mockMutate.mockResolvedValueOnce(bridge());
    mockCreateJourney.mockRejectedValue(Object.assign(new Error('Network request failed'), { networkError: {} }));
    await expect(approve()).rejects.toMatchObject({ unsettled: true });
  });
});

describe('the other rails', () => {
  it('a rail that wants Confío Face first: shown, then confirmed once more', async () => {
    const send = { sendId: 'send-1', calls: [], intentId: '0xabc' };
    mockMutate
      .mockResolvedValueOnce(refused('', 'Confirma con tu rostro', { nextStep: 'face' }))
      .mockResolvedValueOnce({ data: { confirmPaymentIntent: { success: true, signKind: 'bsc_send', orderId: 'send-1', send } } });
    await expect(approve()).resolves.toEqual({ orderId: 'send-1' });
    expect(mockFace).toHaveBeenCalledWith('withdrawal');
    expect(mockMutate).toHaveBeenCalledTimes(2);
    expect(mockSubmitSend).toHaveBeenCalledWith(send);
    // Refused there: nothing is confirmed a second time.
    mockMutate.mockResolvedValueOnce(refused('', 'Confirma con tu rostro', { nextStep: 'face' }));
    mockFace.mockResolvedValue(false);
    await expect(approve()).rejects.toMatchObject({ code: 'face' });
    expect(mockMutate).toHaveBeenCalledTimes(3);
  });

  it('a rail that wants the person verified first is not answered with a face check', async () => {
    mockMutate.mockResolvedValueOnce(refused('', 'Verifica tu identidad para enviar.', { nextStep: 'verification' }));
    await expect(approve()).rejects.toMatchObject({ code: 'verification', message: 'Verifica tu identidad para enviar.' });
    expect(mockFace).not.toHaveBeenCalled();
    expect(mockMutate).toHaveBeenCalledTimes(1);
  });

  it('a Confío send that fails says why in the person\'s words', async () => {
    mockMutate.mockResolvedValueOnce({ data: { confirmPaymentIntent: { success: true, signKind: 'bsc_send', send: {} } } });
    mockSubmitSend.mockRejectedValueOnce(new Error('insufficient_balance'));
    await expect(approve()).rejects.toMatchObject({ message: 'Saldo insuficiente.', unsettled: false });
  });

  it('a Pago Móvil order is funded from this phone, in the sheet', async () => {
    const order = { data: { confirmPaymentIntent: { success: true, signKind: 'ramp_order', orderId: 'order-9' } } };
    const pagoMovil = { ...intent, methodId: 've_pagomovil_send', family: 'ramp_order' };
    mockMutate.mockResolvedValueOnce(order);
    await expect(approvePaymentIntent(pagoMovil)).resolves.toEqual({ orderId: 'order-9' });
    expect(mockFundPagoMovil).toHaveBeenCalledWith('order-9');
    // Broadcast with no verdict: never "try again".
    mockMutate.mockResolvedValueOnce(order);
    mockFundPagoMovil.mockResolvedValueOnce('unknown');
    await expect(approvePaymentIntent(pagoMovil)).rejects.toMatchObject({ code: 'unsettled', unsettled: true });
    // Nothing left the wallet: said in those words; the order's own status takes it from there.
    const { NothingSentError } = require('../vePagoMovilSendFunding');
    mockMutate.mockResolvedValueOnce(order);
    mockFundPagoMovil.mockRejectedValueOnce(new NothingSentError('No tienes saldo suficiente. No se envió nada.'));
    await expect(approvePaymentIntent(pagoMovil)).rejects.toMatchObject({
      message: 'No tienes saldo suficiente. No se envió nada.', code: 'not_funded' });
  });

  it('an order with its own funding steps is handed to its screen', async () => {
    mockMutate.mockResolvedValueOnce({ data: { confirmPaymentIntent: { success: true, signKind: 'ramp_order', orderId: 'order-9' } } });
    await expect(approve()).resolves.toEqual({ orderId: 'order-9', handoff: 'order' });
    expect(mockSubmitSend).not.toHaveBeenCalled();
    expect(mockCreateJourney).not.toHaveBeenCalled();
  });
});

describe('a code handed to the chat', () => {
  it('becomes a card in the thread, or a refusal with its code', async () => {
    mockMutate.mockResolvedValueOnce({ data: { preparePaymentIntent: { success: true, intent } } });
    await expect(preparePaymentInChat('000201…', 'shared_qr')).resolves.toBe(intent);
    expect(mockMutate.mock.calls[0][0].variables).toEqual({ code: '000201…', source: 'shared_qr', inChat: true });
    mockMutate.mockResolvedValueOnce({ data: { preparePaymentIntent: {
      success: false, errors: ['Todavía no puedo preparar pagos desde aquí.'], errorCode: 'unavailable' } } });
    await expect(preparePaymentInChat('000201…', 'shared_qr')).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('details typed into a form go as a request, never as a code', async () => {
    mockMutate.mockResolvedValueOnce({ data: { preparePaymentIntent: { success: true, intent } } });
    const request = { methodId: 've_pagomovil_send', phone: '04141234567', cedula: 'V12345678', bankCode: '0134', amountUsd: '20' };
    await expect(prepareRequestInChat(request)).resolves.toBe(intent);
    expect(mockMutate.mock.calls[0][0].variables).toEqual({ source: 'form', inChat: true, request });
  });
});

describe('what the card says', () => {
  it('how far the payee\'s name is vouched for', () => {
    expect(payeeLevelLine({ payeeLevel: 'holder_verified', institution: '' })).toEqual({ text: 'Titular verificado por el banco', verified: true });
    expect(payeeLevelLine({ payeeLevel: 'confio_account', institution: '' }).verified).toBe(true);
    expect(payeeLevelLine({ payeeLevel: 'provider_named', institution: 'Itaú' }).verified).toBe(true);
    // An institution behind the charge is not behind the name; nor is the owner's own Agenda.
    expect(payeeLevelLine({ payeeLevel: 'institution_charge', institution: 'Itaú' }))
      .toEqual({ text: 'Cobro emitido por Itaú. El nombre no está verificado', verified: false });
    expect(payeeLevelLine({ payeeLevel: 'institution_amount', institution: 'Mercado Pago' }))
      .toEqual({ text: 'Monto fijado por Mercado Pago. El nombre lo escribió quien cobra: no está verificado', verified: false });
    expect(payeeLevelLine({ payeeLevel: 'saved_payee', institution: '' }))
      .toEqual({ text: 'De tu Agenda. El nombre no está verificado', verified: false });
    // Anything nobody stands behind is said as a warning, never as a tick.
    for (const level of ['signed_charge', 'signed_amount', 'self_reported', 'unverified', 'something_new']) {
      expect(payeeLevelLine({ payeeLevel: level, institution: '' }).verified).toBe(false);
    }
  });

  it('the server\'s status, and never "paid" before it says so', () => {
    const at = (status: string, ms = 60_000) => intentState({ status, expiresAt: new Date(Date.now() + ms).toISOString() });
    expect(at('quoted').key).toBe('open');
    expect(at('quoted', -1).key).toBe('expired');
    // Confirmed and not signed: nothing moved, and it can still be signed.
    expect(at('awaiting_signature').key).toBe('unsigned');
    expect(at('paying')).toEqual({ key: 'paying', label: 'Pagando…' });
    expect(at('paid')).toEqual({ key: 'paid', label: 'Pagado' });
    expect(at('refunded').key).toBe('refunded');
    expect(at('under_review').key).toBe('review');
    expect(at('a_status_from_the_future').key).toBe('expired');
    expect(timeLeft(new Date(Date.now() + 252_500).toISOString())).toBe('4:12');
    expect(timeLeft(new Date(Date.now() - 1).toISOString())).toBe('');
  });
});
