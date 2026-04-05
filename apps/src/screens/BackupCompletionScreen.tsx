import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, LinearGradient, Stop, Circle as SvgCircle } from 'react-native-svg';
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
    refreshProfile('personal').catch(err => {    });
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

  const handleRetryBackup = useCallback(async (forceBackup: boolean = true) => {
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
      {/* Background decorative elements */}
      <View style={styles.bgDecoration}>
        <Svg width="100%" height="100%" style={StyleSheet.absoluteFill}>
          <Defs>
            <LinearGradient id="bgGrad" x1="0" y1="0" x2="1" y2="1">
              <Stop offset="0" stopColor="#34D399" stopOpacity="0.06" />
              <Stop offset="1" stopColor="#8B5CF6" stopOpacity="0.04" />
            </LinearGradient>
          </Defs>
          <SvgCircle cx="85%" cy="10%" r="120" fill="#34D399" fillOpacity={0.05} />
          <SvgCircle cx="10%" cy="90%" r="80" fill="#8B5CF6" fillOpacity={0.04} />
        </Svg>
      </View>

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {/* Icon badge with gradient ring */}
        <View style={styles.badgeOuter}>
          <View style={styles.badge}>
            <Icon name="shield" size={30} color="#10B981" />
          </View>
        </View>

        {/* Progress dots */}
        <View style={styles.progressRow}>
          <View style={[styles.progressDot, styles.progressDotDone]} />
          <View style={styles.progressBar}>
            <View style={styles.progressBarFill} />
          </View>
          <View style={[styles.progressDot, styles.progressDotPending]} />
        </View>
        <Text style={styles.progressLabel}>Paso 1 de 2 completado</Text>

        <Text style={styles.title}>Terminemos tu respaldo seguro</Text>
        <Text style={styles.body}>
          Tu cuenta ya fue verificada, pero falta confirmar el respaldo cifrado en Google Drive para proteger tu acceso.
        </Text>

        <View style={styles.card}>
          <View style={styles.row}>
            <View style={[styles.iconCircle, styles.iconCircleSuccess]}>
              <Icon name="check" size={14} color="#10B981" />
            </View>
            <View style={styles.rowContent}>
              <Text style={styles.rowTitle}>Cuenta vinculada</Text>
              <Text style={styles.rowSubtitle}>Tu cuenta de Google está conectada</Text>
            </View>
          </View>
          <View style={styles.divider} />
          <View style={styles.row}>
            <View style={[styles.iconCircle, styles.iconCircleWarning]}>
              <Icon name="cloud-off" size={14} color="#F59E0B" />
            </View>
            <View style={styles.rowContent}>
              <Text style={styles.rowTitle}>Respaldo pendiente</Text>
              <Text style={styles.rowSubtitle}>Falta confirmar el cifrado en Google Drive</Text>
            </View>
          </View>
        </View>

        {error ? (
          <View style={styles.errorBox}>
            <Icon name="alert-circle" size={18} color="#DC2626" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : null}

        <TouchableOpacity
          style={[styles.primaryButton, isRetrying && styles.buttonDisabled]}
          onPress={() => handleRetryBackup(true)}
          disabled={isRetrying}
          activeOpacity={0.8}
        >
          {isRetrying ? (
            <ActivityIndicator color="#FFFFFF" />
          ) : (
            <View style={styles.buttonInner}>
              <Icon name="refresh-cw" size={18} color="#FFFFFF" style={styles.buttonIcon} />
              <Text style={styles.primaryText}>Reintentar respaldo</Text>
            </View>
          )}
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
          activeOpacity={0.7}
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
    backgroundColor: '#FFFFFF',
  },
  bgDecoration: {
    ...StyleSheet.absoluteFillObject,
  },
  content: {
    flexGrow: 1,
    paddingHorizontal: 24,
    paddingTop: 40,
    paddingBottom: 32,
  },
  badgeOuter: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#D1FAE5',
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'center',
    marginBottom: 20,
  },
  badge: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: '#ECFDF5',
    alignItems: 'center',
    justifyContent: 'center',
  },
  progressRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 8,
  },
  progressDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
  },
  progressDotDone: {
    backgroundColor: '#10B981',
  },
  progressDotPending: {
    backgroundColor: '#E2E8F0',
    borderWidth: 2,
    borderColor: '#F59E0B',
  },
  progressBar: {
    width: 48,
    height: 3,
    backgroundColor: '#E2E8F0',
    marginHorizontal: 8,
    borderRadius: 2,
  },
  progressBarFill: {
    width: '50%',
    height: '100%',
    backgroundColor: '#10B981',
    borderRadius: 2,
  },
  progressLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: '#10B981',
    textAlign: 'center',
    marginBottom: 20,
  },
  title: {
    fontSize: 26,
    fontWeight: '800',
    color: '#111827',
    textAlign: 'center',
    marginBottom: 10,
    letterSpacing: -0.3,
  },
  body: {
    fontSize: 15,
    lineHeight: 23,
    color: '#6B7280',
    textAlign: 'center',
    marginBottom: 28,
    paddingHorizontal: 8,
  },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    padding: 20,
    marginBottom: 24,
    borderWidth: 1,
    borderColor: '#F3F4F6',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 12,
    elevation: 3,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
  },
  iconCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconCircleSuccess: {
    backgroundColor: '#ECFDF5',
  },
  iconCircleWarning: {
    backgroundColor: '#FFFBEB',
  },
  rowContent: {
    flex: 1,
    marginLeft: 14,
  },
  rowTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: '#111827',
    marginBottom: 2,
  },
  rowSubtitle: {
    fontSize: 13,
    color: '#6B7280',
    lineHeight: 18,
  },
  divider: {
    height: 1,
    backgroundColor: '#F3F4F6',
    marginVertical: 14,
    marginLeft: 50,
  },
  errorBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FEF2F2',
    borderRadius: 14,
    padding: 14,
    marginBottom: 20,
    borderWidth: 1,
    borderColor: '#FECACA',
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
    backgroundColor: '#10B981',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 12,
    shadowColor: '#10B981',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.2,
    shadowRadius: 8,
    elevation: 4,
  },
  secondaryButton: {
    height: 56,
    borderRadius: 16,
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonInner: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  buttonIcon: {
    marginRight: 8,
  },
  primaryText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
  },
  secondaryText: {
    color: '#6B7280',
    fontSize: 16,
    fontWeight: '600',
  },
});

export default BackupCompletionScreen;
