import React, { useState, useCallback, useRef } from 'react';
import { Platform, Alert, ActivityIndicator, Modal, StyleSheet, Text, View } from 'react-native';
import { useAuth } from '../contexts/AuthContext';
import { AuthService } from '../services/authService';
import { useQuery } from '@apollo/client';
import { GET_MY_BALANCES } from '../apollo/queries';
import { BackupConsentModal } from '../components/BackupConsentModal';
import { ExistingBackupModal } from '../components/ExistingBackupModal';
import { AnalyticsService } from '../services/analyticsService';
import { migrationService } from '../services/migrationService';
import { oauthStorage } from '../services/oauthStorageService';
import authService from '../services/authService';
import { GOOGLE_CLIENT_IDS } from '../config/env';

type EnforcementAction = 'presale' | 'transaction' | 'app_launch' | 'deposit';

let activeMigrationPromise: Promise<boolean> | null = null;

export const useBackupEnforcement = () => {
    const { userProfile, refreshProfile } = useAuth();
    const [modalVisible, setModalVisible] = useState(false);
    const [, setStrictMode] = useState(false);
    const [migrationVisible, setMigrationVisible] = useState(false);
    const [migrationStatus, setMigrationStatus] = useState('Verificando estado de la billetera...');

    // State for existing backup handling
    const [existingBackupModalVisible, setExistingBackupModalVisible] = useState(false);
    const [backupEntries, setBackupEntries] = useState<any[]>([]);
    const [hasLegacyBackup, setHasLegacyBackup] = useState(false);

    const resolveRef = useRef<((value: boolean) => void) | null>(null);

    // Fetch balance fallback (for simple cases if needed, though we rely on passed balance for app_launch)
    const { data: myBalancesData } = useQuery(GET_MY_BALANCES, {
        fetchPolicy: 'cache-first',
    });

    const ensureV2Migration = useCallback(async (): Promise<boolean> => {
        if (activeMigrationPromise) {
            return activeMigrationPromise;
        }

        activeMigrationPromise = (async () => {
            try {
                const oauthData = await oauthStorage.getOAuthSubject();

                if (!oauthData?.subject || !oauthData?.provider) {
                    Alert.alert(
                        'Actualización de Seguridad',
                        'Para completar la actualización de tu billetera y asegurar tus fondos, necesitas iniciar sesión nuevamente.',
                        [
                            {
                                text: 'Iniciar Sesión',
                                onPress: async () => {
                                    try {
                                        await authService.signOut();
                                    } catch (error) {
                                        console.error('Migration enforcement sign-out error:', error);
                                    }
                                }
                            }
                        ],
                        { cancelable: false }
                    );
                    return false;
                }

                const provider = oauthData.provider;
                const sub = oauthData.subject;
                const googleClientIds = GOOGLE_CLIENT_IDS[__DEV__ ? 'development' : 'production'];
                const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
                const aud = provider === 'google' ? googleClientIds.web : 'com.confio.app';

                setMigrationStatus('Verificando estado de la billetera...');
                const migrationState = await migrationService.checkNeedsMigration(
                    iss,
                    sub,
                    aud,
                    provider,
                    0
                );

                if (!migrationState.needsMigration) {
                    return true;
                }

                setMigrationVisible(true);
                setMigrationStatus('Actualizando la seguridad de tu billetera...\nPor favor no cierres la aplicación.');

                const success = await migrationService.performMigration(
                    iss,
                    sub,
                    aud,
                    provider,
                    0
                );

                if (!success) {
                    Alert.alert(
                        'Actualización requerida',
                        'No pudimos completar la migración de tu billetera. Intenta nuevamente con conexión estable antes de continuar.'
                    );
                    return false;
                }

                setMigrationStatus('¡Actualización completada!');
                return true;
            } catch (error) {
                console.error('Migration enforcement error:', error);
                Alert.alert(
                    'Actualización requerida',
                    'No pudimos verificar o completar la migración de tu billetera. Intenta nuevamente antes de continuar.'
                );
                return false;
            } finally {
                setTimeout(() => {
                    setMigrationVisible(false);
                    setMigrationStatus('Verificando estado de la billetera...');
                }, 400);
                activeMigrationPromise = null;
            }
        })();

        return activeMigrationPromise;
    }, []);

    const checkBackupEnforcement = useCallback(async (action: EnforcementAction, totalBalanceUSD?: number): Promise<boolean> => {
        const migrationReady = await ensureV2Migration();
        if (!migrationReady) return false;

        // 1. iOS Check - Implicitly backed up via iCloud
        if (Platform.OS === 'ios') return true;

        // 2. Check if backup is already enabled in profile (fast check)
        const backupProvider = (userProfile as any)?.backupProvider?.toLowerCase();
        if (backupProvider === 'google_drive' || backupProvider === 'icloud') return true;

        // 3. Removed local check to strictly enforce backend status
        // const isDriveEnabled = await AuthService.getInstance().checkDriveBackupEnabled();
        // if (isDriveEnabled) return true;

        // 4. Check Balance Threshold for App Launch
        // "1) 잔액 기준 모달 팝업 ($50 초과시 앱 킬때마다 팝업)"
        if (action === 'app_launch') {
            // Use provided balance if available, otherwise fallback to simple calc
            let checkBalance = 0;
            if (typeof totalBalanceUSD === 'number') {
                checkBalance = totalBalanceUSD;
            } else {
                // Fallback: simple CUSD + USDC from internal query (ignores CONFIO price complexity)
                const cusd = parseFloat(myBalancesData?.myBalances?.cusd || '0');
                const usdc = parseFloat(myBalancesData?.myBalances?.usdc || '0');
                checkBalance = cusd + usdc;
            }

            // If balance is low, we don't annoy them on launch
            if (checkBalance <= 50) return true;
        }

        // If we get here, enforcement is needed.
        // Configure strictness based on action
        // Presale: Block participation ("참여를 못 하도록")
        // Deposit: Block viewing the deposit address
        // Transaction: "매번 송금/페이 시" (Prompt every time)
        // App Launch: "앱 킬때마다 팝업" (Prompt)

        setStrictMode(action === 'presale' || action === 'deposit');
        setModalVisible(true);

        // Return a promise that resolves when user makes a choice
        return new Promise<boolean>((resolve) => {
            resolveRef.current = resolve;
        });
    }, [ensureV2Migration, userProfile, myBalancesData]);

    const handleContinue = async () => {
        // We close the modal to allow native Google Sign In UI to show
        setModalVisible(false);

        try {
            AnalyticsService.logBackupAttempt('google_drive');
            const result = await AuthService.getInstance().enableDriveBackup();

            if (result.success) {
                Alert.alert('Respaldo Activado', 'Tu copia de seguridad está lista.');
                await refreshProfile();
                resolveRef.current?.(true);
            } else if (result.existingBackups) {
                // Conflict found: Show Custom Modal
                // Set data for modal
                const entries = result.existingBackups.entriesToShow || result.existingBackups.entries || [];
                // Sort by lastBackupAt desc (newest first)
                entries.sort((a: any, b: any) => {
                    const timeA = a.lastBackupAt ? new Date(a.lastBackupAt).getTime() : 0;
                    const timeB = b.lastBackupAt ? new Date(b.lastBackupAt).getTime() : 0;
                    return timeB - timeA;
                });

                setBackupEntries(entries);
                setHasLegacyBackup(result.existingBackups.hasLegacy || false);
                setExistingBackupModalVisible(true);

                // We keep modalVisible(false) for Consent, but open ExistingBackupModal
                // We do NOT resolve yet. The second modal handles it.
            } else {
                // If strict (Presale), we must fail.
                resolveRef.current?.(false);
            }
        } catch (error) {
            console.error('Backup enforcement error:', error);
            resolveRef.current?.(false);
        }
    };

    const handleRestore = async (entry: any | null) => {
        setExistingBackupModalVisible(false);
        try {
            // Restore from specific entry (or legacy if id is null/undefined)
            const entryId = entry?.id;

            const restoreRes = await AuthService.getInstance().restoreFromDriveBackup(entryId);
            if (restoreRes.success) {
                Alert.alert('Restauración Exitosa', 'Tu billetera ha sido restaurada correctamente.');
                await refreshProfile();
                resolveRef.current?.(true);
            } else {
                Alert.alert('Error', restoreRes.error || 'Falló la restauración.');
                resolveRef.current?.(false);
            }
        } catch (e) {
            console.error('Restore flow failed:', e);
            resolveRef.current?.(false);
        }
    };

    const handleUseCurrentWallet = async () => {
        setExistingBackupModalVisible(false);
        try {
            const forceRes = await AuthService.getInstance().enableDriveBackup(true);
            if (forceRes.success) {
                Alert.alert('Respaldo Activado', 'Tu copia de seguridad actual está lista.');
                await refreshProfile();
                resolveRef.current?.(true);
            } else {
                Alert.alert('Error', forceRes.error || 'No se pudo crear el respaldo.');
                resolveRef.current?.(false);
            }
        } catch (e) {
            console.error('Force backup failed:', e);
            resolveRef.current?.(false);
        }
    };

    const BackupEnforcementModal = () => (
        <>
            <Modal visible={migrationVisible} transparent={false} animationType="fade">
                <View style={styles.migrationContainer}>
                    <View style={styles.migrationContent}>
                        <ActivityIndicator size="large" color="#2563EB" />
                        <Text style={styles.migrationTitle}>Actualizando Billetera</Text>
                        <Text style={styles.migrationMessage}>{migrationStatus}</Text>
                    </View>
                </View>
            </Modal>
            <BackupConsentModal
                visible={modalVisible}
                onContinue={handleContinue}
                onCancel={() => { }}
            />
            <ExistingBackupModal
                visible={existingBackupModalVisible}
                entries={backupEntries}
                hasLegacy={hasLegacyBackup}
                onRestore={handleRestore}
                onUseCurrentWallet={handleUseCurrentWallet}
                onCancel={() => { }}
            />
        </>
    );

    return {
        checkBackupEnforcement,
        BackupEnforcementModal
    };
};

const styles = StyleSheet.create({
    migrationContainer: {
        flex: 1,
        backgroundColor: '#fff',
        justifyContent: 'center',
        alignItems: 'center',
        padding: 24,
    },
    migrationContent: {
        alignItems: 'center',
        gap: 20,
    },
    migrationTitle: {
        fontSize: 24,
        fontWeight: '700',
        color: '#1F2937',
        textAlign: 'center',
    },
    migrationMessage: {
        fontSize: 16,
        lineHeight: 24,
        color: '#4B5563',
        textAlign: 'center',
    },
});
