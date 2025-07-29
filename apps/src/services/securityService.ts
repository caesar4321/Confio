/**
 * Security Service for Confío
 * Handles device fingerprinting and security-related operations
 */

import DeviceFingerprint from '../utils/deviceFingerprint';
import { apolloClient } from '../apollo/client';
import { gql } from '@apollo/client';

// GraphQL mutations for security operations
const TRUST_DEVICE_MUTATION = gql`
  mutation TrustDevice($verificationCode: String!, $deviceFingerprint: JSONString!, $trustReason: String) {
    trustDevice(verificationCode: $verificationCode, deviceFingerprint: $deviceFingerprint, trustReason: $trustReason) {
      success
      error
      device {
        id
        isTrusted
        deviceName
      }
    }
  }
`;

const REQUEST_DEVICE_TRUST_MUTATION = gql`
  mutation RequestDeviceTrust($deviceFingerprint: JSONString!, $method: String) {
    requestDeviceTrust(deviceFingerprint: $deviceFingerprint, method: $method) {
      success
      error
      message
    }
  }
`;

// KYC mutations removed - not needed for blockchain MVP

// Queries for security data
const MY_DEVICES_QUERY = gql`
  query MyDevices {
    myDevices {
      id
      isTrusted
      deviceName
      firstUsed
      lastUsed
      totalSessions
    }
  }
`;

// KYC queries removed - not needed for blockchain MVP

export class SecurityService {
  private static instance: SecurityService;
  private deviceFingerprint: any = null;
  private deviceFingerprintHash: string | null = null;
  private isFingerprintReady = false;

  private constructor() {}

  public static getInstance(): SecurityService {
    if (!SecurityService.instance) {
      SecurityService.instance = new SecurityService();
    }
    return SecurityService.instance;
  }

  /**
   * Initialize device fingerprinting
   */
  public async initializeFingerprinting(): Promise<void> {
    console.log('SecurityService - Initializing device fingerprinting...');
    
    try {
      this.deviceFingerprint = await DeviceFingerprint.generateFingerprint();
      this.deviceFingerprintHash = await DeviceFingerprint.generateHash(this.deviceFingerprint);
      this.isFingerprintReady = true;
      
      console.log('SecurityService - Device fingerprinting initialized');
      console.log('SecurityService - Fingerprint hash:', this.deviceFingerprintHash);
    } catch (error) {
      console.error('SecurityService - Failed to initialize fingerprinting:', error);
      // Use fallback fingerprint
      this.deviceFingerprint = await DeviceFingerprint.getFallbackFingerprint();
      this.deviceFingerprintHash = await DeviceFingerprint.generateHash(this.deviceFingerprint);
      this.isFingerprintReady = true;
    }
  }

  /**
   * Get current device fingerprint
   */
  public async getDeviceFingerprint(): Promise<{ fingerprint: any; hash: string }> {
    if (!this.isFingerprintReady) {
      await this.initializeFingerprinting();
    }

    return {
      fingerprint: this.deviceFingerprint,
      hash: this.deviceFingerprintHash!
    };
  }

  /**
   * Get quick fingerprint for frequent operations
   */
  public async getQuickFingerprint(): Promise<any> {
    try {
      return await DeviceFingerprint.getQuickFingerprint();
    } catch (error) {
      console.error('SecurityService - Error getting quick fingerprint:', error);
      return {
        platform: 'unknown',
        timestamp: new Date().toISOString(),
        error: true
      };
    }
  }

  /**
   * Enhanced authentication with device fingerprinting
   */
  public async performSecureAuthentication(authData: any): Promise<{ 
    authData: any; 
    deviceFingerprint: any; 
    fingerprintHash: string;
    securityFlags: {
      isNewDevice: boolean;
      isTrustedDevice: boolean;
      requiresDeviceTrust: boolean;
    }
  }> {
    const { fingerprint, hash } = await this.getDeviceFingerprint();
    
    // Check device trust status by querying existing devices
    const { isNewDevice, isTrustedDevice } = await this.checkDeviceStatus(hash);
    
    const securityFlags = {
      isNewDevice,
      isTrustedDevice,
      requiresDeviceTrust: isNewDevice && !isTrustedDevice
    };

    console.log('SecurityService - Secure authentication completed');
    console.log('SecurityService - Security flags:', securityFlags);

    return {
      authData,
      deviceFingerprint: fingerprint,
      fingerprintHash: hash,
      securityFlags
    };
  }

  /**
   * Check device status against known devices
   */
  private async checkDeviceStatus(fingerprintHash: string): Promise<{
    isNewDevice: boolean;
    isTrustedDevice: boolean;
  }> {
    try {
      // Try to get user's devices (requires authentication)
      const { data } = await apolloClient.query({
        query: MY_DEVICES_QUERY,
        errorPolicy: 'ignore' // Don't throw on auth errors
      });

      if (data && data.myDevices) {
        // Check if current device exists in user's devices
        const currentDevice = data.myDevices.find((device: any) => 
          device.deviceName === this.generateDeviceName() // We'll need to match somehow
        );

        return {
          isNewDevice: !currentDevice,
          isTrustedDevice: currentDevice ? currentDevice.isTrusted : false
        };
      }
    } catch (error) {
      console.log('SecurityService - Could not check device status (probably not authenticated yet)');
    }

    // Default to new device if we can't check
    return {
      isNewDevice: true,
      isTrustedDevice: false
    };
  }

  /**
   * Generate a device name for display purposes
   */
  private generateDeviceName(): string {
    if (!this.deviceFingerprint) return 'Unknown Device';
    
    const { systemInfo, screenInfo } = this.deviceFingerprint;
    const platform = systemInfo?.platform || 'Unknown';
    const model = systemInfo?.model || 'Device';
    const screenSize = screenInfo?.screenSize || 'unknown';
    
    return `${model} (${platform}) - ${screenSize}`;
  }

  /**
   * Request device trust verification
   */
  public async requestDeviceTrust(method: 'email' | 'sms' = 'email'): Promise<{
    success: boolean;
    message?: string;
    error?: string;
  }> {
    try {
      const { fingerprint } = await this.getDeviceFingerprint();
      
      const { data } = await apolloClient.mutate({
        mutation: REQUEST_DEVICE_TRUST_MUTATION,
        variables: {
          deviceFingerprint: JSON.stringify(fingerprint),
          method
        }
      });

      return data.requestDeviceTrust;
    } catch (error) {
      console.error('SecurityService - Error requesting device trust:', error);
      return {
        success: false,
        error: 'Failed to request device trust verification'
      };
    }
  }

  /**
   * Verify device trust with code
   */
  public async verifyDeviceTrust(verificationCode: string, trustReason?: string): Promise<{
    success: boolean;
    device?: any;
    error?: string;
  }> {
    try {
      const { fingerprint } = await this.getDeviceFingerprint();
      
      const { data } = await apolloClient.mutate({
        mutation: TRUST_DEVICE_MUTATION,
        variables: {
          verificationCode,
          deviceFingerprint: JSON.stringify(fingerprint),
          trustReason
        }
      });

      return data.trustDevice;
    } catch (error) {
      console.error('SecurityService - Error verifying device trust:', error);
      return {
        success: false,
        error: 'Failed to verify device trust'
      };
    }
  }

  // KYC requirement check removed - not needed for blockchain MVP

  /**
   * Get user's devices
   */
  public async getUserDevices(): Promise<any[]> {
    try {
      const { data } = await apolloClient.query({
        query: MY_DEVICES_QUERY,
        fetchPolicy: 'network-only'
      });

      return data.myDevices || [];
    } catch (error) {
      console.error('SecurityService - Error getting user devices:', error);
      return [];
    }
  }

  // KYC status check removed - not needed for blockchain MVP

  /**
   * Prepare fingerprint data for API calls
   */
  public async getFingerprintForAPI(): Promise<{
    device_fingerprint?: string;
    screen_resolution?: string;
    timezone?: string;
    user_agent?: string;
    platform?: string;
  }> {
    try {
      const { fingerprint } = await this.getDeviceFingerprint();
      
      return {
        device_fingerprint: JSON.stringify(fingerprint),
        screen_resolution: `${fingerprint.screenInfo?.screenWidth}x${fingerprint.screenInfo?.screenHeight}`,
        timezone: fingerprint.localeInfo?.timezone,
        user_agent: `Confío/${fingerprint.systemInfo?.platform || 'unknown'}`,
        platform: fingerprint.systemInfo?.platform
      };
    } catch (error) {
      console.error('SecurityService - Error preparing fingerprint for API:', error);
      return {};
    }
  }

  /**
   * Clear stored behavioral data (for privacy)
   */
  public async clearStoredData(): Promise<boolean> {
    try {
      return await DeviceFingerprint.clearStoredData();
    } catch (error) {
      console.error('SecurityService - Error clearing stored data:', error);
      return false;
    }
  }

  /**
   * Check if fingerprinting is ready
   */
  public isReady(): boolean {
    return this.isFingerprintReady;
  }

  /**
   * Get fingerprint readiness status
   */
  public getStatus(): {
    isReady: boolean;
    hasFingerprint: boolean;
    hasHash: boolean;
  } {
    return {
      isReady: this.isFingerprintReady,
      hasFingerprint: this.deviceFingerprint !== null,
      hasHash: this.deviceFingerprintHash !== null
    };
  }
}

export default SecurityService;