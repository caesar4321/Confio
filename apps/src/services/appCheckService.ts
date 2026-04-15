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
import appCheck from '@react-native-firebase/app-check';
import {
    ALLOW_APP_CHECK_DEBUG,
    FIREBASE_APP_CHECK_DEBUG_TOKEN_ANDROID,
    FIREBASE_APP_CHECK_DEBUG_TOKEN_IOS,
} from '@env';


class AppCheckService {
    private isInitialized = false;
    private tokenPromise: Promise<string | null> | null = null;
    private lastToken: string | null = null;
    private lastTokenAt = 0;
    private lastFailureAt = 0;

    private static readonly TOKEN_REUSE_MS = 5 * 60 * 1000;
    private static readonly FAILURE_BACKOFF_MS = 30 * 1000;

    private isDebugAllowed(): boolean {
        return String(ALLOW_APP_CHECK_DEBUG).toLowerCase() === 'true';
    }

    private async shouldUseDebugProvider(): Promise<boolean> {
        if (!this.isDebugAllowed()) {
            return false;
        }

        return Platform.OS === 'android'
            ? Boolean(FIREBASE_APP_CHECK_DEBUG_TOKEN_ANDROID)
            : Boolean(FIREBASE_APP_CHECK_DEBUG_TOKEN_IOS);
    }

    /**
     * Initialize Firebase App Check
     * Should be called once at app startup
     */
    async initialize(): Promise<void> {
        if (this.isInitialized) return;

        try {
            // Use the new modular API for App Check initialization
            const rnfbProvider = appCheck().newReactNativeFirebaseAppCheckProvider();
            const useDebugProvider = await this.shouldUseDebugProvider();

            rnfbProvider.configure({
                android: {
                    provider: useDebugProvider ? 'debug' : 'playIntegrity',
                    debugToken: useDebugProvider ? FIREBASE_APP_CHECK_DEBUG_TOKEN_ANDROID : undefined,
                },
                apple: {
                    provider: useDebugProvider ? 'debug' : 'appAttest',
                    debugToken: useDebugProvider ? FIREBASE_APP_CHECK_DEBUG_TOKEN_IOS : undefined,
                },
            });

            await appCheck().initializeAppCheck({
                provider: rnfbProvider,
                isTokenAutoRefreshEnabled: true,
            });

            this.isInitialized = true;
        } catch (error: any) {
            // Don't throw - allow app to continue in monitoring mode
        }
    }

    /**
     * Get App Check token
     * Returns null if unavailable (which is logged but not blocked)
     */
    private async fetchToken(): Promise<string | null> {
        const startTime = Date.now();
        try {
            if (!this.isInitialized) {
                await this.initialize();
            }

            const { token } = await appCheck().getToken();
            if (token) {
                this.lastToken = token;
                this.lastTokenAt = Date.now();
            } return token;
        } catch (error: any) {

            this.lastFailureAt = Date.now(); return null;
        }
    }

    /**
     * Get token for API request headers
     * Can be used to add X-Firebase-AppCheck header to requests
     */
    async getTokenForHeader(): Promise<string | null> {
        const now = Date.now();

        if (this.lastToken && now - this.lastTokenAt < AppCheckService.TOKEN_REUSE_MS) {
            return this.lastToken;
        }

        if (this.lastFailureAt && now - this.lastFailureAt < AppCheckService.FAILURE_BACKOFF_MS) {
            return this.lastToken;
        }

        if (!this.tokenPromise) {
            this.tokenPromise = this.fetchToken().finally(() => {
                this.tokenPromise = null;
            });
        }

        return this.tokenPromise;
    }
}

export const appCheckService = new AppCheckService();
export default appCheckService;
