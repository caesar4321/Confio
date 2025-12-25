import React, { useState, useCallback, useRef } from 'react';
import { Platform, Alert } from 'react-native';
import { useAuth } from '../contexts/AuthContext';
import { AuthService } from '../services/authService';
import { useQuery } from '@apollo/client';
import { GET_MY_BALANCES } from '../apollo/queries';
import { BackupConsentModal } from '../components/BackupConsentModal';
import { ExistingBackupModal } from '../components/ExistingBackupModal';
import { AnalyticsService } from '../services/analyticsService';

type EnforcementAction = 'presale' | 'transaction' | 'app_launch';

export const useBackupEnforcement = () => {
    const { userProfile, refreshProfile } = useAuth();
    const [modalVisible, setModalVisible] = useState(false);
    const [strictMode, setStrictMode] = useState(false);

    // State for existing backup handling
    const [existingBackupModalVisible, setExistingBackupModalVisible] = useState(false);
    const [backupEntries, setBackupEntries] = useState<any[]>([]);
    const [hasLegacyBackup, setHasLegacyBackup] = useState(false);

    const resolveRef = useRef<((value: boolean) => void) | null>(null);

    // Fetch balance fallback (for simple cases if needed, though we rely on passed balance for app_launch)
    const { data: myBalancesData } = useQuery(GET_MY_BALANCES, {
        fetchPolicy: 'cache-first',
    });

    const checkBackupEnforcement = useCallback(async (action: EnforcementAction, totalBalanceUSD?: number): Promise<boolean> => {
        // 1. iOS Check - Implicitly backed up via iCloud
        if (Platform.OS === 'ios') return true;

        // 2. Check if backup is already enabled in profile (fast check)
        const backupProvider = (userProfile as any)?.backupProvider?.toLowerCase();
        if (backupProvider === 'google_drive') return true;

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

            console.log('checkBackupEnforcement: Action app_launch. Check Balance:', checkBalance);

            // If balance is low, we don't annoy them on launch
            if (checkBalance <= 50) return true;
        }

        // If we get here, enforcement is needed.
        // Configure strictness based on action
        // Presale: Block participation ("참여를 못 하도록")
        // Transaction: "매번 송금/페이 시" (Prompt every time)
        // App Launch: "앱 킬때마다 팝업" (Prompt)

        setStrictMode(action === 'presale');
        setModalVisible(true);

        // Return a promise that resolves when user makes a choice
        return new Promise<boolean>((resolve) => {
            resolveRef.current = resolve;
        });
    }, [userProfile, myBalancesData]);

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
                console.log('UseBackupEnforcement: Existing backups found, prompting with ExistingBackupModal');

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

    const handleCancel = () => {
        setModalVisible(false);
        if (strictMode) {
            // Presale -> Blocked
            resolveRef.current?.(false);
        } else {
            // Transaction/Launch -> Nag only, allow proceed
            resolveRef.current?.(true);
        }
    };

    // --- Handlers for ExistingBackupModal ---

    const handleRestore = async (entry: any | null) => {
        setExistingBackupModalVisible(false);
        try {
            // Restore from specific entry (or legacy if id is null/undefined)
            const entryId = entry?.id;
            console.log('User chose to restore. Target:', entryId || 'Legacy');

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
            console.log('User chose to Create New (Force Backup)');
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

    const handleCancelExistingModal = () => {
        setExistingBackupModalVisible(false);
        // If they cancel the choice, it's a fail or fallback depending on strict mode
        if (strictMode) {
            resolveRef.current?.(false);
        } else {
            resolveRef.current?.(true);
        }
    };

    const BackupEnforcementModal = () => (
        <>
            <BackupConsentModal
                visible={modalVisible}
                onContinue={handleContinue}
                onCancel={handleCancel}
            />
            <ExistingBackupModal
                visible={existingBackupModalVisible}
                entries={backupEntries}
                hasLegacy={hasLegacyBackup}
                onRestore={handleRestore}
                onUseCurrentWallet={handleUseCurrentWallet}
                onCancel={handleCancelExistingModal}
            />
        </>
    );

    return {
        checkBackupEnforcement,
        BackupEnforcementModal
    };
};
