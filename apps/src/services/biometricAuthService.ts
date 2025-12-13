import * as Keychain from 'react-native-keychain';
import { Platform } from 'react-native';

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
      const supported = !!biometryType;
      this.cachedSupported = supported;
      return supported;
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
      return !!pref && pref.password === 'enabled';
    } catch (error) {
      console.error('[BiometricAuthService] Failed to read biometric preference:', error);
      return false;
    }
  }

  /**
   * Persist the user's preference (enabled/disabled) without auth prompts.
   */
  private async setPreference(enabled: boolean): Promise<void> {
    if (!enabled) {
      await Keychain.resetGenericPassword({ service: BIOMETRIC_PREFS_SERVICE });
      return;
    }
    await Keychain.setGenericPassword(
      BIOMETRIC_PREFS_USERNAME,
      'enabled',
      {
        service: BIOMETRIC_PREFS_SERVICE,
        accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED,
      }
    );
  }

  /**
   * Store a guard secret that can only be unlocked with biometrics (no passcode fallback).
   */
  private async storeBiometricSecret(): Promise<boolean> {
    try {
      const randomSecret = `${Date.now()}-${Math.random()}`;
      await Keychain.setGenericPassword(
        BIOMETRIC_SECRET_USERNAME,
        randomSecret,
        {
          service: BIOMETRIC_SECRET_SERVICE,
          accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED,
          accessControl: Platform.OS === 'android'
            ? Keychain.ACCESS_CONTROL.BIOMETRY_ANY
            : Keychain.ACCESS_CONTROL.BIOMETRY_CURRENT_SET,
          authenticationType: Keychain.AUTHENTICATION_TYPE.BIOMETRICS,
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
   * Enable biometric protection (requires a successful biometric prompt).
   */
  async enable(): Promise<boolean> {
    const supported = await this.isSupported();
    if (!supported) return false;

    // Check current secret; if missing, create one under biometric-only policy
    const stored = await this.storeBiometricSecret();
    if (!stored) {
      return false;
    }

    // Verify immediately to ensure biometric prompt works and no passcode fallback is offered
    const verified = await this.authenticate('Activa la protección biométrica', true, true);
    if (!verified) {
      await this.disable();
      return false;
    }

    await this.setPreference(true);
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
  async authenticate(reason?: string, forcePrompt = false, failIfUnsupported = false): Promise<boolean> {
    this.lastError = null;
    this.lastLockout = false;
    // Debounce: prevent multiple simultaneous authentication prompts
    const now = Date.now();
    const timeSinceLastAuth = now - this.lastAuthenticationTime;
    const timeSinceLastSuccess = now - this.lastSuccessTime;

    if (this.isAuthenticating) {
      console.log('[BiometricAuthService] Authentication already in progress, skipping duplicate prompt');
      return false;
    }

    if (this.lastSuccessTime > 0 && timeSinceLastSuccess < this.SUCCESS_COOLDOWN_MS) {
      console.log('[BiometricAuthService] Recent successful biometric (< cooldown), skipping new prompt');
      return true;
    }

    if (!forcePrompt && timeSinceLastAuth < this.DEBOUNCE_MS) {
      console.log('[BiometricAuthService] Authentication requested too soon after last attempt, skipping (debounce)');
      return true; // Return true to avoid blocking the flow
    }

    const enabled = await this.isEnabled();
    if (!forcePrompt && !enabled) return true;

    const supported = await this.isSupported();
    if (!supported) return failIfUnsupported ? false : true;

    try {
      this.isAuthenticating = true;
      this.lastAuthenticationTime = Date.now();

      console.log('[BiometricAuthService] Prompting for biometric authentication:', reason);

      const authResult = await Keychain.getGenericPassword({
        service: BIOMETRIC_SECRET_SERVICE,
        authenticationPrompt: {
          title: 'Confirma tu identidad',
          subtitle: reason || (Platform.OS === 'ios'
            ? 'Usa Face ID o Touch ID para firmar de forma segura'
            : 'Usa tu huella digital para firmar de forma segura'),
          // More security-focused description
          description: 'Protege tus fondos',
        },
        accessControl: Platform.OS === 'android'
          ? Keychain.ACCESS_CONTROL.BIOMETRY_ANY
          : Keychain.ACCESS_CONTROL.BIOMETRY_CURRENT_SET,
        authenticationType: Keychain.AUTHENTICATION_TYPE.BIOMETRICS,
        storage: Keychain.STORAGE_TYPE.AUTOMATIC,
      });

      const success = !!authResult && authResult.username === BIOMETRIC_SECRET_USERNAME;
      if (!success) {
        console.warn('[BiometricAuthService] Biometric auth failed or was cancelled');
      } else {
        this.lastSuccessTime = Date.now();
        this.lastError = null;
        this.lastLockout = false;
        console.log('[BiometricAuthService] Biometric authentication successful');
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
