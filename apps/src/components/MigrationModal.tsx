import React, { useEffect, useRef, useState } from 'react';
import { View, Text, ActivityIndicator, StyleSheet, Modal, Alert, AppState } from 'react-native';
import { migrationService, DriveAuthorizationRequiredError } from '../services/migrationService';
import { oauthStorage } from '../services/oauthStorageService';
import { GOOGLE_CLIENT_IDS } from '../config/env';
import { AccountManager } from '../utils/accountManager';
import { apolloClient } from '../apollo/client';
import { useAuth } from '../contexts/AuthContext';


export const MigrationModal = () => {
    const [visible, setVisible] = useState(false);
    const [loading, setLoading] = useState(false);
    const [status, setStatus] = useState('Verificando estado de la billetera...');
    // The context's signOut, not authService's: only it flips isAuthenticated,
    // which is what takes this full-screen modal down.
    const { isAuthenticated, accountContextTick, signOut } = useAuth();
    const isAuthenticatedRef = useRef(isAuthenticated);
    isAuthenticatedRef.current = isAuthenticated;
    const isCheckingRef = useRef(false);
    const isMigratingRef = useRef(false);
    const failurePromptRef = useRef(false);
    // Bumped on every auth/account change and on unmount. Work started under
    // an older epoch belongs to an identity that is gone: it must not open
    // prompts, start migrations, or act on anyone's behalf.
    const authEpochRef = useRef(0);
    const mountedRef = useRef(true);

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
            authEpochRef.current += 1;
        };
    }, []);

    useEffect(() => {
        // Any auth or account change orphans prompts opened for the previous
        // identity: their buttons become no-ops, and the new identity gets its
        // own migration check.
        authEpochRef.current += 1;
        failurePromptRef.current = false;
        if (!isAuthenticated) {
            setVisible(false);
            setLoading(false);
            setStatus('Verificando estado de la billetera...');
            return;
        }

        void checkMigration();
    }, [isAuthenticated, accountContextTick]);

    useEffect(() => {
        const subscription = AppState.addEventListener('change', (nextState) => {
            if (nextState === 'active' && isAuthenticated) {
                void checkMigration();
            }
        });

        return () => subscription.remove();
    }, [isAuthenticated, accountContextTick]);

    const checkMigration = async () => {
        if (!mountedRef.current || !isAuthenticatedRef.current) {
            return;
        }
        if (isCheckingRef.current || isMigratingRef.current || failurePromptRef.current) {
            return;
        }

        const epoch = authEpochRef.current;
        isCheckingRef.current = true;
        try {
            // 1. (Removed) Preliminary Backend Status Check
            // We removed the UI-level backend check because it was preventing the "Zombie Type 2" fix.
            // migrationService.checkNeedsMigration() now handles both backend status AND 
            // the "Trust But Verify" on-chain validation internally.


            // 2. Get OAuth context
            const oauthData = await oauthStorage.getOAuthSubject();
            if (epoch !== authEpochRef.current) return;

            // SYSTEMIC FIX:
            // If we are NOT migrated (per backend or unknown), but we lack OAuth Subject,
            // we are in a broken state (App Update from V1 -> V2).
            // We MUST force re-login to get the 'sub' claim for V1 derivation.
            if (!oauthData || !oauthData.subject) {
                // Same lifecycle as the failure prompts: it owns the modal
                // until answered, and only its own identity may act on it.
                failurePromptRef.current = true;
                Alert.alert(
                    'Actualización de Seguridad',
                    'Para completar la actualización de tu billetera y asegurar tus fondos, necesitas iniciar sesión nuevamente.',
                    [
                        {
                            text: 'Iniciar Sesión',
                            onPress: async () => {
                                if (epoch !== authEpochRef.current) return;
                                failurePromptRef.current = false;
                                try {
                                    await signOut(); // Flips isAuthenticated; the auth flow takes over
                                } catch (e) {
                                }
                            }
                        }
                    ],
                    { cancelable: false }
                );
                return;
            }

            const provider = oauthData.provider;
            const sub = oauthData.subject;

            // ... (rest of logic)
            const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
            const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
            const aud = provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';

            // Check personal account (index 0)
            const migrationState = await migrationService.checkNeedsMigration(
                iss, sub, aud, provider, 0
            );
            if (epoch !== authEpochRef.current) return;

            if (migrationState.statusUnknown) {
                // The check could not complete, so we do not know whether this
                // user has V1 funds. Do NOT start a migration on an unverified
                // picture, and do not claim there is nothing to do either —
                // leave the modal closed and re-check on the next trigger.
                console.warn('[MigrationModal] Migration status unknown; skipping this check.');
                setVisible(false);
            } else if (migrationState.needsMigration) {
                setVisible(true);
                void performMigration(iss, sub, aud, provider, epoch);
            } else {
                setVisible(false);
            }
        } catch (error) {
        } finally {
            isCheckingRef.current = false;
            // An identity change while this check ran was turned away by the
            // busy flag; run the check it was denied.
            if (epoch !== authEpochRef.current) {
                void checkMigration();
            }
        }
    };

    const performMigration = async (iss: string, sub: string, aud: string, provider: 'google' | 'apple', epoch: number) => {
        if (isMigratingRef.current || epoch !== authEpochRef.current) {
            return;
        }

        isMigratingRef.current = true;
        setLoading(true);
        setStatus('Actualizando la seguridad de tu billetera...\nPor favor no cierres la aplicación.');

        let succeeded = false;
        let failure: unknown = null;
        try {
            succeeded = await migrationService.performMigration(
                iss, sub, aud, provider, 0
            );
            // A false return is a refusal (server rejected the group or the
            // address, or V1 still holds value). Retrying it on a timer never
            // converges — it used to loop every 3s behind a modal the user
            // could not leave.
        } catch (error) {
            failure = error;
        } finally {
            isMigratingRef.current = false;
            setLoading(false);
        }

        if (epoch !== authEpochRef.current) {
            // The identity changed mid-migration: this result is not theirs.
            // Hide the modal and run the check the busy flag turned away.
            setVisible(false);
            void checkMigration();
            return;
        }

        if (succeeded) {
            setStatus('¡Actualización completada!');

            // Trigger global refresh
            try {
                await apolloClient.reFetchObservableQueries();
                // Also clear any cached heavy data if needed
            } catch (e) {
            }

            // Hide only if this identity still owns the modal: a later one may
            // be mid-migration behind it by now.
            setTimeout(() => {
                if (epoch === authEpochRef.current) {
                    setVisible(false);
                }
            }, 1500);
            return;
        }
        showMigrationFailure(failure, iss, sub, aud, provider, epoch);
    };

    const showMigrationFailure = (
        error: unknown,
        iss: string,
        sub: string,
        aud: string,
        provider: 'google' | 'apple',
        epoch: number,
    ) => {
        // A prompt belongs to the identity that opened it. After a logout or
        // account switch its buttons must not act, least of all sign out or
        // retry on behalf of whoever is signed in now.
        const isCurrent = () => epoch === authEpochRef.current;
        if (!isCurrent()) return;

        // An open prompt owns the migration until the user answers it.
        // Otherwise returning to the app fires AppState's re-check, which
        // stacks a second prompt over the first.
        failurePromptRef.current = true;
        const retry = () => {
            if (!isCurrent()) return;
            failurePromptRef.current = false;
            void performMigration(iss, sub, aud, provider, epoch);
        };
        // This modal covers the whole app, so every failure needs a way out.
        const signOutButton = {
            text: 'Cerrar sesión',
            style: 'destructive' as const,
            onPress: () => {
                if (!isCurrent()) return;
                failurePromptRef.current = false;
                signOut().catch(() => {});
            },
        };

        if (error instanceof DriveAuthorizationRequiredError) {
            // The migration never prompts for Drive itself: a consent sheet can
            // outlive the session that opened it and leave its token cached for
            // whoever signs in next. Signing in again obtains a token bound to
            // this identity.
            Alert.alert(
                'Inicia sesión de nuevo',
                'Para actualizar tu billetera primero guardamos un respaldo en tu Google Drive. Cierra sesión y vuelve a entrar; cuando la app lo pida, acepta Google Drive. No movimos tus fondos.',
                [signOutButton],
                { cancelable: false },
            );
            return;
        }

        Alert.alert(
            'Actualización Fallida',
            'No pudimos completar la actualización de tu billetera. Inténtalo de nuevo. Si continúa, cierra sesión y vuelve a entrar, o contáctanos.',
            [signOutButton, { text: 'Reintentar', onPress: retry }],
            { cancelable: false },
        );
    };

    return (
        <Modal visible={visible} transparent={false} animationType="fade">
            <View style={styles.container}>
                <View style={styles.content}>
                    <ActivityIndicator size="large" color="#2563EB" />
                    <Text style={styles.title}>Actualizando Billetera</Text>
                    <Text style={styles.message}>{status}</Text>
                </View>
            </View>
        </Modal>
    );
};

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#fff',
        justifyContent: 'center',
        alignItems: 'center',
        padding: 20
    },
    content: {
        alignItems: 'center',
        gap: 20
    },
    title: {
        fontSize: 24,
        fontWeight: 'bold',
        marginTop: 20,
        color: '#1F2937'
    },
    message: {
        fontSize: 16,
        color: '#4B5563',
        textAlign: 'center',
        lineHeight: 24
    }
});
