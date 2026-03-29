import React from 'react';
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { NavigationProp, useFocusEffect, useNavigation } from '@react-navigation/native';
import { useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import { Header } from '../navigation/Header';
import { RootStackParamList } from '../types/navigation';
import { GET_BUSINESS_KYC_STATUS, GET_ME, GET_MY_KYC_STATUS, GET_MY_PERSONAL_KYC_STATUS } from '../apollo/queries';
import { CREATE_DIDIT_VERIFICATION_SESSION, SYNC_DIDIT_VERIFICATION_SESSION } from '../apollo/mutations';
import { useAccount } from '../contexts/AccountContext';
import { getDiditResultSessionId, startDiditVerification } from '../services/diditService';

const colors = {
  primary: '#34D399',
  primaryDark: '#059669',
  primaryLight: '#D1FAE5',
  info: '#2563EB',
  infoLight: '#DBEAFE',
  warning: '#F59E0B',
  warningLight: '#FEF3C7',
  danger: '#DC2626',
  dangerLight: '#FEE2E2',
  success: '#10B981',
  successLight: '#D1FAE5',
  dark: '#111827',
  textMuted: '#6B7280',
  surface: '#FFFFFF',
  surfaceMuted: '#F9FAFB',
  border: '#E5E7EB',
};

type NormalizedStatus = 'unverified' | 'pending' | 'verified' | 'rejected';

type VerificationLevel = {
  level: number;
  title: string;
  subtitle: string;
  features: string[];
};

const verificationLevels: VerificationLevel[] = [
  {
    level: 0,
    title: 'Cuenta básica',
    subtitle: 'Teléfono confirmado',
    features: [
      'Envíos a billeteras externas con límites reducidos.',
      'Retiros grandes de recompensas quedan bloqueados.',
      'Todavía puedes operar dentro de Confío.',
    ],
  },
  {
    level: 1,
    title: 'Identidad verificada',
    subtitle: 'Didit completado',
    features: [
      'Desbloquea retiros grandes de recompensas.',
      'Tu verificación queda guardada en tu cuenta.',
      'Tu información validada puede usarse para habilitar más servicios.',
    ],
  },
];

function normalizeStatus(value?: string | null): NormalizedStatus {
  const normalized = (value || '').trim().toLowerCase();
  if (['pending', 'submitted', 'in_review', 'review required', 'in progress'].includes(normalized)) {
    return 'pending';
  }
  if (['verified', 'approved', 'completed', 'success'].includes(normalized)) {
    return 'verified';
  }
  if (['rejected', 'declined', 'failed', 'denied'].includes(normalized)) {
    return 'rejected';
  }
  return 'unverified';
}

function statusText(status: NormalizedStatus): string {
  switch (status) {
    case 'verified':
      return 'Verificado';
    case 'pending':
      return 'En revisión';
    case 'rejected':
      return 'Vuelve a intentarlo';
    default:
      return 'Aún no verificado';
  }
}

function statusMeta(status: NormalizedStatus) {
  switch (status) {
    case 'verified':
      return {
        label: 'Verificado',
        description: 'Tu identidad ya fue confirmada correctamente.',
        color: colors.success,
        bg: colors.successLight,
        icon: 'check-circle',
      };
    case 'pending':
      return {
        label: 'En revisión',
        description: 'Ya recibimos tu verificación. Ahora la estamos revisando.',
        color: colors.warning,
        bg: colors.warningLight,
        icon: 'clock',
      };
    case 'rejected':
      return {
        label: 'Rechazado',
        description: 'La última sesión no aprobó. Puedes iniciar una nueva verificación.',
        color: colors.danger,
        bg: colors.dangerLight,
        icon: 'x-circle',
      };
    default:
      return {
        label: 'Sin verificar',
        description: 'Necesitas confirmar tu identidad para desbloquear más funciones.',
        color: colors.info,
        bg: colors.infoLight,
        icon: 'shield',
      };
  }
}

function getStatusDetail(status: NormalizedStatus, detail?: string | null): string {
  const trimmed = (detail || '').trim();
  if (trimmed) {
    return trimmed;
  }
  return statusMeta(status).description;
}

const VerificationScreen = () => {
  const navigation = useNavigation<NavigationProp<RootStackParamList>>();
  const { activeAccount } = useAccount();
  const isBusinessAccount = (activeAccount?.type || '').toLowerCase() === 'business';

  const { data: meData, refetch: refetchMe, loading: meLoading } = useQuery(GET_ME, { fetchPolicy: 'network-only' });
  const { data: personalKycData, refetch: refetchPersonalKyc, loading: personalLoading } = useQuery(GET_MY_PERSONAL_KYC_STATUS, { fetchPolicy: 'network-only' });
  const { data: anyKycData, refetch: refetchAnyKyc, loading: anyLoading } = useQuery(GET_MY_KYC_STATUS, { fetchPolicy: 'network-only' });
  const { data: bizKycData, refetch: refetchBizKyc, loading: businessLoading } = useQuery(
    GET_BUSINESS_KYC_STATUS,
    {
      variables: { businessId: activeAccount?.business?.id || '' },
      skip: !isBusinessAccount || !activeAccount?.business?.id,
      fetchPolicy: 'network-only',
    },
  );

  const [createDiditSession] = useMutation(CREATE_DIDIT_VERIFICATION_SESSION);
  const [syncDiditSession] = useMutation(SYNC_DIDIT_VERIFICATION_SESSION);

  const [isLaunchingDidit, setIsLaunchingDidit] = React.useState(false);
  const [isRefreshing, setIsRefreshing] = React.useState(false);
  const [lastError, setLastError] = React.useState<string | null>(null);
  const [lastAttemptStatus, setLastAttemptStatus] = React.useState<'idle' | 'cancelled' | 'failed'>('idle');

  const personalStatus = normalizeStatus(personalKycData?.myPersonalKycStatus?.status || meData?.me?.verificationStatus);
  const anyStatus = normalizeStatus(anyKycData?.myKycStatus?.status);
  const businessStatus = normalizeStatus(bizKycData?.businessKycStatus?.status);
  const effectiveStatus = isBusinessAccount
    ? (businessStatus !== 'unverified' ? businessStatus : anyStatus)
    : (personalStatus !== 'unverified' ? personalStatus : anyStatus);
  const currentLevel = effectiveStatus === 'verified' ? 1 : 0;
  const activeStatusNode = isBusinessAccount
    ? (bizKycData?.businessKycStatus || anyKycData?.myKycStatus)
    : (personalKycData?.myPersonalKycStatus || anyKycData?.myKycStatus);
  const meta = {
    ...statusMeta(effectiveStatus),
    description: getStatusDetail(effectiveStatus, activeStatusNode?.statusDetail),
  };
  const isBusy = isLaunchingDidit || isRefreshing;
  const isInitialLoading = meLoading || personalLoading || anyLoading || businessLoading;

  const refreshStatuses = React.useCallback(async () => {
    setIsRefreshing(true);
    try {
      await Promise.all([
        refetchMe(),
        refetchPersonalKyc(),
        refetchAnyKyc(),
        isBusinessAccount && refetchBizKyc ? refetchBizKyc() : Promise.resolve(),
      ]);
    } finally {
      setIsRefreshing(false);
    }
  }, [isBusinessAccount, refetchAnyKyc, refetchBizKyc, refetchMe, refetchPersonalKyc]);

  useFocusEffect(
    React.useCallback(() => {
      refreshStatuses().catch((error) => {
        console.warn('[Verification] Failed to refresh Didit status on focus:', error);
      });
    }, [refreshStatuses]),
  );

  const syncSessionAndRefresh = React.useCallback(async (sessionId: string) => {
    const { data } = await syncDiditSession({ variables: { sessionId } });
    const result = data?.syncDiditVerificationSession;
    if (!result?.success) {
      throw new Error(result?.error || 'No se pudo sincronizar la decisión de Didit.');
    }

    await refreshStatuses();
    const normalized = normalizeStatus(result.verificationStatus);
    const detail = result.statusDetail || result.verification?.statusDetail;
    if (normalized === 'verified') {
      Alert.alert('Verificación completa', detail || 'Tu identidad quedó verificada correctamente.');
    } else if (normalized === 'pending') {
      Alert.alert('Verificación enviada', detail || 'Didit recibió tu sesión. Te avisaremos cuando termine la revisión.');
    } else if (normalized === 'rejected') {
      Alert.alert('Verificación rechazada', detail || 'La sesión fue rechazada. Puedes intentar nuevamente.');
    } else {
      Alert.alert('Sesión iniciada', detail || 'La sesión se creó, pero Didit todavía no devolvió un resultado final.');
    }
  }, [refreshStatuses, syncDiditSession]);

  const handleStartDidit = React.useCallback(async () => {
    setLastError(null);
    setLastAttemptStatus('idle');
    setIsLaunchingDidit(true);

    try {
      const { data } = await createDiditSession();
      const result = data?.createDiditVerificationSession;
      if (!result?.success || !result?.session?.sessionToken) {
        throw new Error(result?.error || 'No se pudo crear la sesión de Didit.');
      }

      const createdSessionId = result.session.sessionId;
      const sdkResult = await startDiditVerification(result.session.sessionToken);
      const sdkResultType = sdkResult?.type;

      if (sdkResultType === 'cancelled') {
        setLastAttemptStatus('cancelled');
        setLastError('Cancelaste la verificación antes de terminarla.');
        return;
      }

      if (sdkResultType === 'failed') {
        setLastAttemptStatus('failed');
        throw new Error(sdkResult?.errorMessage || 'No se pudo completar la verificación con Didit.');
      }

      const resolvedSessionId = getDiditResultSessionId(sdkResult, createdSessionId);
      if (!resolvedSessionId) {
        throw new Error('Didit no devolvió el identificador de sesión.');
      }

      await syncSessionAndRefresh(resolvedSessionId);
    } catch (error: any) {
      const message = error?.message || 'No se pudo completar la verificación con Didit.';
      setLastAttemptStatus('failed');
      setLastError(message);
      Alert.alert('Error de verificación', message);
    } finally {
      setIsLaunchingDidit(false);
    }
  }, [createDiditSession, syncSessionAndRefresh]);

  const primaryActionLabel = React.useMemo(() => {
    if (effectiveStatus === 'verified') {
      return 'Verificado';
    }
    if (lastAttemptStatus === 'cancelled') {
      return 'Volver a intentar';
    }
    if (lastAttemptStatus === 'failed') {
      return 'Intentar de nuevo';
    }
    if (effectiveStatus === 'pending') {
      return 'En revisión';
    }
    if (effectiveStatus === 'rejected') {
      return 'Reintentar con Didit';
    }
    return 'Verificar con Didit';
  }, [effectiveStatus, lastAttemptStatus]);

  return (
    <View style={styles.container}>
      <Header
        title="Verificación"
        navigation={navigation}
        backgroundColor={colors.primary}
        isLight={true}
      />

      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={isRefreshing} onRefresh={refreshStatuses} tintColor={colors.primaryDark} />}
      >
        <View style={styles.heroCard}>
          <View style={styles.heroHeader}>
            <View style={styles.heroBadge}>
              <Icon name="shield" size={18} color={colors.primaryDark} />
              <Text style={styles.heroBadgeText}>{isBusinessAccount ? 'Cuenta negocio' : 'Cuenta personal'}</Text>
            </View>
            <View style={[styles.statusPill, { backgroundColor: meta.bg }]}>
              <Icon name={meta.icon} size={16} color={meta.color} />
              <Text style={[styles.statusPillText, { color: meta.color }]}>{meta.label}</Text>
            </View>
          </View>

          <Text style={styles.heroTitle}>Confirma tu identidad para usar más funciones en Confío.</Text>
          <Text style={styles.heroDescription}>{meta.description}</Text>

          <View style={styles.heroActions}>
            <TouchableOpacity
              style={[
                styles.primaryButton,
                (isBusy || effectiveStatus === 'verified') && styles.primaryButtonDisabled,
              ]}
              onPress={handleStartDidit}
              disabled={isBusy || effectiveStatus === 'verified'}
              activeOpacity={0.9}
            >
              {isLaunchingDidit ? (
                <ActivityIndicator color="#FFFFFF" />
              ) : (
                <>
                  <Icon name="arrow-up-right" size={18} color="#FFFFFF" />
                  <Text style={styles.primaryButtonText}>{primaryActionLabel}</Text>
                </>
              )}
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.secondaryButton}
              onPress={refreshStatuses}
              disabled={isBusy}
              activeOpacity={0.9}
            >
              {isRefreshing ? (
                <ActivityIndicator color={colors.primaryDark} />
              ) : (
                <>
                  <Icon name="refresh-cw" size={18} color={colors.primaryDark} />
                  <Text style={styles.secondaryButtonText}>Actualizar estado</Text>
                </>
              )}
            </TouchableOpacity>
          </View>

          {lastError ? (
            <View style={styles.errorBox}>
              <Icon name="alert-triangle" size={16} color={colors.danger} />
              <Text style={styles.errorText}>{lastError}</Text>
            </View>
          ) : null}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Tu nivel actual</Text>
          {verificationLevels.map((level) => {
            const isActive = currentLevel >= level.level;
            return (
              <View key={level.level} style={[styles.levelCard, isActive && styles.levelCardActive]}>
                <View style={styles.levelHeader}>
                  <View>
                    <Text style={styles.levelTitle}>{level.title}</Text>
                    <Text style={styles.levelSubtitle}>{level.subtitle}</Text>
                  </View>
                  <Icon name={isActive ? 'check-circle' : 'circle'} size={20} color={isActive ? colors.primaryDark : colors.border} />
                </View>
                {level.features.map((feature) => (
                  <View key={feature} style={styles.featureRow}>
                    <Text style={styles.featureBullet}>•</Text>
                    <Text style={styles.featureText}>{feature}</Text>
                  </View>
                ))}
              </View>
            );
          })}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Qué pasará</Text>
          <View style={styles.infoCard}>
            <View style={styles.infoRow}>
              <Icon name="smartphone" size={18} color={colors.info} />
              <Text style={styles.infoText}>Se abrirá una verificación segura dentro de la app.</Text>
            </View>
            <View style={styles.infoRow}>
              <Icon name="file-text" size={18} color={colors.info} />
              <Text style={styles.infoText}>Te pediremos fotos de tu documento y una selfie.</Text>
            </View>
            <View style={styles.infoRow}>
              <Icon name="database" size={18} color={colors.info} />
              <Text style={styles.infoText}>Cuando termines, guardaremos el resultado en tu cuenta.</Text>
            </View>
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Estado de tu verificación</Text>
          <View style={styles.metaCard}>
            <Text style={styles.metaLabel}>Nombre</Text>
            <Text style={styles.metaValue}>{meData?.me?.firstName || meData?.me?.username || 'Sin nombre'}</Text>
            <Text style={styles.metaLabel}>Cuenta activa</Text>
            <Text style={styles.metaValue}>{isBusinessAccount ? activeAccount?.business?.name || 'Negocio' : 'Personal'}</Text>
            <Text style={styles.metaLabel}>Estado actual</Text>
            <Text style={styles.metaValue}>{statusText(effectiveStatus)}</Text>
            {isBusinessAccount ? (
              <>
                <Text style={styles.metaLabel}>Verificación del negocio</Text>
                <Text style={styles.metaValue}>{statusText(businessStatus)}</Text>
              </>
            ) : null}
          </View>
        </View>

        {isInitialLoading ? (
          <View style={styles.loadingBlock}>
            <ActivityIndicator color={colors.primaryDark} />
            <Text style={styles.loadingText}>Cargando estado de verificación…</Text>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.surfaceMuted,
  },
  scrollView: {
    flex: 1,
  },
  content: {
    padding: 20,
    gap: 18,
  },
  heroCard: {
    backgroundColor: colors.surface,
    borderRadius: 20,
    padding: 20,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 14,
  },
  heroHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  heroBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: colors.primaryLight,
  },
  heroBadgeText: {
    color: colors.primaryDark,
    fontSize: 13,
    fontWeight: '700',
  },
  statusPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
  },
  statusPillText: {
    fontSize: 13,
    fontWeight: '700',
  },
  heroTitle: {
    fontSize: 24,
    fontWeight: '800',
    color: colors.dark,
  },
  heroDescription: {
    fontSize: 15,
    lineHeight: 22,
    color: colors.textMuted,
  },
  heroActions: {
    gap: 12,
  },
  primaryButton: {
    backgroundColor: colors.primaryDark,
    borderRadius: 14,
    paddingVertical: 15,
    paddingHorizontal: 18,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
  },
  primaryButtonDisabled: {
    opacity: 0.6,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
  },
  secondaryButton: {
    backgroundColor: colors.surface,
    borderRadius: 14,
    paddingVertical: 15,
    paddingHorizontal: 18,
    borderWidth: 1,
    borderColor: colors.primaryLight,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
  },
  secondaryButtonText: {
    color: colors.primaryDark,
    fontSize: 16,
    fontWeight: '700',
  },
  errorBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    backgroundColor: colors.dangerLight,
    borderRadius: 12,
    padding: 14,
  },
  errorText: {
    flex: 1,
    color: colors.danger,
    fontSize: 14,
    lineHeight: 20,
  },
  section: {
    gap: 12,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '800',
    color: colors.dark,
  },
  levelCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 18,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 10,
  },
  levelCardActive: {
    borderColor: colors.primaryLight,
    backgroundColor: '#FCFFFE',
  },
  levelHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  levelTitle: {
    fontSize: 16,
    fontWeight: '800',
    color: colors.dark,
  },
  levelSubtitle: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: 2,
  },
  featureRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
  },
  featureBullet: {
    color: colors.primaryDark,
    fontWeight: '800',
    marginTop: 1,
  },
  featureText: {
    flex: 1,
    color: colors.dark,
    fontSize: 14,
    lineHeight: 20,
  },
  infoCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 18,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 14,
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  infoText: {
    flex: 1,
    color: colors.dark,
    fontSize: 14,
    lineHeight: 20,
  },
  metaCard: {
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 18,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 6,
  },
  metaLabel: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.4,
    textTransform: 'uppercase',
    color: colors.textMuted,
    marginTop: 6,
  },
  metaValue: {
    fontSize: 15,
    color: colors.dark,
    fontWeight: '600',
  },
  loadingBlock: {
    paddingVertical: 24,
    alignItems: 'center',
    gap: 10,
  },
  loadingText: {
    color: colors.textMuted,
    fontSize: 14,
  },
});

export default VerificationScreen;
