// The sign flow carries the server's refusal code and shows its specific
// copy; the generic "Inténtalo de nuevo" stays for transport/unknown errors.
const mockSubmit = jest.fn();
jest.mock('../../../services/smartAccount', () => ({
  signAndSubmitPrepared: (...a: unknown[]) => mockSubmit(...a),
}));
const mockFace = jest.fn();
jest.mock('../../../services/faceStepUp', () => ({
  FACE_STEP_UP_MESSAGE: 'Confirma que eres tú con tu rostro para continuar.',
  ensureFaceCheck: (...a: unknown[]) => mockFace(...a),
}));

import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { POLICY_COPY, notSentMessage, useSignFlow, type SignFlow } from '../useSignFlow';

const prepared = (over: Record<string, unknown> = {}) => ({
  success: true, errorCode: null, errorMessage: null, requestId: 'req_1',
  calls: [{ to: '0x00000000000000000000000000000000000000aa', valueWei: '0', data: '0x' }],
  notAfter: null, summary: ['x'], ...over,
});

let flow!: SignFlow;
function Probe() {
  flow = useSignFlow();
  return null;
}
let tree: renderer.ReactTestRenderer;
beforeEach(async () => {
  mockSubmit.mockReset();
  mockFace.mockReset();
  await act(async () => { tree = renderer.create(<Probe />); });
});
afterEach(async () => { await act(async () => tree.unmount()); });

const runWith = async (outcome: unknown) => {
  mockSubmit.mockResolvedValue(outcome);
  await act(async () => { await flow.start({ prepare: async () => prepared() as any }); });
  await act(async () => { await flow.confirm(); });
};

it.each([
  ['identity_restricted', /restringidas.*soporte/],
  ['identity_hold', /en revisión/],
  ['payment_due', /pago pendiente/],
  ['smart_action_expired', /venció/],
  ['smart_action_consumed', /ya se había enviado/],
  ['claim_cancel_required', /pedido se cancela/],
  ['recipient_is_smart_account', /es una Cuenta inteligente/],
  ['complex_product_ack_required', /apalancados o inversos/],
  ['beneficiary_residence_unknown', /país de residencia/],
])('%s: carries the code and shows its own copy, without "Inténtalo de nuevo"', async (code, copy) => {
  await runWith({ status: 'not_sent', code });
  expect(flow.state.phase).toBe('failed');
  expect(flow.state.errorCode).toBe(code);
  expect(flow.state.error).toMatch(copy);
  expect(flow.state.error).not.toMatch(/Inténtalo de nuevo|intentarlo de nuevo/);
});

it('an unknown code or transport failure keeps the generic retry copy', async () => {
  await runWith({ status: 'not_sent', code: 'not_sent' });
  expect(flow.state.error).toBe('No pudimos completar la operación. No se movió nada. Inténtalo de nuevo.');
  expect(notSentMessage({ status: 'not_sent', code: 'something_new' })).toMatch(/Inténtalo de nuevo/);
});

it('a refused prepare without a message uses the copy for its code', async () => {
  await act(async () => {
    await flow.start({ prepare: async () => prepared({ success: false, errorCode: 'payment_due' }) as any });
  });
  expect(flow.state.errorCode).toBe('payment_due');
  expect(flow.state.error).toBe(POLICY_COPY.payment_due);
});

it('no policy copy asks to try again', () => {
  Object.values(POLICY_COPY).forEach((c) => expect(c).not.toMatch(/Inténtalo de nuevo|intentarlo de nuevo/));
});

describe('Confío Face step-up (faceStepUp)', () => {
  const FACE = 'Confirma que eres tú con tu rostro para continuar.';
  const faceRequired = () => prepared({
    success: false, errorCode: 'face_required', errorMessage: 'Confirma con Confío Face para programar este envío.',
    requestId: null, calls: null,
  });

  it('runs Face on face_required, prepares once more, then signs', async () => {
    const prepare = jest.fn().mockResolvedValueOnce(faceRequired()).mockResolvedValueOnce(prepared());
    mockFace.mockResolvedValue(true);
    mockSubmit.mockResolvedValue({ status: 'executed', txHash: '0xabc' });
    await act(async () => { await flow.start({ faceStepUp: true, prepare }); });
    expect(mockFace).toHaveBeenCalledWith('withdrawal');
    expect(prepare).toHaveBeenCalledTimes(2);
    expect(flow.state.phase).toBe('confirm');
    await act(async () => { await flow.confirm(); });
    expect(mockSubmit).toHaveBeenCalledTimes(1);
    expect(flow.state.phase).toBe('executed');
  });

  it('a cancelled Face check signs nothing and shows the send flow sentence', async () => {
    const prepare = jest.fn().mockResolvedValue(faceRequired());
    mockFace.mockResolvedValue(false);
    await act(async () => { await flow.start({ faceStepUp: true, prepare }); });
    expect(prepare).toHaveBeenCalledTimes(1);
    expect(flow.state.phase).toBe('failed');
    expect(flow.state.errorCode).toBe('face_required');
    expect(flow.state.error).toBe(FACE);
    await act(async () => { await flow.confirm(); });
    expect(mockSubmit).not.toHaveBeenCalled();
  });

  it('a thrown Face check counts as not passed', async () => {
    mockFace.mockRejectedValue(new Error('boom'));
    await act(async () => { await flow.start({ faceStepUp: true, prepare: async () => faceRequired() as any }); });
    expect(flow.state.error).toBe(FACE);
  });

  it('a second face_required is shown, never looped on', async () => {
    const prepare = jest.fn().mockResolvedValue(faceRequired());
    mockFace.mockResolvedValue(true);
    await act(async () => { await flow.start({ faceStepUp: true, prepare }); });
    expect(mockFace).toHaveBeenCalledTimes(1);
    expect(prepare).toHaveBeenCalledTimes(2);
    expect(flow.state.phase).toBe('failed');
    expect(flow.state.errorCode).toBe('face_required');
    expect(flow.state.error).toBe('Confirma con Confío Face para programar este envío.');
    expect(mockSubmit).not.toHaveBeenCalled();
  });

  it('without faceStepUp, face_required is a plain refusal (no Face shown)', async () => {
    await act(async () => { await flow.start({ prepare: async () => faceRequired() as any }); });
    expect(mockFace).not.toHaveBeenCalled();
    expect(flow.state.phase).toBe('failed');
  });

  it('the identity restriction (sent as face_required) is not answered with Face', async () => {
    const restricted = prepared({
      success: false, errorCode: 'face_required', requestId: null, calls: null,
      errorMessage: 'Las salidas de tu cuenta están temporalmente restringidas. Contacta con soporte.',
    });
    await act(async () => { await flow.start({ faceStepUp: true, prepare: async () => restricted as any }); });
    expect(mockFace).not.toHaveBeenCalled();
    expect(flow.state.error).toMatch(/restringidas/);
  });

  it('a Face refusal at submit runs Face and submits the same batch once more', async () => {
    mockFace.mockResolvedValue(true);
    mockSubmit
      .mockResolvedValueOnce({ status: 'not_sent', code: 'face_required' })
      .mockResolvedValueOnce({ status: 'executed', txHash: '0xabc' });
    await act(async () => { await flow.start({ faceStepUp: true, prepare: async () => prepared() as any }); });
    await act(async () => { await flow.confirm(); });
    expect(mockFace).toHaveBeenCalledTimes(1);
    expect(mockSubmit).toHaveBeenCalledTimes(2);
    expect(mockSubmit.mock.calls[1][0]).toBe(mockSubmit.mock.calls[0][0]);
    expect(flow.state.phase).toBe('executed');
  });

  it('a cancelled Face check at submit does not submit again', async () => {
    mockFace.mockResolvedValue(false);
    mockSubmit.mockResolvedValue({ status: 'not_sent', code: 'face_required' });
    await act(async () => { await flow.start({ faceStepUp: true, prepare: async () => prepared() as any }); });
    await act(async () => { await flow.confirm(); });
    expect(mockSubmit).toHaveBeenCalledTimes(1);
    expect(flow.state.phase).toBe('failed');
    expect(flow.state.error).toBe(FACE);
  });

  it('a second Face refusal at submit is shown, not looped on', async () => {
    mockFace.mockResolvedValue(true);
    mockSubmit.mockResolvedValue({ status: 'not_sent', code: 'face_required' });
    await act(async () => { await flow.start({ faceStepUp: true, prepare: async () => prepared() as any }); });
    await act(async () => { await flow.confirm(); });
    expect(mockFace).toHaveBeenCalledTimes(1);
    expect(mockSubmit).toHaveBeenCalledTimes(2);
    expect(flow.state.errorCode).toBe('face_required');
    expect(flow.state.error).toBe(FACE);
  });
});

describe('new refusal copy', () => {
  it.each([
    ['designation_acceptance_in_progress', /Ya empezaste a aceptar/],
    ['designation_already_accepted', /Ya aceptaste/],
    ['face_required', /con tu rostro/],
  ])('%s has its own copy without "Inténtalo de nuevo"', async (code, copy) => {
    await runWith({ status: 'not_sent', code });
    expect(flow.state.errorCode).toBe(code);
    expect(flow.state.error).toMatch(copy);
    expect(flow.state.error).not.toMatch(/Inténtalo de nuevo/);
  });

  it('stock_quote_window is transient: wait a minute and retry', () => {
    expect(POLICY_COPY.stock_quote_window).toBe(
      'El precio cambió mientras preparábamos la operación. Vuelve a intentarlo en un minuto.');
  });
});
