const mockMutate = jest.fn();
const mockQuery = jest.fn();
jest.mock('../../apollo/client', () => ({
  apolloClient: { mutate: (...a: any[]) => mockMutate(...a), query: (...a: any[]) => mockQuery(...a) },
}));
const mockEnsure = jest.fn();
jest.mock('../faceStepUp', () => ({
  ensureFaceCheck: (...a: any[]) => mockEnsure(...a),
  isFaceStepUpRequired: (v?: string | null) =>
    v === 'face_check' || v === 'Confirma que eres tú con tu rostro para continuar.',
}));

import { fetchPendingIncoming, releasePendingIncoming, timeLeft } from '../pendingIncoming';

const payin = { id: 'p1', state: 'awaiting_face', amount: '1200000', asset: 'COP', journeyId: 'j1' };
const released = (ok: boolean, extra: any = {}) => ({
  data: { releasePendingPayins: { success: ok, released: ok ? [payin] : [], ...extra } },
});

describe('pendingIncoming', () => {
  beforeEach(() => { mockMutate.mockReset(); mockQuery.mockReset(); mockEnsure.mockReset(); });

  it('shows the countdown in hours and minutes', () => {
    const now = Date.parse('2026-09-29T10:00:00Z');
    expect(timeLeft('2026-09-30T09:05:00Z', now)).toBe('23 h 5 min');
    expect(timeLeft('2026-09-29T10:12:00Z', now)).toBe('12 min');
    expect(timeLeft('2026-09-29T11:00:00Z', now)).toBe('1 h');
    expect(timeLeft('2026-09-29T10:00:30Z', now)).toBe('menos de 1 min');
  });

  it('hides the feature quietly on a server without it', async () => {
    mockQuery.mockRejectedValueOnce(new Error('Cannot query field "pendingIncomingPayins"'));
    await expect(fetchPendingIncoming()).resolves.toEqual({ items: [] });
  });

  it('reports a failed load as unknown, not as an empty queue', async () => {
    mockQuery.mockRejectedValueOnce(new Error('Network request failed'));
    await expect(fetchPendingIncoming()).resolves.toEqual({ items: null });
  });

  it('returns the queue from the server', async () => {
    mockQuery.mockResolvedValueOnce({ data: { pendingIncomingPayins: [payin] } });
    await expect(fetchPendingIncoming()).resolves.toEqual({ items: [payin] });
  });

  it('asks for the face before releasing the queue', async () => {
    mockEnsure.mockResolvedValue(true);
    mockMutate.mockResolvedValueOnce(released(true));
    await expect(releasePendingIncoming()).resolves.toEqual({ kind: 'released', released: [payin] });
    expect(mockEnsure).toHaveBeenCalledWith('payin_release');
    expect(mockEnsure.mock.invocationCallOrder[0]).toBeLessThan(mockMutate.mock.invocationCallOrder[0]);
  });

  it('never calls the server when the person declines', async () => {
    mockEnsure.mockResolvedValue(false);
    await expect(releasePendingIncoming()).resolves.toEqual({ kind: 'declined' });
    expect(mockMutate).not.toHaveBeenCalled();
  });

  it('confirms once more if the face window lapsed', async () => {
    mockEnsure.mockResolvedValue(true);
    mockMutate
      .mockResolvedValueOnce(released(false, { nextStep: 'face_check' }))
      .mockResolvedValueOnce(released(true));
    await expect(releasePendingIncoming()).resolves.toMatchObject({ kind: 'released' });
    expect(mockEnsure).toHaveBeenCalledTimes(2);
    expect(mockMutate).toHaveBeenCalledTimes(2);
  });

  it('surfaces a server error without retrying', async () => {
    mockEnsure.mockResolvedValue(true);
    mockMutate.mockResolvedValueOnce(released(false, { error: 'Algo salió mal' }));
    await expect(releasePendingIncoming()).resolves.toEqual({ kind: 'error', message: 'Algo salió mal' });
    expect(mockMutate).toHaveBeenCalledTimes(1);
  });
});

describe('pending incoming deep link', () => {
  it('opens the pending screen from the push link and keeps receipts working', () => {
    const { localTransferRoute, PENDING_INCOMING_URL } = require('../localTransferNavigation');
    expect(localTransferRoute(PENDING_INCOMING_URL)).toEqual({ screen: 'PendingIncoming', params: undefined });
    const id = '0b8c7a52-1d2e-4c3f-9a1b-2c3d4e5f6a7b';
    expect(localTransferRoute(`confio://local-transfer/${id}`)).toEqual({ screen: 'LocalTransferStatus', params: { journeyId: id } });
    expect(localTransferRoute('confio://pending-incoming/evil')).toBeNull();
  });
});

describe('unresolved pay-ins stay reachable', () => {
  const { isUnresolved } = require('../pendingIncoming');
  it('keeps confirmed money visible until a journey takes over or the return is final', () => {
    expect(isUnresolved({ state: 'releasing', journeyId: null })).toBe(true);
    expect(isUnresolved({ state: 'releasing', journeyId: 'j1' })).toBe(false);
    expect(isUnresolved({ state: 'review' })).toBe(true);
    expect(isUnresolved({ state: 'returning' })).toBe(true);
    expect(isUnresolved({ state: 'return_failed' })).toBe(true);
    expect(isUnresolved({ state: 'returned' })).toBe(false);
    expect(isUnresolved({ state: 'awaiting_face' })).toBe(false);
  });
});
