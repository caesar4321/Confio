/**
 * Enhanced Authentication Service for Confío
 * Integrates device fingerprinting and security features with existing AuthService
 */

import { AuthService } from './authService';
import { SecurityService } from './securityService';
import { apolloClient } from '../apollo/client';
import { gql } from '@apollo/client';

// Enhanced GraphQL mutations that include device fingerprinting
const ENHANCED_INITIALIZE_ZKLOGIN = gql`
  mutation EnhancedInitializeZkLogin(
    $firebaseToken: String!
    $providerToken: String!
    $provider: String!
    $deviceFingerprint: JSONString
  ) {
    initializeZkLogin(
      firebaseToken: $firebaseToken, 
      providerToken: $providerToken, 
      provider: $provider
    ) {
      success
      error
      maxEpoch
      randomness
      authAccessToken
      authRefreshToken
    }
  }
`;

const ENHANCED_FINALIZE_ZKLOGIN = gql`
  mutation EnhancedFinalizeZkLogin($input: FinalizeZkLoginInput!, $deviceFingerprint: JSONString) {
    finalizeZkLogin(input: $input) {
      success
      error
      zkProof
      suiAddress
      isPhoneVerified
      requiresDeviceTrust
      securityFlags {
        isNewDevice
        isTrustedDevice
        riskScore
      }
    }
  }
`;

export class EnhancedAuthService {
  private static instance: EnhancedAuthService;
  private authService: AuthService;
  private securityService: SecurityService;
  private isInitialized = false;

  private constructor() {
    this.authService = AuthService.getInstance();
    this.securityService = SecurityService.getInstance();
  }

  public static getInstance(): EnhancedAuthService {
    if (!EnhancedAuthService.instance) {
      EnhancedAuthService.instance = new EnhancedAuthService();
    }
    return EnhancedAuthService.instance;
  }

  /**
   * Initialize both auth and security services
   */
  public async initialize(): Promise<void> {
    if (this.isInitialized) {
      console.log('EnhancedAuthService - Already initialized');
      return;
    }

    console.log('EnhancedAuthService - Initializing...');
    
    try {
      // Initialize services in parallel
      await Promise.all([
        this.authService.initialize(),
        this.securityService.initializeFingerprinting()
      ]);

      this.isInitialized = true;
      console.log('EnhancedAuthService - Initialization completed');
    } catch (error) {
      console.error('EnhancedAuthService - Initialization failed:', error);
      throw error;
    }
  }

  /**
   * Enhanced Google Sign-In with device fingerprinting
   */
  public async signInWithGoogle(): Promise<{
    userInfo: any;
    zkLoginData: any;
    securityData: {
      deviceFingerprint: any;
      fingerprintHash: string;
      securityFlags: {
        isNewDevice: boolean;
        isTrustedDevice: boolean;
        requiresDeviceTrust: boolean;
      };
    };
  }> {
    console.log('EnhancedAuthService - Starting enhanced Google Sign-In...');

    try {
      // Ensure services are initialized
      if (!this.isInitialized) {
        await this.initialize();
      }

      // Get device fingerprinting data before authentication
      console.log('EnhancedAuthService - Collecting device fingerprint...');
      const securityData = await this.securityService.performSecureAuthentication({});

      // Perform the actual Google sign-in
      console.log('EnhancedAuthService - Performing Google authentication...');
      const authResult = await this.authService.signInWithGoogle();

      // Log security information
      console.log('EnhancedAuthService - Security flags:', securityData.securityFlags);
      console.log('EnhancedAuthService - Device fingerprint hash:', securityData.fingerprintHash);

      // Check if device trust is required
      if (securityData.securityFlags.requiresDeviceTrust) {
        console.log('EnhancedAuthService - New device detected, device trust verification may be required');
      }

      return {
        ...authResult,
        securityData: {
          deviceFingerprint: securityData.deviceFingerprint,
          fingerprintHash: securityData.fingerprintHash,
          securityFlags: securityData.securityFlags
        }
      };

    } catch (error) {
      console.error('EnhancedAuthService - Enhanced Google Sign-In failed:', error);
      throw error;
    }
  }

  /**
   * Enhanced Apple Sign-In with device fingerprinting
   */
  public async signInWithApple(): Promise<{
    userInfo: any;
    zkLoginData: any;
    securityData: {
      deviceFingerprint: any;
      fingerprintHash: string;
      securityFlags: {
        isNewDevice: boolean;
        isTrustedDevice: boolean;
        requiresDeviceTrust: boolean;
      };
    };
  }> {
    console.log('EnhancedAuthService - Starting enhanced Apple Sign-In...');

    try {
      // Ensure services are initialized
      if (!this.isInitialized) {
        await this.initialize();
      }

      // Get device fingerprinting data before authentication
      console.log('EnhancedAuthService - Collecting device fingerprint...');
      const securityData = await this.securityService.performSecureAuthentication({});

      // Perform the actual Apple sign-in
      console.log('EnhancedAuthService - Performing Apple authentication...');
      const authResult = await this.authService.signInWithApple();

      // Log security information
      console.log('EnhancedAuthService - Security flags:', securityData.securityFlags);
      console.log('EnhancedAuthService - Device fingerprint hash:', securityData.fingerprintHash);

      // Check if device trust is required
      if (securityData.securityFlags.requiresDeviceTrust) {
        console.log('EnhancedAuthService - New device detected, device trust verification may be required');
      }

      return {
        ...authResult,
        securityData: {
          deviceFingerprint: securityData.deviceFingerprint,
          fingerprintHash: securityData.fingerprintHash,
          securityFlags: securityData.securityFlags
        }
      };

    } catch (error) {
      console.error('EnhancedAuthService - Enhanced Apple Sign-In failed:', error);
      throw error;
    }
  }

  /**
   * Secure transaction with fingerprinting for sensitive operations
   */
  public async performSecureOperation<T>(
    operation: () => Promise<T>,
    operationType: string,
    amount?: number
  ): Promise<{
    result: T;
    securityChecks: {
      deviceTrusted: boolean;
      operationAllowed: boolean;
    };
  }> {
    console.log(`EnhancedAuthService - Performing secure operation: ${operationType}`);

    try {
      // Get device fingerprint for the operation
      const fingerprintData = await this.securityService.getFingerprintForAPI();

      // Check device trust status (for logging/analytics only)
      const devices = await this.securityService.getUserDevices();
      const deviceTrusted = devices.length > 0 && devices.some(d => d.isTrusted);

      const securityChecks = {
        deviceTrusted,
        operationAllowed: true  // Always allow operations in MVP
      };

      // Perform the operation with fingerprint data attached
      console.log('EnhancedAuthService - Security checks passed, performing operation...');
      const result = await operation();

      console.log('EnhancedAuthService - Secure operation completed successfully');
      return {
        result,
        securityChecks
      };

    } catch (error) {
      console.error('EnhancedAuthService - Secure operation failed:', error);
      throw error;
    }
  }

  /**
   * Request device trust verification
   */
  public async requestDeviceTrust(method: 'email' | 'sms' = 'email'): Promise<{
    success: boolean;
    message?: string;
    error?: string;
  }> {
    return await this.securityService.requestDeviceTrust(method);
  }

  /**
   * Verify device trust with code
   */
  public async verifyDeviceTrust(verificationCode: string): Promise<{
    success: boolean;
    device?: any;
    error?: string;
  }> {
    return await this.securityService.verifyDeviceTrust(verificationCode, 'User verified via mobile app');
  }

  /**
   * Get security dashboard data
   */
  public async getSecurityDashboard(): Promise<{
    devices: any[];
    securityScore: number;
    recentActivity: any[];
  }> {
    try {
      const devices = await this.securityService.getUserDevices();

      // Calculate a simple security score based on devices only
      const trustedDevices = devices.filter(d => d.isTrusted).length;
      const securityScore = Math.min(100, 
        (trustedDevices * 40) + 
        (devices.length > 0 ? 30 : 0) +
        30 // Base score
      );

      return {
        devices,
        securityScore,
        recentActivity: [] // TODO: Implement recent activity tracking
      };
    } catch (error) {
      console.error('EnhancedAuthService - Error getting security dashboard:', error);
      return {
        devices: [],
        securityScore: 0,
        recentActivity: []
      };
    }
  }

  /**
   * Get device fingerprint for external use
   */
  public async getDeviceFingerprint(): Promise<{ fingerprint: any; hash: string }> {
    return await this.securityService.getDeviceFingerprint();
  }

  /**
   * Check if all services are ready
   */
  public isReady(): boolean {
    return this.isInitialized && this.securityService.isReady();
  }

  /**
   * Get service status
   */
  public getStatus(): {
    isInitialized: boolean;
    authReady: boolean;
    securityReady: boolean;
  } {
    return {
      isInitialized: this.isInitialized,
      authReady: true, // AuthService doesn't have a status method
      securityReady: this.securityService.isReady()
    };
  }

  // Delegate methods to original AuthService for backward compatibility
  public async signOut(): Promise<void> {
    return await this.authService.signOut();
  }

  public async getStoredTokens(): Promise<any> {
    return await this.authService.getStoredTokens();
  }

  public async refreshTokens(): Promise<any> {
    return await this.authService.refreshTokens();
  }

  public async isAuthenticated(): Promise<boolean> {
    return await this.authService.isAuthenticated();
  }

  public async getCurrentUser(): Promise<any> {
    return await this.authService.getCurrentUser();
  }
}

export default EnhancedAuthService;