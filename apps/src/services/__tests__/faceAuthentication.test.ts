import { authenticateWithFace, isFaceAuthenticating } from '../faceAuthentication';
import { ensureFaceCheck, fetchFaceStepUpStatus } from '../faceStepUp';
jest.mock('../faceStepUp', () => ({ ensureFaceCheck: jest.fn(), fetchFaceStepUpStatus: jest.fn(), isFaceCheckActive: () => false }));
const status = fetchFaceStepUpStatus as jest.Mock;
const face = ensureFaceCheck as jest.Mock;
beforeEach(() => { jest.resetAllMocks(); });
it('skips additional authentication only for server-confirmed non-KYC users', async () => {
  status.mockResolvedValue({ enabled: true, required: false });
  expect(await authenticateWithFace()).toBe(true);
  expect(face).not.toHaveBeenCalled();
});
it.each([null, {enabled: false, required: false}, {enabled: true, required: null}])('fails closed on unavailable/unknown policy %j', async value => {
  status.mockResolvedValue(value);
  expect(await authenticateWithFace()).toBe(false);
  expect(face).not.toHaveBeenCalled();
});
it('keeps app unlocking separate and never caches a transaction approval', async () => {
  status.mockResolvedValue({ enabled: true, required: true });
  face.mockImplementation(async () => { expect(isFaceAuthenticating()).toBe(true); return true; });
  await authenticateWithFace('app_unlock');
  await authenticateWithFace();
  await authenticateWithFace();
  expect(face.mock.calls).toEqual([['app_unlock'], ['withdrawal'], ['withdrawal']]);
  expect(isFaceAuthenticating()).toBe(false);
});
it('does not treat cancellation or failure as authorization', async () => {
  status.mockResolvedValue({ enabled: true, required: true });
  face.mockResolvedValue(false);
  expect(await authenticateWithFace()).toBe(false);
  face.mockRejectedValue(new Error('offline'));
  expect(await authenticateWithFace('app_unlock')).toBe(false);
  expect(isFaceAuthenticating()).toBe(false);
});
