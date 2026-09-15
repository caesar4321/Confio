const mockMutate = jest.fn();
const mockAttest = jest.fn();
const mockRequestMultiple = jest.fn();
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
    RESULTS: {GRANTED: 'granted', NEVER_ASK_AGAIN: 'never_ask_again'}, requestMultiple: (...args: any[]) => mockRequestMultiple(...args)},
}));
import {applyCobreBreb, withBrebLocationRetry, verifyBrebLocation, brebLocationPassValid, BREB_PERMISSION_ERROR,
  requestBrebLocationPermission, brebLocationPassRemainingMs} from '../brebLocation';
import {Platform} from 'react-native';

beforeEach(() => {jest.resetAllMocks(); Platform.OS = 'android'; Object.defineProperty(Platform, 'Version', {value: '17', configurable: true});});
test('denied precision never requests challenge', async () => {
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
  expect(await withBrebLocationRetry(operation)).toEqual(denied);
  expect(operation).toHaveBeenCalledTimes(2);
  expect(mockAttest).toHaveBeenCalledTimes(1);
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
