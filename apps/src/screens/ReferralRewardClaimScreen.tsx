import React from 'react';
import {
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
import { useNavigation, NavigationProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { useQuery, useMutation } from '@apollo/client';
import { Buffer } from 'buffer';
import { Header } from '../navigation/Header';

import { GET_MY_REFERRALS } from '../apollo/queries';
import {
  PREPARE_REFERRAL_REWARD_CLAIM,
  SUBMIT_REFERRAL_REWARD_CLAIM,
} from '../apollo/mutations';
import algorandService from '../services/algorandService';
import { useAuth } from '../contexts/AuthContext';
import LoadingOverlay from '../components/LoadingOverlay';
import { EmptyState } from '../components/EmptyState';
import { InlineBanner } from '../components/common/InlineBanner';
import { colors } from '../config/theme';

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
  const navigation = useNavigation<NavigationProp<MainStackParamList>>();
  const { userProfile } = useAuth();
  const currentUserId = userProfile?.id ? String(userProfile.id) : null;
  const PAGE_SIZE = 20;
  const { data, loading, error, refetch, fetchMore } = useQuery(GET_MY_REFERRALS, {
    fetchPolicy: 'cache-and-network',
    variables: { first: PAGE_SIZE, offset: 0 },
  });
  const [prepareClaim] = useMutation(PREPARE_REFERRAL_REWARD_CLAIM);
  const [submitClaim] = useMutation(SUBMIT_REFERRAL_REWARD_CLAIM);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [banner, setBanner] = React.useState<{ message: string; variant: 'error' | 'success' } | null>(null);
  const dismissBanner = React.useCallback(() => setBanner(null), []);
  const [loadingMessage, setLoadingMessage] = React.useState<string>('');
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [hasMore, setHasMore] = React.useState(true);

  const referrals: Referral[] = data?.myReferrals || [];

  const handleLoadMore = React.useCallback(async () => {
    if (loadingMore || !hasMore || loading) return;
    setLoadingMore(true);
    try {
      const { data: moreData } = await fetchMore({
        variables: { first: PAGE_SIZE, offset: referrals.length },
        updateQuery: (prev, { fetchMoreResult }) => {
          if (!fetchMoreResult?.myReferrals?.length) return prev;
          return {
            ...prev,
            myReferrals: [...(prev.myReferrals || []), ...fetchMoreResult.myReferrals],
          };
        },
      });
      if (!moreData?.myReferrals?.length || moreData.myReferrals.length < PAGE_SIZE) {
        setHasMore(false);
      }
    } catch {
      // Silently fail — user can scroll again to retry
    } finally {
      setLoadingMore(false);
    }
  }, [loadingMore, hasMore, loading, fetchMore, referrals.length]);

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
          'ReferralActionPrompt',
          {
            event: nextEvent,
          },
        );
      } else {
        navigation.navigate(
          'ReferralFriendJoined',
          {
            event: nextEvent,
          },
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

  const handleClaim = React.useCallback(
    async (referral: Referral) => {
      if (busyId) return;
      setBusyId(referral.id);

      try {
        const eventId = referral.viewerRewardEventId || null;
        if (!eventId) {
          throw new Error('No pudimos encontrar la recompensa para este rol.');
        }
        setLoadingMessage('Desbloqueando...');
        const prepareRes = await prepareClaim({
          variables: { eventId },
        });
        const payload = prepareRes.data?.prepareReferralRewardClaim;
        if (!payload?.success) {
          throw new Error(payload?.error || 'No pudimos preparar la transacción.');
        }

        const unsigned = payload.unsignedTransaction;
        const token = payload.claimToken;

        setLoadingMessage('Firmando transacción...');
        const unsignedBytes = Buffer.from(unsigned, 'base64');
        const signedBytes = await algorandService.signTransactionBytes(
          Uint8Array.from(unsignedBytes),
        );
        const signedB64 = Buffer.from(signedBytes).toString('base64');

        setLoadingMessage('Enviando transacción...');
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

        setBanner({ variant: 'success', message: 'Tus $CONFIO fueron desbloqueados con éxito.' });
        setHasMore(true);
        await refetch({ first: PAGE_SIZE, offset: 0 });
      } catch (err: any) {
        const message =
          err?.message || 'Ocurrió un error al desbloquear la recompensa.';
        setBanner({ variant: 'error', message });
      } finally {
        setLoadingMessage('');
        setBusyId(null);
      }
    },
    [busyId, prepareClaim, submitClaim, refetch],
  );

  const renderListItem = React.useCallback(
    ({ item }: { item: ListSection }) => {
      if (item.type === 'summary') {
        return (
          <View style={styles.summaryCard}>
            <View style={styles.summaryIconRow}>
              <View style={styles.summaryIconWrap}>
                <Icon name="gift" size={20} color={colors.secondary} />
              </View>
              <Text style={styles.summaryLabel}>Listo para desbloquear</Text>
            </View>
            <Text style={styles.summaryValue}>
              {item.totalClaimable.toFixed(2)} $CONFIO
            </Text>
            <Text style={styles.summarySubtext}>
              Recompensas confirmadas on-chain. Firma para liberarlas en tu
              billetera Confío.
            </Text>
          </View>
        );
      }

      if (item.type === 'empty') {
        return (
          <EmptyState
            icon="gift"
            title="Sin recompensas pendientes"
            subtitle="Invita a un amigo y, cuando haga su primer depósito, ambos reciben $CONFIO."
            actionLabel="Invitar amigos"
            onAction={() => navigation.navigate('ConfioAddress')}
          />
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
          <View key={referral.id} style={[styles.rewardCard, styles.claimableCard]}>
            <View style={styles.rewardHeader}>
              <View style={styles.rewardHeaderText}>
                <Text style={styles.rewardTitle}>
                  {amount.toFixed(2)} $CONFIO
                </Text>
                <Text style={styles.rewardSubtitle} numberOfLines={1}>
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
                  <ActivityIndicator color={colors.white} size="small" />
                ) : (
                  <>
                    <Icon name="unlock" size={16} color={colors.white} />
                    <Text style={styles.claimButtonText}>Desbloquear</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
            <View style={styles.rewardMetaRow}>
              <View style={styles.rewardMetaItem}>
                <Icon name={isReferrer ? 'send' : 'user-check'} size={12} color={colors.textSecondary} />
                <Text style={styles.rewardMeta}>{isReferrer ? 'Invitador' : 'Referido'}</Text>
              </View>
              <View style={styles.rewardMetaItem}>
                <Icon name="calendar" size={12} color={colors.textSecondary} />
                <Text style={styles.rewardMeta}>
                  {new Date(referral.createdAt).toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' })}
                </Text>
              </View>
            </View>
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
              <View style={styles.rewardHeaderText}>
                <Text style={styles.rewardTitle}>
                  {amount.toFixed(2)} $CONFIO
                </Text>
                <Text style={styles.rewardSubtitle} numberOfLines={1}>
                  {isReferrer ? 'Invitaste a' : 'Te invitó'}{' '}
                  {otherUserDisplay}
                </Text>
              </View>
              <View style={styles.pendingBadge}>
                <Icon name="clock" size={14} color={colors.warning.icon} />
                <Text style={styles.pendingBadgeText}>Pendiente</Text>
              </View>
            </View>
            <Text style={styles.rewardRequirement}>{requirementText}</Text>
            <View style={styles.rewardMetaRow}>
              <View style={styles.rewardMetaItem}>
                <Icon name={isReferrer ? 'send' : 'user-check'} size={12} color={colors.textSecondary} />
                <Text style={styles.rewardMeta}>{isReferrer ? 'Invitador' : 'Referido'}</Text>
              </View>
              <View style={styles.rewardMetaItem}>
                <Icon name="calendar" size={12} color={colors.textSecondary} />
                <Text style={styles.rewardMeta}>
                  {new Date(referral.createdAt).toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' })}
                </Text>
              </View>
            </View>
            <View style={styles.pendingHint}>
              <Text style={styles.pendingHintText}>Ver guía</Text>
              <Icon name="chevron-right" size={16} color={colors.secondary} />
            </View>
          </TouchableOpacity>
        );
      }

      return null;
    },
    [busyId, getReferralAmount, getUserDisplayName, handleClaim, handlePendingPress, getViewerRole],
  );



  return (
    <View style={styles.container}>
      <LoadingOverlay visible={!!loadingMessage} message={loadingMessage} />
      <Header
        navigation={navigation as any}
        title="Desbloquear $CONFIO"
        backgroundColor="#fff"
        showBackButton
        onBackPress={handleBack}
      />

      {banner && (
        <InlineBanner
          message={banner.message}
          variant={banner.variant}
          onDismiss={dismissBanner}
          autoHideMs={banner.variant === 'success' ? 3000 : undefined}
          style={{ marginHorizontal: 20, marginTop: 12, marginBottom: 0 }}
        />
      )}

      {loading ? (
        <View style={styles.loadingState}>
          <ActivityIndicator size="large" color={colors.secondary} />
          <Text style={styles.loadingText}>
            Buscando recompensas disponibles...
          </Text>
        </View>
      ) : error ? (
        <EmptyState
          icon="alert-circle"
          title="No pudimos cargar tus bonos"
          subtitle="Revisa tu conexión e intenta de nuevo."
          actionLabel="Reintentar"
          onAction={() => refetch()}
        />
      ) : (
        <FlatList
          data={listData}
          renderItem={renderListItem}
          keyExtractor={keyExtractor}
          style={styles.scroll}
          contentContainerStyle={{ padding: 20, paddingBottom: 32 }}
          initialNumToRender={15}
          maxToRenderPerBatch={10}
          windowSize={21}
          onEndReached={handleLoadMore}
          onEndReachedThreshold={0.5}
          removeClippedSubviews={false}
          ListFooterComponent={
            loadingMore ? (
              <View style={styles.loadMoreFooter}>
                <ActivityIndicator size="small" color={colors.primaryDark} />
              </View>
            ) : null
          }
        />
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  loadingState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    color: colors.textSecondary,
    marginTop: 12,
  },
  scroll: {
    flex: 1,
  },
  loadMoreFooter: {
    paddingVertical: 16,
    alignItems: 'center',
  },
  // $CONFIO surface: the instrument color is violet, not the generic blue
  // accent (emerald = cUSD, violet = CONFIO — app-wide instrument grammar).
  summaryCard: {
    backgroundColor: colors.violetLight,
    borderRadius: 16,
    padding: 20,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#DDD6FE',
    shadowColor: colors.shadowBase,
    shadowOpacity: 0.05,
    shadowOffset: { width: 0, height: 6 },
    shadowRadius: 12,
    elevation: 2,
  },
  summaryIconRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  summaryIconWrap: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#DDD6FE',
    alignItems: 'center',
    justifyContent: 'center',
  },
  summaryLabel: {
    color: colors.secondary,
    fontSize: 14,
    fontWeight: '600',
  },
  summaryValue: {
    color: colors.textFlat,
    fontSize: 30,
    fontWeight: '700',
    marginVertical: 6,
  },
  summarySubtext: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
  },
  rewardCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 16,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: colors.shadowBase,
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
    gap: 12,
  },
  rewardHeaderText: {
    flex: 1,
    flexShrink: 1,
  },
  claimableCard: {
    borderLeftWidth: 3,
    borderLeftColor: colors.secondary,
  },
  pendingCard: {
    borderLeftWidth: 3,
    borderLeftColor: colors.warning.icon,
    borderColor: colors.border,
  },
  pendingSection: {
    marginTop: 24,
    marginBottom: 8,
  },
  pendingTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.textFlat,
  },
  pendingSubtitle: {
    fontSize: 14,
    color: colors.textSecondary,
    marginTop: 4,
  },
  pendingBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    backgroundColor: colors.warning.background,
  },
  pendingBadgeText: {
    marginLeft: 6,
    color: colors.warning.text,
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
    color: colors.secondary,
  },
  rewardTitle: {
    color: colors.textFlat,
    fontSize: 20,
    fontWeight: '600',
  },
  rewardSubtitle: {
    color: colors.textSecondary,
    fontSize: 13,
    marginTop: 2,
  },
  rewardMetaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
    marginTop: 8,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  rewardMetaItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  rewardMeta: {
    color: colors.textSecondary,
    fontSize: 12,
  },
  rewardRequirement: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 18,
    marginTop: 4,
  },
  claimButton: {
    backgroundColor: colors.secondary,
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: 16,
    flexDirection: 'row',
    alignItems: 'center',
  },
  claimButtonDisabled: {
    opacity: 0.5,
  },
  claimButtonText: {
    color: colors.white,
    fontWeight: '600',
    marginLeft: 6,
  },
});

export default ReferralRewardClaimScreen;
