import React from 'react';
import {
  SafeAreaView,
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Platform,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { useQuery, useMutation } from '@apollo/client';
import { Buffer } from 'buffer';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { GET_MY_REFERRALS } from '../apollo/queries';
import {
  PREPARE_REFERRAL_REWARD_CLAIM,
  SUBMIT_REFERRAL_REWARD_CLAIM,
} from '../apollo/mutations';
import algorandService from '../services/algorandService';
import { useAuth } from '../contexts/AuthContext';

const colors = {
  background: '#FFFFFF',
  surface: '#FFFFFF',
  accent: '#047857',
  accentSoft: '#ECFDF5',
  textPrimary: '#0F172A',
  textMuted: '#6B7280',
  border: 'rgba(15,23,42,0.08)',
};

type UserInfo = {
  id: string;
  username?: string | null;
  phoneKey?: string | null;
  firstName?: string | null;
  lastName?: string | null;
};

type Referral = {
  id: string;
  referredUser: UserInfo;
  referrerUser?: UserInfo | null;
  referrerIdentifier: string;
  status: string;
  firstTransactionAt?: string | null;
  rewardRefereeConfio: number;
  rewardReferrerConfio: number;
  refereeRewardStatus: string;
  referrerRewardStatus: string;
  rewardClaimedAt?: string | null;
  viewerRewardEventId?: string | null;
  createdAt: string;
};

export const ReferralRewardClaimScreen: React.FC = () => {
  const navigation = useNavigation();
  const { userProfile } = useAuth();
  const currentUserId = userProfile?.id ? String(userProfile.id) : null;
  const insets = useSafeAreaInsets();
  const { data, loading, error, refetch } = useQuery(GET_MY_REFERRALS, {
    fetchPolicy: 'cache-and-network',
  });
  const [prepareClaim] = useMutation(PREPARE_REFERRAL_REWARD_CLAIM);
  const [submitClaim] = useMutation(SUBMIT_REFERRAL_REWARD_CLAIM);
  const [busyId, setBusyId] = React.useState<string | null>(null);

  const referrals: Referral[] = data?.myReferrals || [];

  // Determine viewer role for each referral
  const getViewerRole = React.useCallback(
    (referral: Referral): 'referrer' | 'referee' => {
      const referrerId = referral.referrerUser?.id
        ? String(referral.referrerUser.id)
        : null;
      const refereeId = referral.referredUser?.id
        ? String(referral.referredUser.id)
        : null;

      if (currentUserId && referrerId === currentUserId) {
        return 'referrer';
      }
      if (currentUserId && refereeId === currentUserId) {
        return 'referee';
      }
      // Fallback to referrer when unknown to avoid showing "Te invitó" incorrectly
      return 'referrer';
    },
    [currentUserId],
  );

  // Filter referrals by status based on current user's role
  const claimable = referrals.filter((ref) => {
    const role = getViewerRole(ref);
    const status =
      role === 'referrer' ? ref.referrerRewardStatus : ref.refereeRewardStatus;
    return status?.toLowerCase() === 'eligible';
  });

  const pendingReferrals = referrals.filter((ref) => {
    const role = getViewerRole(ref);
    const status =
      role === 'referrer' ? ref.referrerRewardStatus : ref.refereeRewardStatus;
    return status?.toLowerCase() === 'pending';
  });
  const toNumber = (value: number | string | null | undefined) =>
    Number(value ?? 0);

  // Get the reward amount for a referral based on current user's role
  const getReferralAmount = (referral: Referral): number => {
    const role = getViewerRole(referral);
    return role === 'referrer'
      ? toNumber(referral.rewardReferrerConfio)
      : toNumber(referral.rewardRefereeConfio);
  };

  const totalClaimable = claimable.reduce(
    (sum, ref) => sum + getReferralAmount(ref),
    0,
  );

  const getUserDisplayName = (user?: UserInfo | null): string => {
    if (!user) return 'Usuario';
    return (
      user.username ||
      user.phoneKey ||
      `${user.firstName || ''} ${user.lastName || ''}`.trim() ||
      'Usuario'
    );
  };

  const handleBack = React.useCallback(() => {
    navigation.goBack();
  }, [navigation]);

  const handlePendingPress = React.useCallback(
    (referral: Referral) => {
      const role = getViewerRole(referral);
      const viewerStatus =
        role === 'referrer'
          ? referral.referrerRewardStatus
          : referral.refereeRewardStatus;
      const isPending = viewerStatus?.toLowerCase() === 'pending';
      const nextEvent = 'top_up';
      if (isPending) {
        navigation.navigate(
          'ReferralActionPrompt' as never,
          {
            event: nextEvent,
          } as never,
        );
      } else {
        navigation.navigate(
          'ReferralFriendJoined' as never,
          {
            event: nextEvent,
          } as never,
        );
      }
    },
    [getViewerRole, navigation],
  );

  type ListSection =
    | { type: 'summary'; totalClaimable: number }
    | { type: 'empty' }
    | { type: 'claimableHeader' }
    | { type: 'claimable'; referral: Referral }
    | { type: 'pendingHeader' }
    | { type: 'pending'; referral: Referral };

  const listData = React.useMemo<ListSection[]>(() => {
    const sections: ListSection[] = [];
    sections.push({ type: 'summary', totalClaimable });

    if (claimable.length === 0 && pendingReferrals.length === 0) {
      sections.push({ type: 'empty' });
      return sections;
    }

    if (claimable.length > 0) {
      claimable.forEach((referral) => {
        sections.push({ type: 'claimable', referral });
      });
    }

    if (pendingReferrals.length > 0) {
      sections.push({ type: 'pendingHeader' });
      pendingReferrals.forEach((referral) => {
        sections.push({ type: 'pending', referral });
      });
    }

    return sections;
  }, [claimable, pendingReferrals, totalClaimable]);


  const keyExtractor = React.useCallback((item: ListSection, index: number) => {
    if (item.type === 'claimable' || item.type === 'pending') {
      return `${item.type}-${item.referral.id}`;
    }
    return `${item.type}-${index}`;
  }, []);

  const renderListItem = React.useCallback(
    ({ item }: { item: ListSection }) => {
      if (item.type === 'summary') {
        return (
          <View style={styles.summaryCard}>
            <Text style={styles.summaryLabel}>Listo para reclamar</Text>
            <Text style={styles.summaryValue}>
              {item.totalClaimable.toFixed(2)} $CONFIO
            </Text>
            <Text style={styles.summarySubtext}>
              Estas recompensas fueron confirmadas on-chain y ya puedes
              reclamarlas. Firmaremos una transacción para que las recibas en tu
              billetera Confío.
            </Text>
          </View>
        );
      }

      if (item.type === 'empty') {
        return (
          <View style={styles.emptyState}>
            <Icon name="gift" size={32} color={colors.textMuted} />
            <Text style={styles.emptyTitle}>Sin recompensas pendientes</Text>
            <Text style={styles.emptySubtitle}>
              Si completaste una misión, asegúrate de iniciar sesión con la
              cuenta que ganó el bono o inténtalo más tarde.
            </Text>
          </View>
        );
      }

      if (item.type === 'pendingHeader') {
        return (
          <View style={styles.pendingSection}>
            <Text style={styles.pendingTitle}>Bonos en progreso</Text>
            <Text style={styles.pendingSubtitle}>
              Completa tu primera transacción para desbloquear estos bonos.
            </Text>
          </View>
        );
      }

      if (item.type === 'claimable') {
        const referral = item.referral;
        const amount = getReferralAmount(referral);
        const isReferrer = getViewerRole(referral) === 'referrer';
        const otherUser = isReferrer ? referral.referredUser : referral.referrerUser;

        return (
          <View key={referral.id} style={styles.rewardCard}>
            <View style={styles.rewardHeader}>
              <View>
                <Text style={styles.rewardTitle}>
                  {amount.toFixed(2)} $CONFIO
                </Text>
                <Text style={styles.rewardSubtitle}>
                  {isReferrer ? 'Invitaste a' : 'Te invitó'}{' '}
                  {getUserDisplayName(otherUser)}
                </Text>
              </View>
              <TouchableOpacity
                style={[
                  styles.claimButton,
                  busyId === referral.id && styles.claimButtonDisabled,
                ]}
                disabled={busyId === referral.id}
                onPress={() => handleClaim(referral)}>
                {busyId === referral.id ? (
                  <ActivityIndicator color="#fff" size="small" />
                ) : (
                  <>
                    <Icon name="unlock" size={16} color="#fff" />
                    <Text style={styles.claimButtonText}>Reclamar</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
            <Text style={styles.rewardMeta}>
              Rol: {isReferrer ? 'Invitador' : 'Referido'}
            </Text>
            <Text style={styles.rewardMeta}>
              Fecha: {new Date(referral.createdAt).toLocaleString()}
            </Text>
          </View>
        );
      }

      if (item.type === 'pending') {
        const referral = item.referral;
        const isReferrer = getViewerRole(referral) === 'referrer';
        const amount = getReferralAmount(referral);
        const otherUser = isReferrer ? referral.referredUser : referral.referrerUser;
        const otherUserDisplay = getUserDisplayName(otherUser);

        const requirementText = isReferrer
          ? `Ayuda a ${otherUserDisplay} a completar su primera transacción válida para liberar el bono para ambos.`
          : 'Completa tu primera transacción válida para desbloquear el bono.';

        return (
          <TouchableOpacity
            key={`pending-${referral.id}`}
            style={[styles.rewardCard, styles.pendingCard]}
            activeOpacity={0.85}
            onPress={() => handlePendingPress(referral)}>
            <View style={styles.rewardHeader}>
              <View>
                <Text style={styles.rewardTitle}>
                  {amount.toFixed(2)} $CONFIO
                </Text>
                <Text style={styles.rewardSubtitle}>
                  {isReferrer ? 'Invitaste a' : 'Te invitó'}{' '}
                  {otherUserDisplay}
                </Text>
              </View>
              <View style={styles.pendingBadge}>
                <Icon name="clock" size={14} color={colors.accent} />
                <Text style={styles.pendingBadgeText}>Pendiente</Text>
              </View>
            </View>
            <Text style={styles.rewardMeta}>
              Rol: {isReferrer ? 'Invitador' : 'Referido'}
            </Text>
            {isReferrer && (
              <Text style={styles.rewardMeta}>
                Invitado: {otherUserDisplay}
              </Text>
            )}
            <Text style={styles.rewardMeta}>{requirementText}</Text>
            <Text style={styles.rewardMeta}>
              Registrado: {new Date(referral.createdAt).toLocaleString()}
            </Text>
            <View style={styles.pendingHint}>
              <Text style={styles.pendingHintText}>Ver guía</Text>
              <Icon name="chevron-right" size={16} color={colors.accent} />
            </View>
          </TouchableOpacity>
        );
      }

      return null;
    },
    [busyId, getReferralAmount, getUserDisplayName, handleClaim, handlePendingPress, getViewerRole],
  );

  const handleClaim = React.useCallback(
    async (referral: Referral) => {
      if (busyId) return;
      setBusyId(referral.id);

      try {
        const eventId = referral.viewerRewardEventId || null;
        if (!eventId) {
          throw new Error('No pudimos encontrar la recompensa para este rol.');
        }
        const prepareRes = await prepareClaim({
          variables: { eventId },
        });
        const payload = prepareRes.data?.prepareReferralRewardClaim;
        if (!payload?.success) {
          throw new Error(payload?.error || 'No pudimos preparar el reclamo.');
        }

        const unsigned = payload.unsignedTransaction;
        const token = payload.claimToken;
        const unsignedBytes = Buffer.from(unsigned, 'base64');
        const signedBytes = await algorandService.signTransactionBytes(
          Uint8Array.from(unsignedBytes),
        );
        const signedB64 = Buffer.from(signedBytes).toString('base64');

        const submitRes = await submitClaim({
          variables: {
            claimToken: token,
            signedTransaction: signedB64,
          },
        });
        const submitPayload = submitRes.data?.submitReferralRewardClaim;
        if (!submitPayload?.success) {
          throw new Error(
            submitPayload?.error || 'No pudimos enviar la transacción.',
          );
        }

        Alert.alert('¡Listo!', 'Tus $CONFIO fueron reclamados con éxito.');
        await refetch();
      } catch (err: any) {
        const message =
          err?.message || 'Ocurrió un error al reclamar la recompensa.';
        Alert.alert('Ups', message);
      } finally {
        setBusyId(null);
      }
    },
    [busyId, prepareClaim, submitClaim, refetch],
  );

  const headerPaddingTop = Platform.OS === 'android' ? insets.top + 12 : 12;

  return (
    <SafeAreaView style={styles.container}>
      <View style={[styles.header, { paddingTop: headerPaddingTop }]}>
        <TouchableOpacity onPress={handleBack} style={styles.backButton}>
          <Icon name="arrow-left" size={22} color={colors.textPrimary} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Reclamar $CONFIO</Text>
        <View style={styles.headerSpacer} />
      </View>

      {loading ? (
        <View style={styles.loadingState}>
          <ActivityIndicator size="large" color={colors.accent} />
          <Text style={styles.loadingText}>
            Buscando recompensas disponibles...
          </Text>
        </View>
      ) : error ? (
        <View style={styles.errorState}>
          <Icon name="alert-circle" size={32} color="#DC2626" />
          <Text style={styles.errorTitle}>No pudimos cargar tus bonos</Text>
          <Text style={styles.errorSubtitle}>
            {error.message || 'Intenta de nuevo en unos segundos.'}
          </Text>
          <TouchableOpacity style={styles.retryButton} onPress={() => refetch()}>
            <Text style={styles.retryButtonText}>Reintentar</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={listData}
          renderItem={renderListItem}
          keyExtractor={keyExtractor}
          style={styles.scroll}
          contentContainerStyle={{ padding: 20, paddingBottom: 32 }}
          initialNumToRender={50}
          maxToRenderPerBatch={20}
          windowSize={10}
          removeClippedSubviews={false}
        />
      )}
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.background,
  },
  backButton: {
    padding: 6,
  },
  headerTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: '600',
  },
  headerSpacer: {
    width: 32,
  },
  loadingState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    color: colors.textMuted,
    marginTop: 12,
  },
  scroll: {
    flex: 1,
  },
  summaryCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 20,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: '#0f172a',
    shadowOpacity: 0.05,
    shadowOffset: { width: 0, height: 6 },
    shadowRadius: 12,
    elevation: 2,
  },
  summaryLabel: {
    color: colors.textMuted,
    fontSize: 14,
  },
  summaryValue: {
    color: colors.textPrimary,
    fontSize: 30,
    fontWeight: '700',
    marginVertical: 6,
  },
  summarySubtext: {
    color: colors.textMuted,
    fontSize: 14,
    lineHeight: 20,
  },
  emptyState: {
    marginTop: 40,
    alignItems: 'center',
    paddingHorizontal: 16,
  },
  emptyTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: '600',
    marginTop: 12,
  },
  emptySubtitle: {
    color: colors.textMuted,
    textAlign: 'center',
    marginTop: 8,
    lineHeight: 20,
  },
  rewardCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 16,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: '#0f172a',
    shadowOpacity: 0.04,
    shadowOffset: { width: 0, height: 4 },
    shadowRadius: 10,
    elevation: 1,
  },
  rewardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  pendingCard: {
    borderColor: colors.accent,
  },
  pendingSection: {
    marginTop: 24,
    marginBottom: 8,
  },
  pendingTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.textPrimary,
  },
  pendingSubtitle: {
    fontSize: 14,
    color: colors.textMuted,
    marginTop: 4,
  },
  pendingBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: colors.accentSoft,
  },
  pendingBadgeText: {
    marginLeft: 6,
    color: colors.accent,
    fontWeight: '600',
    fontSize: 13,
  },
  pendingHint: {
    marginTop: 12,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: 4,
  },
  pendingHintText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.accent,
  },
  rewardTitle: {
    color: colors.textPrimary,
    fontSize: 20,
    fontWeight: '600',
  },
  rewardSubtitle: {
    color: colors.textMuted,
    fontSize: 13,
    marginTop: 2,
    textTransform: 'capitalize',
  },
  rewardMeta: {
    color: colors.textMuted,
    fontSize: 12,
    marginTop: 4,
  },
  claimButton: {
    backgroundColor: colors.accent,
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: 999,
    flexDirection: 'row',
    alignItems: 'center',
  },
  claimButtonDisabled: {
    backgroundColor: 'rgba(4,120,87,0.35)',
  },
  claimButtonText: {
    color: '#fff',
    fontWeight: '600',
    marginLeft: 6,
  },
  errorState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  errorTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: '600',
    marginTop: 12,
  },
  errorSubtitle: {
    color: colors.textMuted,
    textAlign: 'center',
    marginTop: 6,
    marginBottom: 16,
  },
  retryButton: {
    backgroundColor: colors.accent,
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 12,
  },
  retryButtonText: {
    color: '#fff',
    fontWeight: '600',
  },
});

export default ReferralRewardClaimScreen;
