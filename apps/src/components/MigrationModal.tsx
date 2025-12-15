import React, { useEffect, useState } from 'react';
import { View, Text, ActivityIndicator, StyleSheet, Modal, Alert } from 'react-native';
import { migrationService } from '../services/migrationService';
import authService from '../services/authService';
import { oauthStorage } from '../services/oauthStorageService';
import { GOOGLE_CLIENT_IDS } from '../config/env';
import { AccountManager } from '../utils/accountManager';
import { apolloClient } from '../apollo/client';
import { GET_MY_MIGRATION_STATUS } from '../apollo/queries';

export const MigrationModal = () => {
    const [visible, setVisible] = useState(false);
    const [loading, setLoading] = useState(false);
    const [status, setStatus] = useState('Verificando estado de la billetera...');

    useEffect(() => {
        checkMigration();
    }, []);

    const checkMigration = async () => {
        try {
            // 1. Check Backend Status Implementation FIRST
            // This avoids issues where local keychain is empty but backend knows we migrated
            try {
                const { data } = await apolloClient.query({
                    query: GET_MY_MIGRATION_STATUS,
                    fetchPolicy: 'network-only'
                });

                const myAccount = data?.userAccounts?.find((a: any) =>
                    a.accountType?.toLowerCase() === 'personal' && String(a.accountIndex) === '0'
                );

                if (myAccount?.isKeylessMigrated) {
                    console.log('[MigrationModal] Backend says already migrated ✅');
                    return; // Stop here, no need to migrate
                }
            } catch (e) {
                console.warn('[MigrationModal] Backend status check failed, proceeding to local check:', e);
            }

            // 2. Get OAuth context
            const oauthData = await oauthStorage.getOAuthSubject();

            // SYSTEMIC FIX:
            // If we are NOT migrated (per backend or unknown), but we lack OAuth Subject,
            // we are in a broken state (App Update from V1 -> V2).
            // We MUST force re-login to get the 'sub' claim for V1 derivation.
            if (!oauthData || !oauthData.subject) {
                console.log('[MigrationModal] ⚠️ Critical: Authenticated but missing OAuth Subject. Forcing re-login.');

                Alert.alert(
                    'Actualización de Seguridad',
                    'Para completar la actualización de tu billetera y asegurar tus fondos, necesitas iniciar sesión nuevamente.',
                    [
                        {
                            text: 'Iniciar Sesión',
                            onPress: async () => {
                                try {
                                    await authService.signOut(); // SignOut
                                    // The auth state listener in App.tsx will handle navigation to Auth flow
                                } catch (e) {
                                    console.error('Logout failed', e);
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

            if (migrationState.needsMigration) {
                setVisible(true);
                performMigration(iss, sub, aud, provider);
            }
        } catch (error) {
            console.error('Migration check failed:', error);
        }
    };

    const performMigration = async (iss: string, sub: string, aud: string, provider: 'google' | 'apple') => {
        setLoading(true);
        setStatus('Actualizando la seguridad de tu billetera...\nPor favor no cierres la aplicación.');

        try {
            const success = await migrationService.performMigration(
                iss, sub, aud, provider, 0
            );

            if (success) {
                setStatus('¡Actualización completada!');

                // Trigger global refresh
                try {
                    await apolloClient.reFetchObservableQueries();
                    // Also clear any cached heavy data if needed   
                } catch (e) {
                    console.warn('Refetch failed', e);
                }

                setTimeout(() => {
                    setVisible(false);
                }, 1500);
            } else {
                setStatus('Actualización fallida. Reintentando...');
                setTimeout(() => performMigration(iss, sub, aud, provider), 3000);
            }
        } catch (error) {
            console.error('Migration failed:', error);
            Alert.alert(
                'Actualización Fallida',
                'No pudimos actualizar tu billetera. Por favor verifica tu conexión a internet e inténtalo de nuevo.',
                [{ text: 'Reintentar', onPress: () => performMigration(iss, sub, aud, provider) }]
            );
        }
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
