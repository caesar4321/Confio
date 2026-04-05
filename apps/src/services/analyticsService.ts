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
            if (__DEV__) {            }
            await analytics().logEvent(name, params);
        } catch (error) {
        }
    },

    /**
     * Set a user property for segmentation.
     * @param name Property name (e.g. 'has_cloud_backup')
     * @param value Property value (e.g. 'true')
     */
    setUserProperty: async (name: string, value: string) => {
        try {
            if (__DEV__) {            }
            await analytics().setUserProperty(name, value);
        } catch (error) {
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
        }
    },

    // --- Backup Events ---

    logBackupAttempt: async (provider: 'google_drive' | 'icloud') => {
        try {
            await analytics().logEvent('backup_attempt', {
                provider,
                timestamp: new Date().toISOString(),
            });
        } catch (e) {
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

        } catch (e) {
        }
    },

    logBackupFailed: async (provider: 'google_drive' | 'icloud', error: string) => {
        try {
            await analytics().logEvent('backup_failed', {
                provider,
                error_message: error.substring(0, 100), // Truncate for safety
                timestamp: new Date().toISOString(),
            });
        } catch (e) {
        }
    }
};
