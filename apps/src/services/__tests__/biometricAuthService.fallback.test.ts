/**
 * Regression tests for the device-credential fallback in biometricAuthService.
 *
 * Incident (user 10090, 2026-07-02, Redmi Note 14 Pro+ 5G): on Android devices
 * whose fingerprint sensor is classified WEAK (Class 2) — common on
 * Xiaomi/MIUI — the biometric prompt succeeds but can never unlock the
 * user-auth-bound Keystore key (platform rule: only device credential or
 * STRONG biometrics do). enable() then always failed and onboarding was
 * blocked at BiometricSetupScreen ("no me lee la huella") even though the
 * user had fingerprint + PIN enrolled. The fix retries with a pure
 * DEVICE_PASSCODE gate and persists that mode for later prompts.
 */

type StoredEntry = { username: string; password: string; accessControl?: string };

const mockStore = new Map<string, StoredEntry>();

// Simulates a MIUI device with a weak-classified sensor: reads of the guard
// secret fail whenever it was stored under a biometric-bound policy.
const mockState = { biometricBoundReadsFail: true };

jest.mock('react-native', () => ({
  Platform: { OS: 'android' },
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
    if (
      options.service === 'com.confio.biometric.guard' &&
      mockState.biometricBoundReadsFail &&
      entry.accessControl === 'BiometryCurrentSetOrDevicePasscode'
    ) {
      throw new Error('Key user not authenticated');
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

// The service is a stateful singleton (auth cooldowns); import it fresh per test.
const freshService = () => {
  let service: any;
  jest.isolateModules(() => {
    service = require('../biometricAuthService').biometricAuthService;
  });
  return service!;
};

describe('biometricAuthService weak-sensor fallback', () => {
  beforeEach(() => {
    mockStore.clear();
    mockState.biometricBoundReadsFail = true;
    jest.clearAllMocks();
  });

  it('falls back to a device-credential gate when the biometric-bound gate cannot be verified', async () => {
    const service = freshService();

    const enabled = await service.enable();

    expect(enabled).toBe(true);
    expect(mockStore.get(GUARD_SERVICE)?.accessControl).toBe('DevicePasscode');
    expect(mockStore.get(PREFS_SERVICE)?.password).toBe('enabled:passcode');
  });

  it('keeps the biometric gate on devices where it works', async () => {
    mockState.biometricBoundReadsFail = false;
    const service = freshService();

    const enabled = await service.enable();

    expect(enabled).toBe(true);
    expect(mockStore.get(GUARD_SERVICE)?.accessControl).toBe('BiometryCurrentSetOrDevicePasscode');
    expect(mockStore.get(PREFS_SERVICE)?.password).toBe('enabled');
  });

  it('prompts with the persisted passcode gate on later authentications', async () => {
    const Keychain = require('react-native-keychain');
    // Simulate a prior fallback enrollment persisted on the device.
    mockStore.set(PREFS_SERVICE, { username: 'biometric_pref', password: 'enabled:passcode' });
    mockStore.set(GUARD_SERVICE, {
      username: 'biometric_unlock',
      password: 'guard-secret',
      accessControl: 'DevicePasscode',
    });
    const service = freshService();

    const ok = await service.authenticate('Desbloquea Confío', true, true);

    expect(ok).toBe(true);
    const guardRead = (Keychain.getGenericPassword as jest.Mock).mock.calls.find(
      ([options]) => options.service === GUARD_SERVICE
    );
    expect(guardRead?.[0]?.accessControl).toBe('DevicePasscode');
  });
});
