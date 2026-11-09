import React, { useCallback, useMemo, useState } from 'react';
import { ActivityIndicator, FlatList, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { gql, useMutation, useQuery } from '@apollo/client';
import { useNavigation, NavigationProp } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import { InlineBanner } from '../components/common/InlineBanner';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';
import { formatDecimal } from '../utils/numberLocale';
import { formatSmallAmount } from '../utils/savingsFormat';
import {
  FEE_REFERRAL_SUMMARY,
  FeeReferralFriend,
  FeeReferralSummary,
  commissionPercents,
  windowRule,
} from '../hooks/useFeeReferralSummary';

/** "Mis comisiones": the referrer's own dashboard. Everything here is the
 *  member's OWN money (amounts, totals) and their friends' verification
 *  status. Never a friend's activity: payouts carry no name, transaction
 *  type or hash, and friends carry no amounts (cusd_plus/fee_referral.py). */

const PAGE = 30;

export const FEE_REFERRAL_PAYOUTS = gql`
  query FeeReferralPayouts($limit: Int, $offset: Int) {
    feeReferralPayouts(limit: $limit, offset: $offset) {
      id
      amountUsd
      paidAt
    }
  }
`;

const REMIND_FRIEND = gql`
  mutation RemindFeeReferralFriend($referralId: ID!) {
    remindFeeReferralFriend(referralId: $referralId) {
      success
      error
    }
  }
`;

type Payout = { id: string; amountUsd: string; paidAt: string };

const usd = (raw: string | number): string => `US$${formatSmallAmount(Number(raw) || 0)}`;

const when = (iso: string): string => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const today = new Date();
  const time = d.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === today.toDateString()) return `Hoy, ${time}`;
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return `Ayer, ${time}`;
  return `${d.toLocaleDateString('es', { day: 'numeric', month: 'short' })}, ${time}`;
};

const REMIND_ERRORS: Record<string, string> = {
  too_soon: 'Ya le recordaste esta semana. Podrás hacerlo de nuevo en unos días.',
  already_verified: 'Tu amigo ya verificó su identidad.',
  not_found: 'No encontramos a este amigo.',
};

const FriendGroup: React.FC<{
  title: string;
  hint?: string;
  friends: FeeReferralFriend[];
  icon: string;
  color: string;
  onRemind?: (friend: FeeReferralFriend) => void;
  reminding?: string | null;
}> = ({ title, hint, friends, icon, color, onRemind, reminding }) => {
  if (friends.length === 0) return null;
  return (
    <View style={styles.group}>
      <Text style={styles.groupTitle}>{title} · {friends.length}</Text>
      {hint ? <Text style={styles.groupHint}>{hint}</Text> : null}
      {friends.map((friend) => (
        <View key={friend.referralId} style={styles.friendRow}>
          <Icon name={icon} size={14} color={color} style={styles.friendIcon} />
          <Text style={styles.friendName} numberOfLines={1}>{friend.displayName}</Text>
          {onRemind && (
            friend.canRemind ? (
              <TouchableOpacity
                style={styles.remindButton}
                onPress={() => onRemind(friend)}
                disabled={reminding === friend.referralId}
                accessibilityRole="button"
                accessibilityLabel={`Recordarle a ${friend.displayName}`}
              >
                {reminding === friend.referralId
                  ? <ActivityIndicator size="small" color={colors.primaryDark} />
                  : <Text style={styles.remindText}>Recordarle</Text>}
              </TouchableOpacity>
            ) : (
              <Text style={styles.remindedText}>Recordado</Text>
            )
          )}
        </View>
      ))}
    </View>
  );
};

export const FeeReferralCommissionsScreen: React.FC = () => {
  const navigation = useNavigation<NavigationProp<MainStackParamList>>();
  const [banner, setBanner] = useState<{ message: string; variant: 'error' | 'success' } | null>(null);
  const [reminding, setReminding] = useState<string | null>(null);
  const [exhausted, setExhausted] = useState(false);

  const summaryQuery = useQuery(FEE_REFERRAL_SUMMARY, { fetchPolicy: 'cache-and-network', errorPolicy: 'ignore' });
  const summary: FeeReferralSummary | undefined = summaryQuery.data?.feeReferralSummary;
  const payoutsQuery = useQuery(FEE_REFERRAL_PAYOUTS, {
    variables: { limit: PAGE, offset: 0 },
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'ignore',
    notifyOnNetworkStatusChange: true,
  });
  const payouts: Payout[] = payoutsQuery.data?.feeReferralPayouts ?? [];
  const [remind] = useMutation(REMIND_FRIEND);

  // FlatList pagination (CLAUDE.md rule): fetch the next page at the end
  // until a short page says there is no more.
  const loadMore = useCallback(async () => {
    if (exhausted || payoutsQuery.loading || payouts.length < PAGE) return;
    try {
      await payoutsQuery.fetchMore({
      variables: { limit: PAGE, offset: payouts.length },
      updateQuery: (prev, { fetchMoreResult }) => {
        const next = fetchMoreResult?.feeReferralPayouts ?? [];
        if (next.length < PAGE) setExhausted(true);
        const seen = new Set((prev?.feeReferralPayouts ?? []).map((p: Payout) => p.id));
        return {
          feeReferralPayouts: [
            ...(prev?.feeReferralPayouts ?? []),
            ...next.filter((p: Payout) => !seen.has(p.id)),
          ],
        };
      },
      });
    } catch {
      // A failed page is retried on the next scroll to the end.
    }
  }, [exhausted, payoutsQuery, payouts.length]);

  const onRemind = useCallback(async (friend: FeeReferralFriend) => {
    setReminding(friend.referralId);
    try {
      const { data } = await remind({ variables: { referralId: friend.referralId } });
      const result = data?.remindFeeReferralFriend;
      if (result?.success) {
        setBanner({ variant: 'success', message: `Le enviamos un recordatorio a ${friend.displayName}.` });
        summaryQuery.refetch();
      } else {
        setBanner({ variant: 'error', message: REMIND_ERRORS[result?.error] || 'No pudimos enviar el recordatorio.' });
      }
    } catch {
      setBanner({ variant: 'error', message: 'No pudimos enviar el recordatorio.' });
    } finally {
      setReminding(null);
    }
  }, [remind, summaryQuery]);

  const groups = useMemo(() => {
    const friends = summary?.friends ?? [];
    return {
      earning: friends.filter((f) => f.status === 'earning'),
      waiting: friends.filter((f) => f.status === 'needs_friend_verification'),
      you: friends.filter((f) => f.status === 'needs_your_verification'),
      ended: friends.filter((f) => f.status === 'ended' || f.status === 'unavailable'),
    };
  }, [summary]);

  if (!summary) {
    return (
      <View style={styles.safeArea}>
        <Header navigation={navigation as any} title="Mis comisiones" showBackButton />
        <View style={styles.center}>
          {summaryQuery.loading ? <ActivityIndicator color={colors.primaryDark} /> : (
            <Text style={styles.groupHint}>No pudimos cargar tus comisiones. Inténtalo de nuevo.</Text>
          )}
        </View>
      </View>
    );
  }

  const { sharePct, volumePct, feePct } = commissionPercents(summary);

  const header = (
    <View style={styles.headerBlock}>
      {banner && (
        <InlineBanner
          message={banner.message}
          variant={banner.variant}
          onDismiss={() => setBanner(null)}
          autoHideMs={banner.variant === 'success' ? 2500 : undefined}
        />
      )}

      <View style={styles.totalsCard}>
        <Text style={styles.caption}>Ganaste este mes</Text>
        <Text style={styles.bigAmount}>{usd(summary.monthTotalUsd)}</Text>
        <Text style={styles.caption}>Total: {usd(summary.totalEarnedUsd)} · llega al instante a tu billetera</Text>
      </View>

      {!summary.viewerVerified && (
        <TouchableOpacity
          style={styles.verifyButton}
          onPress={() => navigation.navigate('Verification' as never)}
          accessibilityRole="button"
        >
          <Icon name="shield" size={16} color={colors.white} />
          <Text style={styles.verifyText}>Verifica tu identidad para empezar a ganar</Text>
        </TouchableOpacity>
      )}

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Tus invitados</Text>
        {(summary.friendCount === 0) && (
          <Text style={styles.groupHint}>Aún no tienes invitados. Comparte tu link para empezar.</Text>
        )}
        {summary.friendCount > summary.friends.length && (
          <Text style={styles.groupHint}>
            Mostramos tus {summary.friends.length} invitados más recientes de {summary.friendCount}.
          </Text>
        )}
        <FriendGroup title="Ganando" friends={groups.earning} icon="check-circle" color={colors.successText} />
        <FriendGroup
          title="Falta que verifiquen"
          hint="Cuando verifiquen su identidad empiezas a recibir tu comisión. Puedes recordarles una vez por semana."
          friends={groups.waiting}
          icon="clock"
          color={colors.warning.text}
          onRemind={onRemind}
          reminding={reminding}
        />
        <FriendGroup
          title="Esperando tu verificación"
          friends={groups.you}
          icon="alert-circle"
          color={colors.warning.text}
        />
        <FriendGroup title="Sin comisión" friends={groups.ended} icon="minus-circle" color={colors.text.secondary} />
      </View>

      <Text style={styles.sectionTitle}>Comisiones recibidas</Text>
      {payouts.length === 0 && !payoutsQuery.loading && (
        <Text style={styles.groupHint}>Cuando un invitado use Confío, verás aquí cada comisión.</Text>
      )}
    </View>
  );

  const footer = (
    <View style={styles.footer}>
      {payoutsQuery.loading && payouts.length > 0 && <ActivityIndicator color={colors.primaryDark} />}
      <Text style={styles.note}>
        Recibes el {sharePct} de la comisión de {feePct} ({volumePct} de lo que mueve) cuando un invitado recarga o
        retira dólares, invierte o envía a una billetera fuera de Confío. Empieza cuando ambos verifican su
        identidad. {windowRule(summary.windowDays)}. No aplica a envíos entre usuarios de Confío, Confío Pay ni
        Comprar. En la app no te mostramos qué hizo cada invitado. Confío puede cambiar estas condiciones.
      </Text>
    </View>
  );

  return (
    <View style={styles.safeArea}>
      <Header navigation={navigation as any} title="Mis comisiones" showBackButton />
      <FlatList
        data={payouts}
        keyExtractor={(item) => item.id}
        ListHeaderComponent={header}
        ListFooterComponent={footer}
        renderItem={({ item }) => (
          <View style={styles.payoutRow}>
            <View style={styles.payoutIcon}>
              <Icon name="gift" size={16} color={colors.offRampIcon} />
            </View>
            <View style={styles.payoutText}>
              <Text style={styles.payoutTitle}>Comisión recibida</Text>
              <Text style={styles.caption}>{when(item.paidAt)}</Text>
            </View>
            <Text style={styles.payoutAmount}>+{usd(item.amountUsd)}</Text>
          </View>
        )}
        onEndReached={loadMore}
        onEndReachedThreshold={0.4}
        initialNumToRender={20}
        maxToRenderPerBatch={10}
        windowSize={21}
        refreshing={payoutsQuery.networkStatus === 4 || summaryQuery.networkStatus === 4}
        onRefresh={() => { setExhausted(false); summaryQuery.refetch(); payoutsQuery.refetch(); }}
        contentContainerStyle={styles.content}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.neutral },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  content: { padding: 16, paddingBottom: 40 },
  headerBlock: { gap: 14, marginBottom: 6 },
  totalsCard: {
    backgroundColor: colors.white, borderRadius: 14, padding: 16, borderWidth: 1, borderColor: colors.border, gap: 2,
  },
  bigAmount: { fontSize: 30, fontWeight: '700', color: colors.text.primary, marginVertical: 2 },
  caption: { fontSize: 12, color: colors.text.secondary },
  verifyButton: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
    backgroundColor: colors.primaryDark, borderRadius: 10, paddingVertical: 12, paddingHorizontal: 14,
  },
  verifyText: { color: colors.white, fontSize: 14, fontWeight: '600' },
  section: {
    backgroundColor: colors.white, borderRadius: 14, padding: 16, borderWidth: 1, borderColor: colors.border, gap: 12,
  },
  sectionTitle: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  group: { gap: 8 },
  groupTitle: { fontSize: 13, fontWeight: '700', color: colors.text.primary },
  groupHint: { fontSize: 12, lineHeight: 17, color: colors.text.secondary },
  friendRow: { flexDirection: 'row', alignItems: 'center', minHeight: 32 },
  friendIcon: { marginRight: 10 },
  friendName: { flex: 1, fontSize: 14, color: colors.text.primary, paddingRight: 8 },
  remindButton: {
    borderWidth: 1, borderColor: colors.primaryDark, borderRadius: 16, paddingVertical: 5, paddingHorizontal: 12,
    minWidth: 96, alignItems: 'center',
  },
  remindText: { fontSize: 13, fontWeight: '600', color: colors.primaryDark },
  remindedText: { fontSize: 12, color: colors.text.secondary },
  payoutRow: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: colors.white, borderRadius: 12,
    paddingVertical: 12, paddingHorizontal: 14, marginTop: 8,
  },
  payoutIcon: {
    width: 32, height: 32, borderRadius: 16, backgroundColor: colors.neutral,
    alignItems: 'center', justifyContent: 'center', marginRight: 12,
  },
  payoutText: { flex: 1 },
  payoutTitle: { fontSize: 14, color: colors.text.primary },
  payoutAmount: { fontSize: 15, fontWeight: '700', color: colors.successText },
  footer: { marginTop: 16, gap: 12 },
  note: { fontSize: 12, lineHeight: 17, color: colors.text.secondary },
});

export default FeeReferralCommissionsScreen;
