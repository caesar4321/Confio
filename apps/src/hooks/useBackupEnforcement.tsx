import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Platform, Alert, ActivityIndicator, Modal, StyleSheet, Text, View } from 'react-native';
import { useAuth } from '../contexts/AuthContext';
import { AuthService } from '../services/authService';
import { gql, useApolloClient, useQuery } from '@apollo/client';
import { GET_MY_BALANCES, GET_MY_MIGRATION_STATUS } from '../apollo/queries';
import { BackupConsentModal } from '../components/BackupConsentModal';
import { DriveStorageFullModal } from '../components/DriveStorageFullModal';
import { AnalyticsService } from '../services/analyticsService';
import { migrationService } from '../services/migrationService';
import { oauthStorage } from '../services/oauthStorageService';
import authService from '../services/authService';
import { GOOGLE_CLIENT_IDS } from '../config/env';

type EnforcementAction = 'presale' | 'transaction' | 'app_launch' | 'deposit' | 'bsc_deposit';

// This existing field resolves the JWT's active account, including business
// address permissions. myWalletAnchors resolves personal/0 only.
const GET_INBOUND_BSC_ADDRESS = gql`
    query GetInboundBscAddress {
        stockWalletAddress
    }
`;

let activeMigrationPromise: Promise<boolean> | null = null;

const WALLET_MISMATCH_TITLE = 'Billetera no sincronizada';
const WALLET_MISMATCH_MESSAGE =
    'Por seguridad, no podemos recibir fondos ni continuar esta operación porque la billetera de este dispositivo no coincide con la billetera registrada en tu cuenta. Cierra sesión e inicia sesión nuevamente con la misma cuenta donde guardaste tu respaldo. Si el problema continúa, contáctanos para ayudarte.';

export const useBackupEnforcement = () => {
    const { userProfile, refreshProfile } = useAuth();
    const apolloClient = useApolloClient();
    const [modalVisible, setModalVisible] = useState(false);
    const [storageFullVisible, setStorageFullVisible] = useState(false);
    const [, setStrictMode] = useState(false);
    const [migrationVisible, setMigrationVisible] = useState(false);
    const [migrationStatus, setMigrationStatus] = useState('Verificando estado de la billetera...');

    const resolveRef = useRef<((value: boolean) => void) | null>(null);
    const mountedRef = useRef(true);
    useEffect(() => {
        mountedRef.current = true;
        return () => { mountedRef.current = false; };
    }, []);

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

                if (migrationState.statusUnknown) {
                    // Unknown is not "clear to proceed". Reporting readiness
                    // here let a funded V1 user through whenever the pepper
                    // service or algod was briefly unreachable.
                    //
                    // Say so, though: failing closed in silence just makes the
                    // user's deposit or purchase die with no explanation and
                    // nothing to act on. This is a transient outage, so the
                    // honest message is "try again", not "something is wrong
                    // with your wallet".
                    console.warn('[BackupEnforcement] Migration status unknown; not reporting readiness.');
                    setMigrationVisible(false);
                    Alert.alert(
                        'No pudimos verificar tu billetera',
                        'No pudimos comprobar el estado de tu billetera en este momento. Revisa tu conexión e inténtalo de nuevo en unos segundos.',
                        [{ text: 'Entendido' }]
                    );
                    return false;
                }

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

    const verifyInboundSigningWallet = useCallback(async (action: EnforcementAction): Promise<boolean> => {
        if (action !== 'deposit' && action !== 'bsc_deposit' && action !== 'presale') {
            return true;
        }

        try {
            const activeContext = await authService.getActiveAccountContext();
            if (action === 'bsc_deposit') {
                const identity = await oauthStorage.getOAuthSubject();
                if (!mountedRef.current) return false;
                if (!identity?.subject || !identity?.provider) {
                    throw new Error('Signing identity unavailable');
                }
                const { getActiveEvmWallet } = await import('../services/secureDeterministicWallet');
                // Derive from the recovered secret, never from a display cache.
                // This refuses to generate a replacement secret when one is absent.
                const localWallet = await getActiveEvmWallet(activeContext);
                const { data } = await apolloClient.query({
                    query: GET_INBOUND_BSC_ADDRESS,
                    fetchPolicy: 'no-cache',
                    errorPolicy: 'none',
                    context: { fetchOptions: { cache: 'no-store' } as any },
                });
                const currentContext = await authService.getActiveAccountContext();
                const currentIdentity = await oauthStorage.getOAuthSubject();
                // A delayed response may outlive sign-out or this screen. Two
                // different users can both have the same personal/0 context.
                if (!mountedRef.current) return false;
                if (currentIdentity?.subject !== identity.subject
                    || currentIdentity?.provider !== identity.provider) {
                    throw new Error('Signed-in identity changed during deposit verification');
                }
                if (currentContext.type !== activeContext.type
                    || currentContext.index !== activeContext.index
                    || String(currentContext.businessId || '') !== String(activeContext.businessId || '')) {
                    throw new Error('Active account changed during deposit verification');
                }
                const serverAddress = data?.stockWalletAddress;
                if (typeof serverAddress !== 'string'
                    || !/^0x[0-9a-fA-F]{40}$/.test(serverAddress)
                    || /^0x0{40}$/i.test(serverAddress)) {
                    throw new Error('Registered BSC wallet unavailable');
                }
                if (localWallet.address.toLowerCase() !== serverAddress.toLowerCase()) {
                    Alert.alert(WALLET_MISMATCH_TITLE, WALLET_MISMATCH_MESSAGE);
                    return false;
                }
                return true;
            }
            const { data } = await apolloClient.query({
                query: GET_MY_MIGRATION_STATUS,
                fetchPolicy: 'no-cache',
                errorPolicy: 'all',
                context: { fetchOptions: { cache: 'no-store' } as any, skipProactiveRefresh: true },
            });

            const accounts = data?.userAccounts || [];
            const serverAccount = accounts.find((account: any) => {
                const accountType = String(account?.accountType || '').toLowerCase();
                const accountIndex = Number(account?.accountIndex || 0);
                if (accountType !== activeContext.type || accountIndex !== activeContext.index) {
                    return false;
                }
                if (activeContext.type === 'business' && activeContext.businessId) {
                    return String(account?.business?.id || '') === String(activeContext.businessId);
                }
                return true;
            });

            const serverAddress = serverAccount?.algorandAddress || null;
            if (!serverAddress) {
                // Algorand deprecated: new accounts are BSC-only and never get
                // an Algorand address, so re-login would not fix this.
                Alert.alert(
                    'Depósito no disponible',
                    'Esta cuenta no usa la red anterior (Algorand), así que esta vía de depósito no está disponible. Usa las opciones de depósito principales de la app.'
                );
                return false;
            }

            const oauthData = await oauthStorage.getOAuthSubject();
            if (!oauthData?.subject || !oauthData?.provider) {
                Alert.alert(
                    'Billetera no verificada',
                    'Para proteger tus fondos, inicia sesión nuevamente antes de recibir dinero.'
                );
                return false;
            }

            const provider = oauthData.provider;
            const googleClientIds = GOOGLE_CLIENT_IDS[__DEV__ ? 'development' : 'production'];
            const iss = provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
            const aud = provider === 'google' ? googleClientIds.web : 'com.confio.app';
            const { secureDeterministicWallet } = await import('../services/secureDeterministicWallet');
            const localWallet = await secureDeterministicWallet.createOrRestoreWallet(
                iss,
                oauthData.subject,
                aud,
                provider,
                activeContext.type,
                activeContext.index,
                activeContext.businessId
            );

            if (localWallet.address === serverAddress) {
                return true;
            }

            console.warn('[BackupEnforcement] Blocking inbound funds due to wallet mismatch', {
                action,
                accountType: activeContext.type,
                accountIndex: activeContext.index,
                businessId: activeContext.businessId,
                serverAddress,
                localSigningAddress: localWallet.address,
            });

            Alert.alert(
                WALLET_MISMATCH_TITLE,
                WALLET_MISMATCH_MESSAGE
            );
            return false;
        } catch (error) {
            if (action === 'bsc_deposit' && !mountedRef.current) return false;
            console.error('Inbound wallet verification error:', error);
            Alert.alert(
                'No pudimos verificar tu billetera',
                'Para proteger tus fondos, intenta de nuevo antes de recibir dinero.'
            );
            return false;
        }
    }, [apolloClient]);

    const checkBackupEnforcement = useCallback(async (action: EnforcementAction, totalBalanceUSD?: number): Promise<boolean> => {
        // BSC recovery already establishes its signing secret. Retired Algorand
        // registrations and legacy chain outages must not gate BSC deposits.
        if (action !== 'bsc_deposit') {
            const migrationReady = await ensureV2Migration();
            if (!migrationReady) return false;
        }

        // 1. iOS Check - Implicitly backed up via iCloud
        if (Platform.OS === 'ios') return verifyInboundSigningWallet(action);

        // 2. Check if backup is already enabled in profile (fast check)
        const backupProvider = (userProfile as any)?.backupProvider?.toLowerCase();
        if (backupProvider === 'google_drive' || backupProvider === 'icloud') {
            return verifyInboundSigningWallet(action);
        }

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

        setStrictMode(action === 'presale' || action === 'deposit' || action === 'bsc_deposit');
        setModalVisible(true);

        // Return a promise that resolves when user makes a choice
        return new Promise<boolean>((resolve) => {
            resolveRef.current = async (allowed) => {
                if (!allowed) {
                    resolve(false);
                    return;
                }
                resolve(await verifyInboundSigningWallet(action));
            };
        });
    }, [ensureV2Migration, userProfile, myBalancesData, verifyInboundSigningWallet]);

    const attemptDriveBackup = async () => {
        try {
            AnalyticsService.logBackupAttempt('google_drive');
            const result = await AuthService.getInstance().enableDriveBackup();

            if (result.success) {
                Alert.alert('Respaldo Activado', 'Tu copia de seguridad está lista.');
                await refreshProfile();
                resolveRef.current?.(true);
            } else if (result.storageFull) {
                // Only the user can free Google storage. Keep the gated action
                // pending until they retry or dismiss the how-to prompt.
                setStorageFullVisible(true);
            } else {
                // If strict (Presale), we must fail.
                resolveRef.current?.(false);
            }
        } catch (error) {
            console.error('Backup enforcement error:', error);
            resolveRef.current?.(false);
        }
    };

    const handleContinue = async () => {
        // We close the modal to allow native Google Sign In UI to show
        setModalVisible(false);
        await attemptDriveBackup();
    };

    const handleStorageFullRetry = () => {
        setStorageFullVisible(false);
        attemptDriveBackup();
    };

    const handleStorageFullClose = () => {
        setStorageFullVisible(false);
        resolveRef.current?.(false);
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
            <DriveStorageFullModal
                visible={storageFullVisible}
                onRetry={handleStorageFullRetry}
                onClose={handleStorageFullClose}
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
