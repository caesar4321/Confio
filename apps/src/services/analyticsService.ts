import analytics from '@react-native-firebase/analytics';

/**
 * Analytics Service Wrapper
 * Centralizes all telemetry calls to ensure consistency and type safety.
 * Currently uses Firebase Analytics.
 */

export const AnalyticsService = {
    /**
     * Log a custom event.
     * @param name Event name (e.g. 'backup_success')
     * @param params Optional parameters (e.g. { provider: 'google' })
     */
    logEvent: async (name: string, params?: { [key: string]: any }) => {
        try {
            if (__DEV__) {
                console.log(`[Analytics] logEvent: ${name}`, params || '');
            }
            await analytics().logEvent(name, params);
        } catch (error) {
            console.warn('[Analytics] Failed to log event:', error);
        }
    },

    /**
     * Set a user property for segmentation.
     * @param name Property name (e.g. 'has_cloud_backup')
     * @param value Property value (e.g. 'true')
     */
    setUserProperty: async (name: string, value: string) => {
        try {
            if (__DEV__) {
                console.log(`[Analytics] setUserProperty: ${name} = ${value}`);
            }
            await analytics().setUserProperty(name, value);
        } catch (error) {
            console.warn('[Analytics] Failed to set user property:', error);
        }
    },

    /**
     * Screen tracking (optional utility)
     */
    logScreenView: async (screenName: string, screenClass: string) => {
        try {
            await analytics().logScreenView({
                screen_name: screenName,
                screen_class: screenClass,
            });
        } catch (error) {
            console.warn('[Analytics] Failed to log screen view:', error);
        }
    },

    // --- Backup Events ---

    logBackupAttempt: async (provider: 'google_drive' | 'icloud') => {
        try {
            await analytics().logEvent('backup_attempt', {
                provider,
                timestamp: new Date().toISOString(),
            });
            if (__DEV__) console.log(`[Analytics] logBackupAttempt: ${provider}`);
        } catch (e) {
            console.warn('[Analytics] Failed to log backup_attempt', e);
        }
    },

    logBackupSuccess: async (provider: 'google_drive' | 'icloud', deviceName?: string) => {
        try {
            await analytics().logEvent('backup_success', {
                provider,
                device_name: deviceName || 'unknown',
                timestamp: new Date().toISOString(),
            });

            // Update User User Property
            await analytics().setUserProperty('has_cloud_backup', 'true');

            if (__DEV__) console.log(`[Analytics] logBackupSuccess: ${provider}`);
        } catch (e) {
            console.warn('[Analytics] Failed to log backup_success', e);
        }
    },

    logBackupFailed: async (provider: 'google_drive' | 'icloud', error: string) => {
        try {
            await analytics().logEvent('backup_failed', {
                provider,
                error_message: error.substring(0, 100), // Truncate for safety
                timestamp: new Date().toISOString(),
            });
            if (__DEV__) console.log(`[Analytics] logBackupFailed: ${provider}`, error);
        } catch (e) {
            console.warn('[Analytics] Failed to log backup_failed', e);
        }
    }
};
