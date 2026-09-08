/**
 * Regression tests for how a failed biometric prompt is classified.
 *
 * Incident (Motorola / Galaxy S9 reports, 2026-09): users reported "ya lo
 * activé y me lo sigue pidiendo" — the app kept demanding setup for protection
 * they had already enabled. Cause: enforceBiometricEnrollment() called
 * disable() on ANY failed revalidation, including a plain user cancel, wiping
 * a working enrollment and demanding a fresh enable().
 *
 * Only a genuinely invalidated Keystore key may be treated as void.
 */

// Makes this file a module so its top-level test scaffolding does not collide
// with the sibling fallback suite in the global TS scope.
export {};

type StoredEntry = { username: string; password: string; accessControl?: string };

const mockStore = new Map<string, StoredEntry>();

// Simulates a device where NO user-auth-bound guard key can be read back,
// regardless of the policy it was stored under.
const mockState = {
  allGuardReadsFail: true,
  guardReadError: 'Key user not authenticated',
};

jest.mock('react-native', () => ({
  Platform: { OS: 'android' },
  NativeModules: {
    RNGetRandomValues: {
      getRandomBase64: (byteLength: number) =>
        require('crypto').randomBytes(byteLength).toString('base64'),
    },
  },
}));

jest.mock('react-native-keychain', () => ({
  ACCESS_CONTROL: {
    BIOMETRY_CURRENT_SET_OR_DEVICE_PASSCODE: 'BiometryCurrentSetOrDevicePasscode',
    DEVICE_PASSCODE: 'DevicePasscode',
  },
  ACCESSIBLE: { AFTER_FIRST_UNLOCK: 'AfterFirstUnlock' },
  AUTHENTICATION_TYPE: { DEVICE_PASSCODE_OR_BIOMETRICS: 'AuthenticationWithBiometricsDevicePasscode' },
  SECURITY_LEVEL: { SECURE_SOFTWARE: 'SECURE_SOFTWARE' },
  STORAGE_TYPE: { AUTOMATIC: 'automatic' },
  getSupportedBiometryType: jest.fn().mockResolvedValue('Fingerprint'),
  setGenericPassword: jest.fn(async (username: string, password: string, options: any) => {
    mockStore.set(options.service, { username, password, accessControl: options.accessControl });
    return { service: options.service, storage: 'automatic' };
  }),
  getGenericPassword: jest.fn(async (options: any) => {
    const entry = mockStore.get(options.service);
    if (!entry) return false;
    if (options.service === 'com.confio.biometric.guard' && mockState.allGuardReadsFail) {
      throw new Error(mockState.guardReadError);
    }
    return { username: entry.username, password: entry.password };
  }),
  resetGenericPassword: jest.fn(async (options: any) => {
    mockStore.delete(options.service);
    return true;
  }),
}));

jest.mock('react-native-device-info', () => ({
  isPinOrFingerprintSet: jest.fn().mockResolvedValue(true),
}));

const GUARD_SERVICE = 'com.confio.biometric.guard';
const PREFS_SERVICE = 'com.confio.biometric.prefs';

const freshService = () => {
  let service: any;
  jest.isolateModules(() => {
    service = require('../biometricAuthService').biometricAuthService;
  });
  return service!;
};

/**
 * enforceBiometricEnrollment() used to disable() a WORKING enrollment whenever
 * revalidation returned false — including a plain user cancel — and then demand
 * a fresh enable(). That is the most likely source of "ya lo activé y me lo
 * sigue pidiendo": the app itself wiped the enrollment the user had just made.
 * Only a genuinely invalidated key may be treated as void.
 */
describe('biometricAuthService invalidation classification', () => {
  beforeEach(() => {
    mockStore.clear();
    mockState.allGuardReadsFail = true;
    mockState.guardReadError = 'Key user not authenticated';
    jest.clearAllMocks();
  });

  const primeFailedAuth = async (message: string) => {
    mockState.guardReadError = message;
    mockStore.set(PREFS_SERVICE, { username: 'biometric_pref', password: 'enabled' });
    mockStore.set(GUARD_SERVICE, {
      username: 'biometric_unlock',
      password: 'guard-secret',
      accessControl: 'BiometryCurrentSetOrDevicePasscode',
    });
    const service = freshService();
    expect(await service.authenticate('Valida tu biometría', true, true)).toBe(false);
    return service;
  };

  it('does not treat a cancelled or failed prompt as invalidation', async () => {
    const service = await primeFailedAuth('The user name or passphrase you entered is not correct');
    expect(service.isPermanentInvalidation()).toBe(false);
  });

  it('does not treat a sensor lockout as invalidation', async () => {
    const service = await primeFailedAuth('Too many attempts. Biometry is locked out.');
    expect(service.isLockout()).toBe(true);
    expect(service.isPermanentInvalidation()).toBe(false);
  });

  it('treats a permanently invalidated key as invalidation', async () => {
    const service = await primeFailedAuth(
      'android.security.keystore.KeyPermanentlyInvalidatedException'
    );
    expect(service.isPermanentInvalidation()).toBe(true);
  });

  it('reports no invalidation when nothing has failed yet', async () => {
    const service = freshService();
    expect(service.isPermanentInvalidation()).toBe(false);
  });
});
