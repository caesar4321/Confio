import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { useNavigation, NavigationProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { useQuery } from '@apollo/client';
import { Header } from '../navigation/Header';

import { GET_MY_REFERRALS, GET_REWARDS_CLAIMS_UNLOCKED } from '../apollo/queries';
import { useAuth } from '../contexts/AuthContext';
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
  // Before the launch, $CONFIO has no market and nothing is written on-chain
  // when a reward is earned: the bonus is recorded in the user's account and
  // paid out only once claims open. So this screen is a LEDGER of what the
  // user has earned, not a payout surface. Any failure to read the flag
  // (older server, no network) must read as locked — never offer a withdrawal
  // we cannot honor.
  const { data: claimsData } = useQuery(GET_REWARDS_CLAIMS_UNLOCKED, {
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
  });
  const claimsUnlocked = claimsData?.rewardsClaimsUnlocked === true;
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

  // Filter referrals by status based on current user's role. 'eligible' means
  // the bonus is EARNED and recorded — the condition was met — not that it can
  // be withdrawn today.
  const earned = referrals.filter((ref) => {
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

  const totalEarned = earned.reduce(
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
    | { type: 'summary'; totalEarned: number }
    | { type: 'empty' }
    | { type: 'earnedHeader' }
    | { type: 'earned'; referral: Referral }
    | { type: 'pendingHeader' }
    | { type: 'pending'; referral: Referral };

  const listData = React.useMemo<ListSection[]>(() => {
    const sections: ListSection[] = [];
    sections.push({ type: 'summary', totalEarned });

    if (earned.length === 0 && pendingReferrals.length === 0) {
      sections.push({ type: 'empty' });
      return sections;
    }

    if (earned.length > 0) {
      sections.push({ type: 'earnedHeader' });
      earned.forEach((referral) => {
        sections.push({ type: 'earned', referral });
      });
    }

    if (pendingReferrals.length > 0) {
      sections.push({ type: 'pendingHeader' });
      pendingReferrals.forEach((referral) => {
        sections.push({ type: 'pending', referral });
      });
    }

    return sections;
  }, [earned, pendingReferrals, totalEarned]);


  const keyExtractor = React.useCallback((item: ListSection, index: number) => {
    if (item.type === 'earned' || item.type === 'pending') {
      return `${item.type}-${item.referral.id}`;
    }
    return `${item.type}-${index}`;
  }, []);


  const renderListItem = React.useCallback(
    ({ item }: { item: ListSection }) => {
      if (item.type === 'summary') {
        return null;
      }

      if (item.type === 'empty') {
        return (
          <EmptyState
            icon="gift"
            title="Aún no tienes bonos"
            subtitle="Invita a un amigo y, cuando haga su primer depósito, ambos ganan $CONFIO."
            actionLabel="Invitar amigos"
            onAction={() => navigation.navigate('ConfioAddress')}
          />
        );
      }

      if (item.type === 'earnedHeader') {
        return (
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Bonos ganados</Text>
            <Text style={styles.sectionSubtitle}>
              Ya son tuyos y están guardados en tu cuenta.
            </Text>
          </View>
        );
      }

      if (item.type === 'pendingHeader') {
        return (
          <View style={[styles.sectionHeader, styles.sectionHeaderSpaced]}>
            <Text style={styles.sectionTitle}>Bonos en progreso</Text>
            <Text style={styles.sectionSubtitle}>
              Completa tu primera recarga o ahorro de US$20 para ganar estos bonos.
            </Text>
          </View>
        );
      }

      if (item.type === 'earned') {
        const referral = item.referral;
        const amount = getReferralAmount(referral);
        const isReferrer = getViewerRole(referral) === 'referrer';
        const otherUser = isReferrer ? referral.referredUser : referral.referrerUser;

        return (
          <View key={referral.id} style={styles.rewardCard}>
            <View style={styles.rewardHeader}>
              <View style={styles.rewardIconWrap}>
                <Icon name="gift" size={18} color={colors.secondary} />
              </View>
              <View style={styles.rewardHeaderText}>
                <Text style={styles.rewardTitle}>
                  {amount.toFixed(2)} $CONFIO
                </Text>
                <Text style={styles.rewardSubtitle} numberOfLines={1}>
                  {isReferrer ? 'Invitaste a' : 'Te invitó'}{' '}
                  {getUserDisplayName(otherUser)}
                </Text>
              </View>
              <View style={styles.earnedBadge}>
                <Icon name="check" size={14} color={colors.secondary} />
                <Text style={styles.earnedBadgeText}>Ganado</Text>
              </View>
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
          ? `Ayuda a ${otherUserDisplay} a completar su primera recarga o ahorro de US$20 para ganar el bono los dos.`
          : 'Completa tu primera recarga o ahorro de al menos US$20 para ganar el bono.';

        return (
          <TouchableOpacity
            key={`pending-${referral.id}`}
            style={styles.rewardCard}
            activeOpacity={0.85}
            onPress={() => handlePendingPress(referral)}>
            <View style={styles.rewardHeader}>
              <View style={[styles.rewardIconWrap, { backgroundColor: colors.warning.background }]}>
                <Icon name="clock" size={18} color={colors.warning.icon} />
              </View>
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
    [getReferralAmount, getUserDisplayName, handlePendingPress, getViewerRole],
  );



  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Tus bonos $CONFIO"
        backgroundColor={colors.secondary}
        isLight
        showBackButton
        onBackPress={handleBack}
      />

      {/* Violet brand field: fixed above the list so the total stays visible
          while scrolling. Same gradient + coin-ring grammar as the Programa
          de referidos hero; padding on fieldInner (Yoga absolute-child rule). */}
      <View style={styles.brandField}>
        <Svg style={StyleSheet.absoluteFill}>
          <Defs>
            <SvgLinearGradient id="claimField" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={colors.secondary} />
              <Stop offset="1" stopColor={colors.secondaryDark} />
            </SvgLinearGradient>
          </Defs>
          <Rect width="100%" height="100%" fill="url(#claimField)" />
          <Circle cx="104%" cy="30%" r="80" stroke={colors.white} strokeWidth="20" strokeOpacity="0.10" fill="none" />
        </Svg>
        <View style={styles.fieldInner}>
          <Text style={styles.fieldLabel}>GANADO EN BONOS</Text>
          <Text style={styles.fieldValue}>{totalEarned.toFixed(2)} $CONFIO</Text>
          <Text style={styles.fieldSubtext}>
            Guardados en tu cuenta. Se podrán retirar cuando $CONFIO se lance al
            mercado.
          </Text>
        </View>
      </View>

      {/* Claims opened while this build is installed: the withdrawal itself
          ships in a newer version, so point there instead of leaving the
          screen silently unchanged. */}
      {claimsUnlocked && (
        <InlineBanner
          message="El retiro de $CONFIO ya está disponible. Actualiza la app para retirar tus bonos."
          variant="success"
          style={{ marginHorizontal: 20, marginTop: 12, marginBottom: 0 }}
        />
      )}

      {loading ? (
        <View style={styles.loadingState}>
          <ActivityIndicator size="large" color={colors.secondary} />
          <Text style={styles.loadingText}>
            Buscando tus bonos...
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
  brandField: {
    backgroundColor: colors.secondary,
    overflow: 'hidden',
  },
  fieldInner: {
    paddingHorizontal: 20,
    paddingTop: 18,
    paddingBottom: 22,
  },
  fieldLabel: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 2,
    color: colors.violetLight,
    marginBottom: 6,
  },
  fieldValue: {
    fontSize: 32,
    fontWeight: '800',
    color: colors.white,
  },
  fieldSubtext: {
    fontSize: 13,
    lineHeight: 19,
    color: 'rgba(255, 255, 255, 0.85)',
    marginTop: 6,
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
  rewardIconWrap: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: colors.violetLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sectionHeader: {
    marginBottom: 12,
  },
  sectionHeaderSpaced: {
    marginTop: 16,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.textFlat,
  },
  sectionSubtitle: {
    fontSize: 14,
    color: colors.textSecondary,
    marginTop: 4,
  },
  earnedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    backgroundColor: colors.violetLight,
  },
  earnedBadgeText: {
    marginLeft: 6,
    color: colors.secondaryText,
    fontWeight: '600',
    fontSize: 13,
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
});

export default ReferralRewardClaimScreen;
