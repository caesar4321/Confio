/**
 * Firebase App Check Service for Confío
 * 
 * Unified device/app integrity verification for both Android and iOS:
 * - Android: Uses Play Integrity provider
 * - iOS: Uses App Attest provider (with DeviceCheck fallback)
 * 
 * This replaces the previous playIntegrityService.ts with Firebase App Check
 * for cross-platform support.
 */

import { Platform } from 'react-native';
import appCheck, { firebase } from '@react-native-firebase/app-check';
import { apolloClient } from '../apollo/client';


class AppCheckService {
    private isInitialized = false;

    /**
     * Initialize Firebase App Check
     * Should be called once at app startup
     */
    async initialize(): Promise<void> {
        if (this.isInitialized) return;

        try {
            // Use the new modular API for App Check initialization
            const rnfbProvider = appCheck().newReactNativeFirebaseAppCheckProvider();

            rnfbProvider.configure({
                android: {
                    provider: __DEV__ ? 'debug' : 'playIntegrity',
                },
                apple: {
                    provider: __DEV__ ? 'debug' : 'appAttest',
                },
            });

            await appCheck().initializeAppCheck({
                provider: rnfbProvider,
                isTokenAutoRefreshEnabled: true,
            });

            this.isInitialized = true;
            console.log('[AppCheck] Initialized successfully on', Platform.OS, __DEV__ ? '(debug mode)' : '(production)');
        } catch (error: any) {
            console.warn('[AppCheck] Failed to initialize:', error?.message, error);
            // Don't throw - allow app to continue in monitoring mode
        }
    }

    /**
     * Get App Check token
     * Returns null if unavailable (which is logged but not blocked)
     */
    private async getToken(): Promise<string | null> {
        console.log('[AppCheck] getToken() called, isInitialized:', this.isInitialized);
        try {
            if (!this.isInitialized) {
                console.log('[AppCheck] Not initialized, calling initialize()...');
                await this.initialize();
            }

            // Force refresh to get a fresh token
            console.log('[AppCheck] Calling appCheck().getToken(true)...');
            const { token } = await appCheck().getToken(true);
            console.log('[AppCheck] Token received, length:', token?.length || 0);
            return token;
        } catch (error: any) {
            console.warn('[AppCheck] Failed to get token:', error?.message, error);
            return null;
        }
    }

    /**
     * Get token for API request headers
     * Can be used to add X-Firebase-AppCheck header to requests
     */
    async getTokenForHeader(): Promise<string | null> {
        return this.getToken();
    }
}

export const appCheckService = new AppCheckService();
export default appCheckService;
