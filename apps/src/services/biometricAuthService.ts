import * as Keychain from 'react-native-keychain';
import { Platform } from 'react-native';
import { isPinOrFingerprintSet } from 'react-native-device-info';

const BIOMETRIC_SECRET_SERVICE = 'com.confio.biometric.guard';
const BIOMETRIC_PREFS_SERVICE = 'com.confio.biometric.prefs';
const BIOMETRIC_SECRET_USERNAME = 'biometric_unlock';
const BIOMETRIC_PREFS_USERNAME = 'biometric_pref';

class BiometricAuthService {
  private cachedSupported: boolean | null = null;
  private isAuthenticating: boolean = false;
  private lastAuthenticationTime: number = 0;
  private readonly DEBOUNCE_MS = 1500; // Prevent multiple prompts within 1.5 seconds
  private lastSuccessTime: number = 0;
  private readonly SUCCESS_COOLDOWN_MS = 10000; // Skip new prompts for 10s after a success
  private lastError: string | null = null;
  private lastLockout: boolean = false;

  /**
   * Use a pure passcode policy when the device has no enrolled biometrics.
   * On iOS this makes the system show passcode entry directly instead of forcing
   * users through multiple failed biometric attempts before the fallback appears.
   */
  private getAccessControlForCurrentDevice(
    biometryType: Keychain.BIOMETRY_TYPE | null,
  ): Keychain.ACCESS_CONTROL {
    if (biometryType) {
      return Keychain.ACCESS_CONTROL.BIOMETRY_CURRENT_SET_OR_DEVICE_PASSCODE;
    }

    return Keychain.ACCESS_CONTROL.DEVICE_PASSCODE;
  }

  /**
   * Invalidate the cached biometric support status to force a fresh check.
   */
  invalidateCache(): void {
    this.cachedSupported = null;
  }

  /**
   * Check if the device supports biometric auth (Face ID, Touch ID, Android biometrics).
   */
  async isSupported(): Promise<boolean> {
    if (this.cachedSupported !== null) return this.cachedSupported;
    try {
      const biometryType = await Keychain.getSupportedBiometryType();
      if (biometryType) {
        this.cachedSupported = true;
        return true;
      }

      // Fallback: Check if device has a PIN/Passcode set (since we allow device credential)
      const hasDeviceSecurity = await isPinOrFingerprintSet();
      this.cachedSupported = hasDeviceSecurity;
      return hasDeviceSecurity;
    } catch (error) {
      console.error('[BiometricAuthService] Failed to check biometry support:', error);
      this.cachedSupported = false;
      return false;
    }
  }

  /**
   * Check if the user enabled biometric protection in the app.
   */
  async isEnabled(): Promise<boolean> {
    try {
      const pref = await Keychain.getGenericPassword({
        service: BIOMETRIC_PREFS_SERVICE,
        username: BIOMETRIC_PREFS_USERNAME,
      });
      return !!pref && pref.password.startsWith('enabled');
    } catch (error) {
      console.error('[BiometricAuthService] Failed to read biometric preference:', error);
      return false;
    }
  }

  /**
   * Persist the user's preference (enabled/disabled) without auth prompts.
   * `mode` records which gate the guard secret was stored under so later
   * prompts request matching authenticators ('enabled' keeps backward compat
   * with entries written before the passcode fallback existed).
   */
  private async setPreference(enabled: boolean, mode: 'biometric' | 'passcode' = 'biometric'): Promise<void> {
    if (!enabled) {
      await Keychain.resetGenericPassword({ service: BIOMETRIC_PREFS_SERVICE });
      return;
    }
    await Keychain.setGenericPassword(
      BIOMETRIC_PREFS_USERNAME,
      mode === 'passcode' ? 'enabled:passcode' : 'enabled',
      {
        service: BIOMETRIC_PREFS_SERVICE,
        accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK,
      }
    );
  }

  /**
   * Access control matching how the guard secret was actually stored.
   */
  private async getConfiguredAccessControl(): Promise<Keychain.ACCESS_CONTROL> {
    try {
      const pref = await Keychain.getGenericPassword({
        service: BIOMETRIC_PREFS_SERVICE,
        username: BIOMETRIC_PREFS_USERNAME,
      });
      if (pref && pref.password === 'enabled:passcode') {
        return Keychain.ACCESS_CONTROL.DEVICE_PASSCODE;
      }
    } catch (error) {
      console.warn('[BiometricAuthService] Failed to read gate mode preference:', error);
    }
    const biometryType = await Keychain.getSupportedBiometryType();
    return this.getAccessControlForCurrentDevice(biometryType);
  }

  /**
   * Store a guard secret that can only be unlocked with biometrics (no passcode fallback).
   */
  private async storeBiometricSecret(accessControl: Keychain.ACCESS_CONTROL): Promise<boolean> {
    try {
      // Clear any prior key. On Android, an existing key bound to a previous
      // biometric enrollment set will be invalidated as soon as the user
      // enrolls a new biometric, and subsequent get/set calls throw
      // KeyPermanentlyInvalidatedException. Resetting ensures we always
      // start from a fresh key on each enable() attempt.
      try {
        await Keychain.resetGenericPassword({ service: BIOMETRIC_SECRET_SERVICE });
      } catch (resetError) {
        console.warn('[BiometricAuthService] Failed to reset prior biometric secret:', resetError);
      }

      const randomSecret = `${Date.now()}-${Math.random()}`;
      await Keychain.setGenericPassword(
        BIOMETRIC_SECRET_USERNAME,
        randomSecret,
        {
          service: BIOMETRIC_SECRET_SERVICE,
          accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK,
          accessControl,
          authenticationType: Keychain.AUTHENTICATION_TYPE.DEVICE_PASSCODE_OR_BIOMETRICS,
          securityLevel: Keychain.SECURITY_LEVEL.SECURE_SOFTWARE,
          storage: Keychain.STORAGE_TYPE.AUTOMATIC,
        }
      );
      return true;
    } catch (error) {
      console.error('[BiometricAuthService] Failed to store biometric secret:', error);
      return false;
    }
  }

  /**
   * Store the guard secret under the given policy and verify it with a prompt.
   */
  private async storeAndVerify(accessControl: Keychain.ACCESS_CONTROL): Promise<boolean> {
    const stored = await this.storeBiometricSecret(accessControl);
    if (!stored) return false;
    return this.authenticate('Activa la protección biométrica', true, true, accessControl);
  }

  /**
   * Enable biometric protection (requires a successful biometric prompt).
   */
  async enable(): Promise<boolean> {
    const supported = await this.isSupported();
    if (!supported) return false;

    const biometryType = await Keychain.getSupportedBiometryType();
    const primaryAccessControl = this.getAccessControlForCurrentDevice(biometryType);

    let verified = await this.storeAndVerify(primaryAccessControl);

    // Android fallback: weak (Class 2) fingerprint sensors — common on
    // Xiaomi/MIUI — can pass the biometric prompt but can NEVER unlock a
    // user-auth-bound Keystore key (platform rule: only device credential or
    // strong biometrics do). The biometric-bound attempt then always fails
    // even though the user "authenticated". Retry with a pure
    // device-credential (PIN/pattern) gate, which works on every device.
    let mode: 'biometric' | 'passcode' = 'biometric';
    if (
      !verified &&
      Platform.OS === 'android' &&
      primaryAccessControl !== Keychain.ACCESS_CONTROL.DEVICE_PASSCODE
    ) {
      console.warn('[BiometricAuthService] Biometric-bound enable failed; retrying with device credential gate.');
      verified = await this.storeAndVerify(Keychain.ACCESS_CONTROL.DEVICE_PASSCODE);
      mode = 'passcode';
    }

    if (!verified) {
      await this.disable();
      return false;
    }

    await this.setPreference(true, mode);
    return true;
  }

  /**
   * Disable biometric protection (removes secret + preference).
   */
  async disable(): Promise<void> {
    try {
      await Keychain.resetGenericPassword({ service: BIOMETRIC_SECRET_SERVICE });
    } catch (error) {
      console.error('[BiometricAuthService] Failed to reset biometric secret:', error);
    }
    try {
      await this.setPreference(false);
    } catch (error) {
      console.error('[BiometricAuthService] Failed to reset biometric preference:', error);
    }
  }

  /**
   * Require biometric authentication. Returns true when passed or not enabled.
   */
  async authenticate(
    reason?: string,
    forcePrompt = false,
    failIfUnsupported = false,
    accessControlOverride?: Keychain.ACCESS_CONTROL,
  ): Promise<boolean> {
    this.lastError = null;
    this.lastLockout = false;
    // Debounce: prevent multiple simultaneous authentication prompts
    const now = Date.now();
    const timeSinceLastAuth = now - this.lastAuthenticationTime;
    const timeSinceLastSuccess = now - this.lastSuccessTime;

    if (this.isAuthenticating) {
      return false;
    }

    if (this.lastSuccessTime > 0 && timeSinceLastSuccess < this.SUCCESS_COOLDOWN_MS) {
      return true;
    }

    if (!forcePrompt && timeSinceLastAuth < this.DEBOUNCE_MS) {
      return true; // Return true to avoid blocking the flow
    }

    const enabled = await this.isEnabled();
    if (!forcePrompt && !enabled) return true;

    const supported = await this.isSupported();
    if (!supported) return failIfUnsupported ? false : true;

    try {
      this.isAuthenticating = true;
      this.lastAuthenticationTime = Date.now();
      // Prompt authenticators must match how the guard secret was stored: a
      // passcode-fallback gate would never be unlocked by a fingerprint scan.
      const accessControl = accessControlOverride ?? await this.getConfiguredAccessControl();

      const authResult = await Keychain.getGenericPassword({
        service: BIOMETRIC_SECRET_SERVICE,
        authenticationPrompt: {
          title: 'Confirma tu identidad',
          subtitle: reason || (Platform.OS === 'ios'
            ? 'Usa tu biometría o código para firmar de forma segura'
            : 'Usa tu biometría o patrón para firmar de forma segura'),
          // More security-focused description
          description: 'Protege tus fondos',
        },
        accessControl,
        authenticationType: Keychain.AUTHENTICATION_TYPE.DEVICE_PASSCODE_OR_BIOMETRICS,
        storage: Keychain.STORAGE_TYPE.AUTOMATIC,
      });

      const success = !!authResult && authResult.username === BIOMETRIC_SECRET_USERNAME;
      if (success) {
        this.lastSuccessTime = Date.now();
        this.lastError = null;
        this.lastLockout = false;
      }
      return success;
    } catch (error: any) {
      // Do not allow device passcode fallback; fail closed
      console.warn('[BiometricAuthService] Biometric auth error:', error?.message || error);
      const msg = typeof error?.message === 'string' ? error.message : '';
      const lower = msg.toLowerCase();
      const lockout = lower.includes('lockout') || lower.includes('locked out') || lower.includes('biometry is locked') || lower.includes('lockedout');
      this.lastError = msg || 'Biometric authentication failed';
      this.lastLockout = lockout;
      return false;
    } finally {
      this.isAuthenticating = false;
    }
  }

  getLastError(): string | null {
    return this.lastError;
  }

  isLockout(): boolean {
    return this.lastLockout;
  }
}

export const biometricAuthService = new BiometricAuthService();
