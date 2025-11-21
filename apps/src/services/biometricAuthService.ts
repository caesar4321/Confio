import * as Keychain from 'react-native-keychain';

const BIOMETRIC_SECRET_SERVICE = 'com.confio.biometric.guard';
const BIOMETRIC_PREFS_SERVICE = 'com.confio.biometric.prefs';
const BIOMETRIC_SECRET_USERNAME = 'biometric_unlock';
const BIOMETRIC_PREFS_USERNAME = 'biometric_pref';

class BiometricAuthService {
  private cachedSupported: boolean | null = null;

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
          accessControl: Keychain.ACCESS_CONTROL.BIOMETRY_CURRENT_SET,
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
    const enabled = await this.isEnabled();
    if (!forcePrompt && !enabled) return true;
    
    const supported = await this.isSupported();
    if (!supported) return failIfUnsupported ? false : true;

    try {
      const authResult = await Keychain.getGenericPassword({
        service: BIOMETRIC_SECRET_SERVICE,
        authenticationPrompt: {
          title: 'Confirma con biometría',
          subtitle: reason || 'Face ID / Touch ID o huella para proteger tus operaciones',
          // Keep description short to avoid cramped Android prompt layout
          description: 'Requerido para envíos y pagos',
        },
        accessControl: Keychain.ACCESS_CONTROL.BIOMETRY_CURRENT_SET,
        authenticationType: Keychain.AUTHENTICATION_TYPE.BIOMETRICS,
        storage: Keychain.STORAGE_TYPE.AUTOMATIC,
      });

      const success = !!authResult && authResult.username === BIOMETRIC_SECRET_USERNAME;
      if (!success) {
        console.warn('[BiometricAuthService] Biometric auth failed or was cancelled');
      }
      return success;
    } catch (error: any) {
      // Do not allow device passcode fallback; fail closed
      console.warn('[BiometricAuthService] Biometric auth error:', error?.message || error);
      return false;
    }
  }
}

export const biometricAuthService = new BiometricAuthService();
