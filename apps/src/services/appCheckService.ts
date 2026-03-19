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
import DeviceInfo from 'react-native-device-info';
import {
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

    private async shouldUseDebugProvider(): Promise<boolean> {
        if (Platform.OS === 'ios') {
            return Boolean(FIREBASE_APP_CHECK_DEBUG_TOKEN_IOS);
        }

        if (Platform.OS === 'android') {
            if (!FIREBASE_APP_CHECK_DEBUG_TOKEN_ANDROID) {
                return false;
            }

            try {
                const installer = await DeviceInfo.getInstallerPackageName();
                console.log('[AppCheck] Android installer package:', installer || 'none');
                return installer !== 'com.android.vending';
            } catch (error: any) {
                console.warn('[AppCheck] Failed to read Android installer package:', error?.message, error);
                return true;
            }
        }

        return false;
    }

    /**
     * Initialize Firebase App Check
     * Should be called once at app startup
     */
    async initialize(): Promise<void> {
        if (this.isInitialized) return;

        try {
            const initStart = Date.now();
            // Use the new modular API for App Check initialization
            const rnfbProvider = appCheck().newReactNativeFirebaseAppCheckProvider();
            const configuredDebugToken =
                Platform.OS === 'android'
                    ? FIREBASE_APP_CHECK_DEBUG_TOKEN_ANDROID
                    : FIREBASE_APP_CHECK_DEBUG_TOKEN_IOS;
            const useDebugProvider = await this.shouldUseDebugProvider();

            if (__DEV__ || useDebugProvider) {
                console.log(
                    '[AppCheck] Configuring debug token suffix:',
                    configuredDebugToken ? configuredDebugToken.slice(-6) : 'missing',
                );
            }

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
            console.log(
                '[AppCheck] Initialized successfully on',
                Platform.OS,
                useDebugProvider ? '(debug token mode)' : '(production attestation mode)',
            );
            console.log(`[PERF][AppCheck] initialize total: ${Date.now() - initStart}ms`);
        } catch (error: any) {
            console.warn('[AppCheck] Failed to initialize:', error?.message, error);
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
            }
            console.log(`[PERF][AppCheck] fetchToken total: ${Date.now() - startTime}ms`, {
                hasToken: !!token,
            });
            return token;
        } catch (error: any) {
            console.warn('[AppCheck] Failed to get token:', error?.message, error);
            this.lastFailureAt = Date.now();
            console.log(`[PERF][AppCheck] fetchToken failed after: ${Date.now() - startTime}ms`);
            return null;
        }
    }

    /**
     * Get token for API request headers
     * Can be used to add X-Firebase-AppCheck header to requests
     */
    async getTokenForHeader(): Promise<string | null> {
        const now = Date.now();

        if (this.lastToken && now - this.lastTokenAt < AppCheckService.TOKEN_REUSE_MS) {
            console.log(`[PERF][AppCheck] getTokenForHeader cache hit: 0ms`, {
                tokenAgeMs: now - this.lastTokenAt,
            });
            return this.lastToken;
        }

        if (this.lastFailureAt && now - this.lastFailureAt < AppCheckService.FAILURE_BACKOFF_MS) {
            console.log(`[PERF][AppCheck] getTokenForHeader backoff hit: 0ms`, {
                failureAgeMs: now - this.lastFailureAt,
                hasCachedToken: !!this.lastToken,
            });
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
