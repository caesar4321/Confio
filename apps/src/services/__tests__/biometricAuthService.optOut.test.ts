/**
 * Regression tests for the device-protection opt-out.
 *
 * Incident (Motorola / Galaxy S9 reports, 2026-09): users with a PIN AND a
 * fingerprint enrolled were stuck forever on BiometricSetupScreen ("ya lo
 * activé y me lo sigue pidiendo"). isSupported() returns true for them, so the
 * unsupported-device escape in enforceBiometricEnrollment never fires, but the
 * guard key cannot be created or read back under EITHER policy — the weak-
 * sensor fallback to DEVICE_PASSCODE fails too. enable() then always returns
 * false and there was no way into the app.
 *
 * The opt-out is the escape hatch. It must (a) release the signing prompts as
 * well as the setup gate, or the dead end simply moves to the first send/pay,
 * and (b) be superseded by a later successful enable(), or the guard would
 * report itself enabled while authenticate() kept short-circuiting.
 */

type StoredEntry = { username: string; password: string; accessControl?: string };

const mockStore = new Map<string, StoredEntry>();

// Simulates a device where NO user-auth-bound guard key can be read back,
// regardless of the policy it was stored under.
const mockState = { allGuardReadsFail: true };

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
const OPTOUT_SERVICE = 'com.confio.biometric.optout';

const freshService = () => {
  let service: any;
  jest.isolateModules(() => {
    service = require('../biometricAuthService').biometricAuthService;
  });
  return service!;
};

describe('biometricAuthService device-protection opt-out', () => {
  beforeEach(() => {
    mockStore.clear();
    mockState.allGuardReadsFail = true;
    jest.clearAllMocks();
  });

  it('reproduces the dead end: enrolled device where neither gate can be enabled', async () => {
    const service = freshService();

    expect(await service.isSupported()).toBe(true);
    expect(await service.enable()).toBe(false);
    expect(await service.isOptedOut()).toBe(false);
  });

  it('releases the signing prompts, not just the setup gate', async () => {
    const service = freshService();
    await service.enable();

    await service.optOut();

    expect(await service.isOptedOut()).toBe(true);
    // forcePrompt + failIfUnsupported: the exact call the send/pay gates make.
    expect(await service.authenticate('Confirma tu envío', true, true)).toBe(true);
  });

  it('keeps the opt-out marker out of the preferences service disable() resets', async () => {
    const service = freshService();

    await service.optOut();

    expect(mockStore.get(OPTOUT_SERVICE)?.password).toBe('opted_out');
    // optOut() calls disable() internally; the marker must outlive that reset.
    expect(mockStore.has(PREFS_SERVICE)).toBe(false);
    expect(await service.isEnabled()).toBe(false);
  });

  it('is superseded by a later successful enable()', async () => {
    const service = freshService();
    await service.optOut();
    expect(await service.isOptedOut()).toBe(true);

    // User re-enables from Profile on a device that now works.
    mockState.allGuardReadsFail = false;
    expect(await service.enable()).toBe(true);

    expect(await service.isOptedOut()).toBe(false);
    expect(mockStore.get(GUARD_SERVICE)?.accessControl).toBe('BiometryCurrentSetOrDevicePasscode');
  });

  it('still prompts during enable() verification while opted out', async () => {
    const Keychain = require('react-native-keychain');
    const service = freshService();
    await service.optOut();
    mockState.allGuardReadsFail = false;
    (Keychain.getGenericPassword as jest.Mock).mockClear();

    await service.enable();

    // enable() passes an accessControlOverride, which must bypass the
    // short-circuit — otherwise it would "succeed" without ever verifying.
    const guardRead = (Keychain.getGenericPassword as jest.Mock).mock.calls.find(
      ([options]) => options.service === GUARD_SERVICE
    );
    expect(guardRead).toBeDefined();
  });
});
