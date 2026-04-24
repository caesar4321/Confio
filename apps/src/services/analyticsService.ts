import analytics from '@react-native-firebase/analytics';
import { Platform } from 'react-native';
import { apolloClient } from '../apollo/client';
import { TRACK_FUNNEL_EVENT } from '../apollo/mutations';

/**
 * Analytics Service Wrapper
 * Centralizes all telemetry calls to ensure consistency and type safety.
 * Dual-emits to Firebase Analytics (client-side funnels) AND Confío's own
 * FunnelEvent table (server-joinable analysis across web, server, chain).
 */

// Events that are safe to emit from the client. Must match the server
// whitelist in users/funnel_schema.py (CLIENT_EMITTABLE_EVENTS).
export type ClientFunnelEvent =
    | 'whatsapp_share_tapped'
    | 'referral_whatsapp_share_tapped'
    | 'invite_share_dismissed'
    | 'claim_entry_viewed'
    | 'signup_completed';

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
    },

    // --- Funnel Events (Invitar y Enviar + referral loop) ---
    //
    // Dual-emits to Firebase (for client-side funnel exploration) and to
    // Confío's own FunnelEvent table via GraphQL (for server-joinable,
    // LATAM-sovereign analysis in Postgres).
    //
    // Fire-and-forget. Both emits are independently try/catch'd; one failing
    // doesn't block the other. NEVER await this from a financial path —
    // treat it as void.
    logFunnelEvent: async (
        eventName: ClientFunnelEvent,
        params?: { [key: string]: any },
        options?: { sourceType?: string; channel?: string },
    ) => {
        // Firebase side
        try {
            await analytics().logEvent(eventName, {
                ...(params || {}),
                platform: Platform.OS,
            });
        } catch (_e) {
            // swallow
        }

        // Confío DB side
        try {
            await apolloClient.mutate({
                mutation: TRACK_FUNNEL_EVENT,
                variables: {
                    eventName,
                    platform: Platform.OS,
                    sourceType: options?.sourceType,
                    channel: options?.channel,
                    properties: params ? JSON.stringify(params) : undefined,
                },
                // We don't care about the result and we don't want this to
                // retry or block the UI thread.
                fetchPolicy: 'no-cache',
            });
        } catch (_e) {
            // swallow
        }
    },
};
