import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useApolloClient } from '@apollo/client';
import { useAuth } from '../contexts/AuthContext';
import { GET_ME } from '../apollo/queries';
import { ExistingBackupModal } from '../components/ExistingBackupModal';
import authService from '../services/authService';

export const BackupCompletionScreen = () => {
  const apolloClient = useApolloClient();
  const { handleSuccessfulLogin, refreshProfile, signOut } = useAuth();
  const [isRetrying, setIsRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showExistingBackupModal, setShowExistingBackupModal] = useState(false);
  const [existingBackupEntries, setExistingBackupEntries] = useState<any[]>([]);
  const [hasLegacyBackup, setHasLegacyBackup] = useState(false);

  useEffect(() => {
    refreshProfile('personal').catch(err => {
      console.warn('[BackupCompletion] Failed to refresh profile on mount:', err);
    });
  }, [refreshProfile]);

  const continueOnboardingIfSafe = useCallback(async () => {
    await refreshProfile('personal');
    const { data } = await apolloClient.query({
      query: GET_ME,
      fetchPolicy: 'network-only',
    });
    const me = data?.me;
    if (me?.requiresBackupCompletion) {
      setError('Todavia no pudimos confirmar el respaldo en el servidor. Intenta nuevamente.');
      return;
    }
    const phoneVerified = !!(me?.phoneNumber && me?.phoneCountry);
    await handleSuccessfulLogin(phoneVerified, false);
  }, [apolloClient, handleSuccessfulLogin, refreshProfile]);

  const handleRetryBackup = useCallback(async (forceBackup: boolean = false) => {
    setIsRetrying(true);
    setError(null);

    try {
      const result = await authService.enableDriveBackup(forceBackup);

      if (result.success) {
        await continueOnboardingIfSafe();
        return;
      }

      if (result.existingBackups) {
        const entries = result.existingBackups.entriesToShow || result.existingBackups.entries || [];
        entries.sort((a: any, b: any) => {
          const timeA = a.lastBackupAt ? new Date(a.lastBackupAt).getTime() : 0;
          const timeB = b.lastBackupAt ? new Date(b.lastBackupAt).getTime() : 0;
          return timeB - timeA;
        });

        setExistingBackupEntries(entries);
        setHasLegacyBackup(result.existingBackups.hasLegacy || false);
        setShowExistingBackupModal(true);
        return;
      }

      setError(result.error || 'No pudimos terminar el respaldo seguro.');
    } catch (retryErr: any) {
      console.error('[BackupCompletion] Backup retry failed:', retryErr);
      setError(retryErr?.message || 'No pudimos terminar el respaldo seguro.');
    } finally {
      setIsRetrying(false);
    }
  }, [continueOnboardingIfSafe]);

  const handleRestore = useCallback(async (entry: any | null) => {
    setShowExistingBackupModal(false);
    setIsRetrying(true);
    setError(null);

    try {
      const restoreRes = await authService.restoreFromDriveBackup(entry?.id, entry?.lastBackupAt);
      if (!restoreRes.success) {
        setError(restoreRes.error || 'No se pudo restaurar la billetera.');
        return;
      }

      await continueOnboardingIfSafe();
    } catch (restoreErr: any) {
      console.error('[BackupCompletion] Restore failed:', restoreErr);
      setError(restoreErr?.message || 'No se pudo restaurar la billetera.');
    } finally {
      setIsRetrying(false);
    }
  }, [continueOnboardingIfSafe]);

  const handleUseCurrentWallet = useCallback(async () => {
    setShowExistingBackupModal(false);
    await handleRetryBackup(true);
  }, [handleRetryBackup]);

  return (
    <SafeAreaView style={styles.container} edges={['top', 'left', 'right', 'bottom']}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <View style={styles.badge}>
          <Icon name="shield" size={28} color="#2563EB" />
        </View>

        <Text style={styles.title}>Terminemos tu respaldo seguro</Text>
        <Text style={styles.body}>
          Tu cuenta ya fue verificada, pero todavía no pudimos confirmar el respaldo cifrado en Google Drive.
          Antes de entrar a Confio, necesitamos completar ese paso para que no pierdas acceso si cambias de teléfono.
        </Text>

        <View style={styles.card}>
          <View style={styles.row}>
            <Icon name="check-circle" size={18} color="#10B981" />
            <Text style={styles.rowText}>Tu cuenta de Google ya está vinculada.</Text>
          </View>
          <View style={styles.row}>
            <Icon name="alert-triangle" size={18} color="#F59E0B" />
            <Text style={styles.rowText}>Falta confirmar el respaldo seguro en tu Google Drive.</Text>
          </View>
          <View style={styles.row}>
            <Icon name="refresh-cw" size={18} color="#2563EB" />
            <Text style={styles.rowText}>Reintenta aquí sin empezar el registro desde cero.</Text>
          </View>
        </View>

        {error ? (
          <View style={styles.errorBox}>
            <Icon name="x-circle" size={16} color="#DC2626" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : null}

        <TouchableOpacity
          style={[styles.primaryButton, isRetrying && styles.buttonDisabled]}
          onPress={() => handleRetryBackup(false)}
          disabled={isRetrying}
        >
          {isRetrying ? <ActivityIndicator color="#FFFFFF" /> : <Text style={styles.primaryText}>Reintentar respaldo</Text>}
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.secondaryButton, isRetrying && styles.buttonDisabled]}
          onPress={() => {
            Alert.alert(
              'Salir',
              'Cerraremos tu sesión para que puedas intentar de nuevo más tarde.',
              [
                { text: 'Cancelar', style: 'cancel' },
                { text: 'Salir', style: 'destructive', onPress: () => { signOut().catch(() => undefined); } },
              ]
            );
          }}
          disabled={isRetrying}
        >
          <Text style={styles.secondaryText}>Salir por ahora</Text>
        </TouchableOpacity>
      </ScrollView>

      <ExistingBackupModal
        visible={showExistingBackupModal}
        entries={existingBackupEntries}
        hasLegacy={hasLegacyBackup}
        onRestore={handleRestore}
        onUseCurrentWallet={handleUseCurrentWallet}
        onCancel={() => setShowExistingBackupModal(false)}
      />
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F8FAFC',
  },
  content: {
    flexGrow: 1,
    paddingHorizontal: 24,
    paddingVertical: 32,
    justifyContent: 'center',
  },
  badge: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: '#DBEAFE',
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'center',
    marginBottom: 24,
  },
  title: {
    fontSize: 28,
    fontWeight: '800',
    color: '#0F172A',
    textAlign: 'center',
    marginBottom: 12,
  },
  body: {
    fontSize: 16,
    lineHeight: 24,
    color: '#475569',
    textAlign: 'center',
    marginBottom: 24,
  },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    padding: 20,
    marginBottom: 20,
    borderWidth: 1,
    borderColor: '#E2E8F0',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 14,
  },
  rowText: {
    flex: 1,
    marginLeft: 12,
    color: '#334155',
    fontSize: 15,
    lineHeight: 22,
  },
  errorBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: '#FEF2F2',
    borderRadius: 14,
    padding: 14,
    marginBottom: 20,
  },
  errorText: {
    flex: 1,
    marginLeft: 10,
    color: '#991B1B',
    fontSize: 14,
    lineHeight: 20,
  },
  primaryButton: {
    height: 56,
    borderRadius: 16,
    backgroundColor: '#2563EB',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 12,
  },
  secondaryButton: {
    height: 56,
    borderRadius: 16,
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#CBD5E1',
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonDisabled: {
    opacity: 0.7,
  },
  primaryText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
  },
  secondaryText: {
    color: '#334155',
    fontSize: 16,
    fontWeight: '700',
  },
});

export default BackupCompletionScreen;
