const mockMutate = jest.fn();
jest.mock('../../apollo/client', () => ({ apolloClient: { mutate: (...args: any[]) => mockMutate(...args) } }));

import { NativeModules } from 'react-native';
import {
  FACE_STEP_UP_MESSAGE,
  FaceCheckError,
  ensureFaceCheck,
  isFaceStepUpRequired,
  registerFaceCheckPresenter,
  runFaceCapture,
  withFaceStepUp,
} from '../faceStepUp';

const started = {
  data: {
    startFaceCheck: {
      success: true, sessionId: 'sess-1', region: 'eu-central-1', accessKeyId: 'AK',
      secretAccessKey: 'SK', sessionToken: 'ST', expiration: '2026-09-29T20:15:00+00:00',
    },
  },
};
const completed = (passed: boolean, error?: string) => ({
  data: { completeFaceCheck: { success: error === undefined || passed, passed, error } },
});
const pending = {
  data: { completeFaceCheck: {
    success: false, passed: false,
    error: 'Todavía estamos procesando tu verificación. Intenta de nuevo en unos segundos.',
  } },
};

describe('faceStepUp', () => {
  const start = jest.fn();

  beforeEach(() => {
    jest.useRealTimers();
    mockMutate.mockReset();
    start.mockReset().mockResolvedValue('complete');
    (NativeModules as any).ConfioFaceLiveness = { start };
    registerFaceCheckPresenter(null);
  });

  it('recognizes both ways the server asks for a face', () => {
    expect(isFaceStepUpRequired('face_check')).toBe(true);
    expect(isFaceStepUpRequired(FACE_STEP_UP_MESSAGE)).toBe(true);
    expect(isFaceStepUpRequired('rate_limited')).toBe(false);
    expect(isFaceStepUpRequired(undefined)).toBe(false);
  });

  it('passes scoped credentials to the native capture and returns the server grade', async () => {
    mockMutate.mockResolvedValueOnce(started).mockResolvedValueOnce(completed(true));
    await expect(runFaceCapture('withdrawal')).resolves.toEqual({ outcome: 'passed' });
    expect(start).toHaveBeenCalledWith('sess-1', 'eu-central-1', {
      accessKeyId: 'AK', secretAccessKey: 'SK', sessionToken: 'ST',
      expirationEpochSeconds: Math.floor(Date.parse('2026-09-29T20:15:00+00:00') / 1000),
    });
  });

  it('keeps asking while AWS is still processing the video', async () => {
    jest.useFakeTimers();
    mockMutate.mockResolvedValueOnce(started).mockResolvedValueOnce(pending).mockResolvedValueOnce(completed(true));
    const result = runFaceCapture('on_ramp');
    await jest.advanceTimersByTimeAsync(1600);
    await expect(result).resolves.toEqual({ outcome: 'passed' });
    expect(mockMutate).toHaveBeenCalledTimes(3);
  });

  it('reports a cancelled capture without asking the server to grade it', async () => {
    mockMutate.mockResolvedValueOnce(started);
    start.mockRejectedValueOnce(Object.assign(new Error('Cancelled'), { code: 'UserCancelledException' }));
    await expect(runFaceCapture('on_ramp')).resolves.toEqual({ outcome: 'cancelled' });
    expect(mockMutate).toHaveBeenCalledTimes(1);
  });

  it('explains a denied camera instead of grading an empty session', async () => {
    mockMutate.mockResolvedValueOnce(started);
    start.mockRejectedValueOnce(Object.assign(new Error('denied'), { code: 'camera_permission_denied' }));
    const result = await runFaceCapture('withdrawal');
    expect(result.outcome).toBe('unavailable');
    expect(result.message).toMatch(/cámara/);
    expect(mockMutate).toHaveBeenCalledTimes(1);
  });

  it('gives up on a start request that never answers', async () => {
    jest.useFakeTimers();
    mockMutate.mockReturnValueOnce(new Promise(() => {}));
    const result = runFaceCapture('on_ramp');
    await jest.advanceTimersByTimeAsync(20001);
    await expect(result).resolves.toMatchObject({ outcome: 'unavailable' });
    expect(start).not.toHaveBeenCalled();
  });

  it('stops grading after hung requests instead of spinning forever', async () => {
    jest.useFakeTimers();
    mockMutate.mockResolvedValueOnce(started).mockReturnValue(new Promise(() => {}));
    const result = runFaceCapture('on_ramp');
    await jest.advanceTimersByTimeAsync(8 * (15000 + 1500) + 100);
    await expect(result).resolves.toMatchObject({ outcome: 'failed' });
  });

  it('is unavailable on an app build without the native module', async () => {
    (NativeModules as any).ConfioFaceLiveness = undefined;
    const result = await runFaceCapture('on_ramp');
    expect(result.outcome).toBe('unavailable');
    expect(mockMutate).not.toHaveBeenCalled();
  });

  it('retries the action once after a passed check', async () => {
    registerFaceCheckPresenter(async () => true);
    const action = jest.fn()
      .mockResolvedValueOnce({ nextStep: 'face_check' })
      .mockResolvedValueOnce({ nextStep: 'ok' });
    await expect(withFaceStepUp('on_ramp', action, (r: any) => isFaceStepUpRequired(r.nextStep)))
      .resolves.toEqual({ nextStep: 'ok' });
    expect(action).toHaveBeenCalledTimes(2);
  });

  it('stops when the person declines the check', async () => {
    registerFaceCheckPresenter(async () => false);
    const action = jest.fn().mockResolvedValue({ nextStep: 'face_check' });
    await expect(withFaceStepUp('withdrawal', action, (r: any) => isFaceStepUpRequired(r.nextStep)))
      .rejects.toBeInstanceOf(FaceCheckError);
    expect(action).toHaveBeenCalledTimes(1);
  });

  it('never passes without a mounted presenter', async () => {
    await expect(ensureFaceCheck('withdrawal')).resolves.toBe(false);
  });
});
