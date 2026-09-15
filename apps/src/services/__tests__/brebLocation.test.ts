const mockMutate = jest.fn();
const mockAttest = jest.fn();
const mockRequestMultiple = jest.fn();
const mockCheckPermission = jest.fn();
const mockAppleKey = jest.fn();
const mockAppleAttest = jest.fn();
const mockAppleRequest = jest.fn();
jest.mock('../../apollo/client', () => ({apolloClient: {mutate: (...args: any[]) => mockMutate(...args)}}));
jest.mock('react-native', () => ({
  Platform: {OS: 'android', Version: '17'}, NativeModules: {
    BrebLocation: {attest: (...args: any[]) => mockAttest(...args)},
    BrebAppleLocation: {keyId: () => mockAppleKey(), attest: (...args: any[]) => mockAppleAttest(...args),
      requestPermission: () => mockAppleRequest()},
  },
  PermissionsAndroid: {PERMISSIONS: {ACCESS_FINE_LOCATION: 'fine', ACCESS_COARSE_LOCATION: 'coarse'},
    check: (...args: any[]) => mockCheckPermission(...args),
    RESULTS: {GRANTED: 'granted', NEVER_ASK_AGAIN: 'never_ask_again'}, requestMultiple: (...args: any[]) => mockRequestMultiple(...args)},
}));
import {applyCobreBreb, withBrebLocationRetry, verifyBrebLocation, brebLocationPassValid, BREB_PERMISSION_ERROR,
  requestBrebLocationPermission, brebLocationPassRemainingMs, isBrebLocationFailure,
  onBrebLocationPassChange} from '../brebLocation';
import {Platform} from 'react-native';

beforeEach(() => {jest.resetAllMocks(); mockCheckPermission.mockResolvedValue(true); Platform.OS = 'android'; Object.defineProperty(Platform, 'Version', {value: '17', configurable: true});});
test('denied precision never requests challenge', async () => {
  mockCheckPermission.mockResolvedValue(false);
  mockRequestMultiple.mockResolvedValue({fine: 'denied'});
  await expect(applyCobreBreb()).rejects.toThrow('ubicación precisa');
  expect(mockMutate).not.toHaveBeenCalled();
});
test('older iOS cannot use the Android attestation path', async () => {
  Platform.OS = 'ios';
  Object.defineProperty(Platform, 'Version', {value: '14', configurable: true});
  await expect(applyCobreBreb()).rejects.toThrow('Actualiza');
  expect(mockMutate).not.toHaveBeenCalled();
});

test('iOS sends a request-bound Apple envelope, without Android configuration', async () => {
  Platform.OS = 'ios';
  mockAppleRequest.mockResolvedValue('granted');
  mockAppleKey.mockResolvedValue('key');
  mockAppleAttest.mockResolvedValue({locationJson: '{"mocked":false}', integrityToken: 'apple-assertion'});
  mockMutate.mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'ios-challenge', keyRegistered: true}}})
    .mockResolvedValueOnce({data: {verifyBrebLocation: {success: true, validUntil: Date.now()/1000 + 900}}});
  await verifyBrebLocation('ios-user');
  expect(mockMutate.mock.calls[0][0].variables).toEqual({platform: 'ios', keyId: 'key'});
  expect(mockAppleAttest).toHaveBeenCalledWith('ios-challenge', true);
  expect(mockRequestMultiple).not.toHaveBeenCalled();
  expect(mockAttest).not.toHaveBeenCalled();
  expect(mockMutate.mock.calls[1][0].variables.integrityToken).toBe('apple-assertion');
});
test('iOS asks for location before any key or server step', async () => {
  Platform.OS = 'ios';
  const order: string[] = [];
  mockAppleRequest.mockImplementation(async () => {order.push('permission'); return 'granted';});
  mockAppleKey.mockImplementation(async () => {order.push('key'); return 'key';});
  // A server that cannot issue a challenge (not configured, offline) fails after the prompt, not instead of it.
  mockMutate.mockImplementation(async () => {order.push('server'); throw new Error('Network request failed');});
  await expect(verifyBrebLocation('ios-user')).rejects.toThrow('Network request failed');
  expect(order).toEqual(['permission', 'key', 'server']);
});
test.each([['denied'], ['reduced']])('iOS %s location stops before the server, marked as a permission refusal', async state => {
  Platform.OS = 'ios';
  mockAppleRequest.mockResolvedValue(state);
  const error: any = await verifyBrebLocation('ios-user').catch(e => e);
  expect(error.code).toBe(BREB_PERMISSION_ERROR);
  expect(mockAppleKey).not.toHaveBeenCalled();
  expect(mockMutate).not.toHaveBeenCalled();
  expect(mockAppleAttest).not.toHaveBeenCalled();
});
test('Android maps the system answers (approximate only, never ask again)', async () => {
  mockRequestMultiple.mockResolvedValueOnce({fine: 'denied', coarse: 'granted'});
  expect(await requestBrebLocationPermission()).toBe('reduced');
  mockRequestMultiple.mockResolvedValueOnce({fine: 'never_ask_again', coarse: 'never_ask_again'});
  expect(await requestBrebLocationPermission()).toBe('blocked');
  mockRequestMultiple.mockResolvedValueOnce({fine: 'denied', coarse: 'denied'});
  mockCheckPermission.mockResolvedValue(false);
  const error: any = await applyCobreBreb().catch(e => e);
  expect(error.code).toBe(BREB_PERMISSION_ERROR);
  expect(mockMutate).not.toHaveBeenCalled();
});
test('native evidence is passed unchanged with its challenge', async () => {
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockMutate.mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge', cloudProjectNumber: '123456789'}}})
    .mockResolvedValueOnce({data: {applyCobreBreb: {success: true, value: '@key'}}});
  mockAttest.mockResolvedValue({locationJson: '{"mocked":false}', integrityToken: 'signed'});
  await expect(applyCobreBreb()).resolves.toBe('@key');
  expect(mockAttest).toHaveBeenCalledWith('challenge', '123456789');
  expect(mockMutate.mock.calls[1][0].variables).toEqual({challenge: 'challenge', locationJson: '{"mocked":false}', integrityToken: 'signed'});
});
test('an application grants the scope its location pass', async () => {
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockAttest.mockResolvedValue({locationJson: '{}', integrityToken: 'signed'});
  mockMutate.mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge', cloudProjectNumber: '123456789'}}})
    .mockResolvedValueOnce({data: {applyCobreBreb: {success: true, value: '@key', validUntil: Date.now()/1000 + 900}}});
  await expect(applyCobreBreb('apply-scope')).resolves.toBe('@key');
  expect(brebLocationPassValid('apply-scope')).toBe(true);
  expect(brebLocationPassRemainingMs('apply-scope')).toBeGreaterThan(800000);
  expect(brebLocationPassRemainingMs('other-scope')).toBe(0);
});
test('native verification failure never submits application', async () => {
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockMutate.mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge', cloudProjectNumber: '123456789'}}});
  mockAttest.mockRejectedValue(new Error('Mock location'));
  await expect(applyCobreBreb()).rejects.toThrow('Mock location');
  expect(mockMutate).toHaveBeenCalledTimes(1);
});

test('explicit expired-pass refusal verifies then retries once', async () => {
  const denied = {success: false, errors: ['Verifica tu ubicación para usar Bre-B.']};
  const operation = jest.fn().mockResolvedValue(denied);
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockAttest.mockResolvedValue({locationJson: '{}', integrityToken: 'signed'});
  mockMutate.mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge', cloudProjectNumber: '123456789'}}})
    .mockResolvedValueOnce({data: {verifyBrebLocation: {success: true, validUntil: 123}}});
  // Refused again after the new check: a location failure to recover from, never a third attempt.
  expect(isBrebLocationFailure(await withBrebLocationRetry(operation).catch(e => e))).toBe(true);
  expect(operation).toHaveBeenCalledTimes(2);
  expect(mockAttest).toHaveBeenCalledTimes(1);
});

test('a failed location step is marked as one, keeping its message and code', async () => {
  mockCheckPermission.mockResolvedValue(false);
  const operation = jest.fn().mockResolvedValue({success: false, errors: ['Verifica tu ubicación para usar Bre-B.']});
  mockRequestMultiple.mockResolvedValue({fine: 'never_ask_again', coarse: 'never_ask_again'});
  const error: any = await withBrebLocationRetry(operation).catch(e => e);
  expect(isBrebLocationFailure(error)).toBe(true);
  expect(error.code).toBe(BREB_PERMISSION_ERROR);
  expect(operation).toHaveBeenCalledTimes(1);
  // An operation's own failure is not a location failure.
  const own: any = await withBrebLocationRetry(async () => { throw new Error('timeout'); }).catch(e => e);
  expect(isBrebLocationFailure(own)).toBe(false);
});
test('an explicit refusal forgets the cached pass', async () => {
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockAttest.mockResolvedValue({locationJson: '{}', integrityToken: 'signed'});
  mockMutate.mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge', cloudProjectNumber: '123456789'}}})
    .mockResolvedValueOnce({data: {verifyBrebLocation: {success: true, validUntil: Date.now()/1000 + 900}}});
  await verifyBrebLocation('cached-scope');
  expect(brebLocationPassValid('cached-scope')).toBe(true);
  // An automatic retry never prompts: it uses the permission that already exists.
  mockCheckPermission.mockResolvedValue(false);
  const operation = jest.fn().mockResolvedValue({success: false, errors: ['Verifica tu ubicación para usar Bre-B.']});
  await expect(withBrebLocationRetry(operation)).rejects.toThrow('ubicación precisa');
  expect(brebLocationPassValid('cached-scope')).toBe(false);
});
test('a stalled location request is bounded and releases the caller', async () => {
  jest.useFakeTimers();
  try {
    mockRequestMultiple.mockResolvedValue({fine: 'granted'}); // the explicit check asks, and is allowed
    mockMutate.mockReturnValue(new Promise(() => {})); // the challenge never answers
    const pending = verifyBrebLocation('stall-scope').catch(error => error);
    await jest.advanceTimersByTimeAsync(20001);
    expect((await pending).message).toContain('tardó demasiado');
  } finally {
    jest.useRealTimers();
  }
});
test('screens hear every pass change: granted and forgotten', async () => {
  const listener = jest.fn();
  const stop = onBrebLocationPassChange(listener);
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockAttest.mockResolvedValue({locationJson: '{}', integrityToken: 'signed'});
  mockMutate.mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge', cloudProjectNumber: '123456789'}}})
    .mockResolvedValueOnce({data: {verifyBrebLocation: {success: true, validUntil: Date.now()/1000 + 900}}});
  await verifyBrebLocation('heard-scope');
  expect(listener).toHaveBeenCalledTimes(1);
  mockCheckPermission.mockResolvedValue(false);
  await withBrebLocationRetry(async () => ({success: false, errors: ['Verifica tu ubicación para usar Bre-B.']})).catch(() => {});
  expect(listener).toHaveBeenCalledTimes(2);
  stop();
});
test('a successful automatic check restores that account\'s pass', async () => {
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockAttest.mockResolvedValue({locationJson: '{}', integrityToken: 'signed'});
  mockMutate.mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge', cloudProjectNumber: '123456789'}}})
    .mockResolvedValueOnce({data: {verifyBrebLocation: {success: true, validUntil: Date.now()/1000 + 900}}})
    .mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge-2', cloudProjectNumber: '123456789'}}})
    .mockResolvedValueOnce({data: {verifyBrebLocation: {success: true, validUntil: Date.now()/1000 + 900}}});
  await verifyBrebLocation('restore-scope');
  const listener = jest.fn();
  const stop = onBrebLocationPassChange(listener);
  const operation = jest.fn()
    .mockResolvedValueOnce({success: false, errors: ['Verifica tu ubicación para usar Bre-B.']})
    .mockResolvedValueOnce({success: true});
  expect(await withBrebLocationRetry(operation)).toEqual({success: true});
  expect(brebLocationPassValid('restore-scope')).toBe(true);
  expect(listener).toHaveBeenCalledTimes(2); // forgotten, then restored
  stop();
});
test('a second refusal after a new check forgets the pass and asks for recovery', async () => {
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockAttest.mockResolvedValue({locationJson: '{}', integrityToken: 'signed'});
  mockMutate.mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge', cloudProjectNumber: '123456789'}}})
    .mockResolvedValueOnce({data: {verifyBrebLocation: {success: true, validUntil: Date.now()/1000 + 900}}})
    .mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge-2', cloudProjectNumber: '123456789'}}})
    .mockResolvedValueOnce({data: {verifyBrebLocation: {success: true, validUntil: Date.now()/1000 + 900}}});
  await verifyBrebLocation('twice-scope');
  const refused = {success: false, errors: ['Verifica tu ubicación para usar Bre-B.']};
  const operation = jest.fn().mockResolvedValue(refused);
  const error: any = await withBrebLocationRetry(operation).catch(e => e);
  expect(isBrebLocationFailure(error)).toBe(true);
  expect(operation).toHaveBeenCalledTimes(2); // never a third automatic attempt
  expect(brebLocationPassValid('twice-scope')).toBe(false);
});
test('a late answer for another account never replaces a newer pass', async () => {
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockAttest.mockResolvedValue({locationJson: '{}', integrityToken: 'signed'});
  const challenge = (id: string) => ({data: {brebLocationChallenge: {success: true, challenge: id, cloudProjectNumber: '123456789'}}});
  const verified = () => ({data: {verifyBrebLocation: {success: true, validUntil: Date.now()/1000 + 900}}});
  let answerA!: (value: any) => void;
  mockMutate
    .mockReturnValueOnce(new Promise(resolve => { answerA = resolve; })) // A's challenge is slow
    .mockResolvedValueOnce(challenge('b')).mockResolvedValueOnce(verified()) // B, answered at once
    .mockResolvedValueOnce(verified()); // A's verification, answered last
  const first = verifyBrebLocation('user:A:1');
  await verifyBrebLocation('user:B:2');
  expect(brebLocationPassValid('user:B:2')).toBe(true);
  answerA(challenge('a'));
  await first;
  expect(brebLocationPassValid('user:B:2')).toBe(true);
  expect(brebLocationPassValid('user:A:1')).toBe(false);
});
test('an answer started before a refusal cannot restore the refused pass', async () => {
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockAttest.mockResolvedValue({locationJson: '{}', integrityToken: 'signed'});
  let answerLate!: (value: any) => void;
  mockMutate
    .mockReturnValueOnce(new Promise(resolve => { answerLate = resolve; })) // a slow check's challenge
    .mockResolvedValueOnce({data: {verifyBrebLocation: {success: true, validUntil: Date.now()/1000 + 900}}});
  const late = verifyBrebLocation('late-scope');
  await Promise.resolve();
  // Meanwhile an operation is refused and its automatic recovery fails.
  mockCheckPermission.mockResolvedValue(false);
  const refused = {success: false, errors: ['Verifica tu ubicación para usar Bre-B.']};
  await withBrebLocationRetry(async () => refused).catch(() => {});
  answerLate({data: {brebLocationChallenge: {success: true, challenge: 'late', cloudProjectNumber: '123456789'}}});
  await late;
  expect(brebLocationPassValid('late-scope')).toBe(false);
});
test('ambiguous network failure and other refusals never retry', async () => {
  const operation = jest.fn().mockRejectedValue(new Error('timeout'));
  await expect(withBrebLocationRetry(operation)).rejects.toThrow('timeout');
  expect(operation).toHaveBeenCalledTimes(1);
  const denied = {success: false, errors: ['Other error']};
  expect(await withBrebLocationRetry(async () => denied)).toEqual(denied);
  expect(mockMutate).not.toHaveBeenCalled();
});

test('failed verification never retries financial operation', async () => {
  const operation = jest.fn().mockResolvedValue({success: false, errors: ['Verifica tu ubicación para usar Bre-B.']});
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockAttest.mockRejectedValue(new Error('Mock location'));
  mockMutate.mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge', cloudProjectNumber: '123456789'}}});
  await expect(withBrebLocationRetry(operation)).rejects.toThrow('Mock location');
  expect(operation).toHaveBeenCalledTimes(1);
});

test('screen pass cache never crosses user/account scopes', async () => {
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockAttest.mockResolvedValue({locationJson: '{}', integrityToken: 'signed'});
  mockMutate.mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge', cloudProjectNumber: '123456789'}}})
    .mockResolvedValueOnce({data: {verifyBrebLocation: {success: true, validUntil: Date.now()/1000 + 900}}});
  await verifyBrebLocation('userA:personal_0:1');
  expect(brebLocationPassValid('userA:personal_0:1')).toBe(true);
  expect(brebLocationPassValid('userB:personal_0:1')).toBe(false);
  expect(brebLocationPassValid('userA:personal_1:2')).toBe(false);
  expect(brebLocationPassValid('')).toBe(false);
});

test('expired verification response cannot open the screen', async () => {
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockAttest.mockResolvedValue({locationJson: '{}', integrityToken: 'signed'});
  mockMutate.mockResolvedValueOnce({data: {brebLocationChallenge: {success: true, challenge: 'challenge', cloudProjectNumber: '123456789'}}})
    .mockResolvedValueOnce({data: {verifyBrebLocation: {success: true, validUntil: 1}}});
  await expect(verifyBrebLocation('expired')).rejects.toThrow('verificar');
  expect(brebLocationPassValid('expired')).toBe(false);
});

test.each([false, true])('automatic retry never prompts (permission already granted: %s)', async allowed => {
  mockCheckPermission.mockResolvedValue(allowed);
  const operation = jest.fn().mockResolvedValue({success: false, errors: ['Verifica tu ubicación para usar Bre-B.']});
  mockMutate.mockRejectedValue(new Error('server unavailable'));
  const error = await withBrebLocationRetry(operation).catch(e => e);
  expect(isBrebLocationFailure(error)).toBe(true);
  expect(mockRequestMultiple).not.toHaveBeenCalled();
  expect(operation).toHaveBeenCalledTimes(1);
  if (!allowed) expect(mockMutate).not.toHaveBeenCalled();
});
test('application requires existing permission without prompting', async () => {
  mockCheckPermission.mockResolvedValue(false);
  await expect(applyCobreBreb()).rejects.toThrow('ubicación precisa');
  expect(mockRequestMultiple).not.toHaveBeenCalled();
  expect(mockMutate).not.toHaveBeenCalled();
});
test('silent screen check cannot prompt if permission was revoked after focus', async () => {
  mockCheckPermission.mockResolvedValue(false);
  await expect(verifyBrebLocation('scope', false)).rejects.toThrow('ubicación precisa');
  expect(mockRequestMultiple).not.toHaveBeenCalled();
  expect(mockMutate).not.toHaveBeenCalled();
});
test('Android location screen explicitly requests permission before contacting the server', async () => {
  mockCheckPermission.mockResolvedValue(false);
  mockRequestMultiple.mockResolvedValue({fine: 'granted'});
  mockMutate.mockRejectedValue(new Error('La verificación de ubicación aún no está disponible.'));
  await expect(verifyBrebLocation('scope', true)).rejects.toThrow('aún no está disponible');
  expect(mockRequestMultiple).toHaveBeenCalledTimes(1);
  expect(mockRequestMultiple.mock.invocationCallOrder[0]).toBeLessThan(mockMutate.mock.invocationCallOrder[0]);
});
