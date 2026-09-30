jest.mock('react-native-keychain', () => ({ getGenericPassword: jest.fn(async () => false) }));
jest.mock('../../config/env', () => ({ getApiUrl: () => 'https://example.test/graphql/' }));
jest.mock('../../apollo/client', () => ({ AUTH_KEYCHAIN_SERVICE: 'test', AUTH_KEYCHAIN_USERNAME: 'test' }));
jest.mock('../appCheckService', () => ({ __esModule: true, default: { waitForToken: async () => 'test' } }));
jest.mock('../mobileClientHeaders', () => ({ mobileClientHeaders: () => ({}) }));
jest.mock('../faceStepUp', () => ({
  ensureFaceCheck: jest.fn(async () => true),
  isFaceStepUpRequired: (s: string) => s === 'face_check',
  FaceCheckError: class extends Error {}, FACE_STEP_UP_MESSAGE: 'Face required',
}));

import { createGuardarianTransaction } from '../guardarianService';
import { ensureFaceCheck } from '../faceStepUp';

const response = (status: number, body: object) => ({ status, ok: status === 200, json: async () => body });
const rejection = response(403, { next_step: 'face_check', face_purpose: 'on_ramp', error: 'Face required' });
const params = { amount: 10, fromCurrency: 'EUR' };
const originalFetch = globalThis.fetch;
beforeEach(() => { jest.clearAllMocks(); globalThis.fetch = jest.fn(); (ensureFaceCheck as jest.Mock).mockResolvedValue(true); });
afterAll(() => { globalThis.fetch = originalFetch; });

it('captures Face and retries only the rejected request once', async () => {
  (fetch as jest.Mock).mockResolvedValueOnce(rejection).mockResolvedValueOnce(response(200, { id: 1 }));
  await expect(createGuardarianTransaction(params)).resolves.toEqual({ id: 1 });
  expect(ensureFaceCheck).toHaveBeenCalledWith('on_ramp');
  expect(fetch).toHaveBeenCalledTimes(2);
});
it('does not retry when Face is cancelled', async () => {
  (fetch as jest.Mock).mockResolvedValue(rejection);
  (ensureFaceCheck as jest.Mock).mockResolvedValue(false);
  await expect(createGuardarianTransaction(params)).rejects.toThrow();
  expect(fetch).toHaveBeenCalledTimes(1);
});
it('does not retry ambiguous network failures', async () => {
  (fetch as jest.Mock).mockRejectedValue(new Error('timeout'));
  await expect(createGuardarianTransaction(params)).rejects.toThrow('timeout');
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(ensureFaceCheck).not.toHaveBeenCalled();
});
it('does not loop if the retry is rejected again', async () => {
  (fetch as jest.Mock).mockResolvedValue(rejection);
  await expect(createGuardarianTransaction(params)).rejects.toThrow('Face required');
  expect(fetch).toHaveBeenCalledTimes(2);
});
