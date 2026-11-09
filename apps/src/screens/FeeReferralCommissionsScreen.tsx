import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Linking,
  Share,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, LinearGradient as SvgLinearGradient, Rect, Stop, Circle } from 'react-native-svg';
import { gql, useMutation, useQuery } from '@apollo/client';
import { useNavigation, NavigationProp } from '@react-navigation/native';
import { Text } from '../components/common/AppText';
import { InlineBanner } from '../components/common/InlineBanner';
import { Header } from '../navigation/Header';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';
import { formatDecimal } from '../utils/numberLocale';
import { formatSmallAmount } from '../utils/savingsFormat';
import { buildReferralShareMessage, normalizeInviteUsername } from '../utils/inviteLinks';
import { useAuth } from '../contexts/AuthContext';
import { AnalyticsService } from '../services/analyticsService';
import WhatsAppLogo from '../assets/svg/WhatsApp.svg';
import {
  DEFAULT_TERMS,
  FeeReferralFriend,
  commissionPercents,
  windowRule,
} from '../hooks/useFeeReferralSummary';

/** "Mis comisiones": the referrer's own dashboard. Everything here is the
 *  member's OWN money (amounts, totals, months) and their invitations'
 *  verification status. Never a friend's activity: payouts carry no name,
 *  operation or hash, and invitations carry no amounts
 *  (cusd_plus/fee_referral.py). Every invitation is reachable: the list is
 *  searched and paged on the server, never capped. */

const PAGE = 30;

const DASHBOARD = gql`
  query FeeReferralDashboard {
    feeReferralSummary {
      shareBps
      feeBps
      windowDays
      viewerVerified
      monthTotalUsd
      totalEarnedUsd
      today
      friendCount
      waitingCount
      earningCount
      noCommissionCount
      monthly {
        month
        amountUsd
      }
    }
  }
`;

const PAYOUTS = gql`
  query FeeReferralPayouts($limit: Int, $offset: Int, $month: String) {
    feeReferralPayouts(limit: $limit, offset: $offset, month: $month) {
      id
      amountUsd
      paidAt
      localDate
      localTime
    }
  }
`;

const FRIENDS = gql`
  query FeeReferralFriends($group: String, $search: String, $limit: Int, $offset: Int) {
    feeReferralFriends(group: $group, search: $search, limit: $limit, offset: $offset) {
      totalCount
      friends {
        referralId
        displayName
        status
        endsAt
        canRemind
      }
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

type Tab = 'payouts' | 'friends';
type Group = '' | 'earning' | 'waiting' | 'none';
type Payout = { id: string; amountUsd: string; paidAt: string; localDate: string; localTime: string };
type Row =
  | { kind: 'day'; key: string; label: string; total: number }
  | { kind: 'payout'; key: string; payout: Payout }
  | { kind: 'friend'; key: string; friend: FeeReferralFriend };

const MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const MONTHS_FULL = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre',
  'octubre', 'noviembre', 'diciembre'];
const monthName = (key: string): string => MONTHS_FULL[Number(key.split('-')[1]) - 1] ?? '';

const usd = (value: number | string): string => `US$${formatSmallAmount(Number(value) || 0)}`;

/** Day labels from the server's local dates (the member's own time zone,
 *  the same zone as the month bars), never the phone's clock. */
const shiftDay = (ymd: string, days: number): string => {
  const [y, m, d] = ymd.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, '0')}-${String(dt.getUTCDate()).padStart(2, '0')}`;
};

const dayLabel = (localDate: string, today: string): string => {
  if (today && localDate === today) return 'Hoy';
  if (today && localDate === shiftDay(today, -1)) return 'Ayer';
  const [y, m, d] = localDate.split('-').map(Number);
  const sameYear = today ? Number(today.slice(0, 4)) === y : true;
  return `${d} de ${MONTHS[m - 1] ?? ''}${sameYear ? '' : ` ${y}`}`;
};

const endsLabel = (iso?: string | null): string => {
  if (!iso) return '';
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
};

const FRIEND_STYLE: Record<string, { label: string; color: string; bg: string }> = {
  earning: { label: 'Ganando', color: colors.successText, bg: colors.primaryLight },
  needs_friend_verification: { label: 'Falta que verifique', color: colors.warning.text, bg: '#FEF3C7' },
  needs_your_verification: { label: 'Falta tu verificación', color: colors.warning.text, bg: '#FEF3C7' },
  ended: { label: 'Terminó su año', color: colors.text.secondary, bg: colors.neutralDark },
  unavailable: { label: 'Sin comisión', color: colors.text.secondary, bg: colors.neutralDark },
};

const REMIND_ERRORS: Record<string, string> = {
  too_soon: 'Ya le recordaste esta semana. Podrás hacerlo de nuevo en unos días.',
  already_verified: 'Tu invitado ya verificó su identidad.',
  not_allowed: 'Este invitado no puede generar comisión ahora.',
  not_found: 'No encontramos a este invitado.',
};

/** Last six months as bars. The month on show is solid, the rest faded;
 *  tapping a month shows its total and filters the list to it, tapping it
 *  again goes back to this month and the full history. */
const MonthBars: React.FC<{
  monthly: { month: string; amountUsd: string }[];
  selected: string;
  onSelect: (month: string) => void;
}> = ({ monthly, selected, onSelect }) => {
  const values = monthly.map((m) => Number(m.amountUsd) || 0);
  const max = Math.max(...values, 0);
  return (
    <View style={styles.bars}>
      {monthly.map((m, i) => {
        const value = values[i];
        const height = max > 0 ? Math.max(4, Math.round((value / max) * 44)) : 4;
        const active = m.month === selected;
        const monthIndex = Number(m.month.split('-')[1]) - 1;
        return (
          <TouchableOpacity
            key={m.month}
            style={styles.barColumn}
            onPress={() => onSelect(m.month)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            accessibilityLabel={`${monthName(m.month)}: ${usd(value)}`}
            hitSlop={{ top: 8, bottom: 8 }}
          >
            <View style={styles.barTrack}>
              <View style={[styles.bar, { height, opacity: active ? 1 : 0.4 }]} />
            </View>
            <Text style={[styles.barLabel, active && styles.barLabelCurrent]}>{MONTHS[monthIndex] ?? ''}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
};

export const FeeReferralCommissionsScreen: React.FC = () => {
  const navigation = useNavigation<NavigationProp<MainStackParamList>>();
  const { userProfile } = useAuth();
  const [tab, setTab] = useState<Tab>('payouts');
  const [group, setGroup] = useState<Group>('');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [showRules, setShowRules] = useState(false);
  const [banner, setBanner] = useState<{ message: string; variant: 'error' | 'success' } | null>(null);
  const [reminding, setReminding] = useState<string | null>(null);
  const [payoutsDone, setPayoutsDone] = useState(false);
  const [friendsDone, setFriendsDone] = useState(false);
  const [fieldSize, setFieldSize] = useState({ width: 0, height: 0 });
  // '' = this month in the hero and the full history in the list.
  const [selectedMonth, setSelectedMonth] = useState('');

  const dashboard = useQuery(DASHBOARD, { fetchPolicy: 'cache-and-network', errorPolicy: 'ignore' });
  const summary = dashboard.data?.feeReferralSummary;
  const terms = summary ?? DEFAULT_TERMS;
  const { sharePct, volumePct, feePct } = commissionPercents(terms);

  const payoutsQuery = useQuery(PAYOUTS, {
    variables: { limit: PAGE, offset: 0, month: selectedMonth },
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'ignore',
    notifyOnNetworkStatusChange: true,
  });
  const payouts: Payout[] = payoutsQuery.data?.feeReferralPayouts ?? [];

  const friendsQuery = useQuery(FRIENDS, {
    variables: { group, search, limit: PAGE, offset: 0 },
    skip: tab !== 'friends',
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'ignore',
    notifyOnNetworkStatusChange: true,
  });
  const friendsPage = friendsQuery.data?.feeReferralFriends;
  const friends: FeeReferralFriend[] = friendsPage?.friends ?? [];
  const friendsTotal: number = friendsPage?.totalCount ?? 0;

  const [remind] = useMutation(REMIND_FRIEND);

  // Debounced server search: every invitation is findable by @usuario.
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => setSearch(searchInput.trim()), 350);
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current); };
  }, [searchInput]);
  useEffect(() => { setFriendsDone(false); }, [group, search]);
  useEffect(() => { setPayoutsDone(false); }, [selectedMonth]);
  const payoutMonth = useRef(selectedMonth);
  payoutMonth.current = selectedMonth;

  const monthly: { month: string; amountUsd: string }[] = summary?.monthly ?? [];
  const currentMonth = monthly.length ? monthly[monthly.length - 1].month : '';
  const shownMonth = selectedMonth || currentMonth;
  const shownMonthEntry = monthly.find((m) => m.month === selectedMonth);
  useEffect(() => {
    if (selectedMonth && monthly.length && !monthly.some((m) => m.month === selectedMonth)) setSelectedMonth('');
  }, [selectedMonth, monthly]);
  const selectMonth = useCallback((month: string) => {
    // The current month (or the one already selected) goes back to the
    // default view: this month on top, full history below.
    setSelectedMonth((prev) => (month === prev || month === currentMonth ? '' : month));
    setTab('payouts');
  }, [currentMonth]);
  // The filters a friends page was requested with; a page that resolves after
  // the member changed chip or search is dropped (Apollo would write it into
  // the CURRENT variables' list).
  const friendFilters = useRef({ group, search });
  friendFilters.current = { group, search };

  const share = useCallback(async () => {
    const message = buildReferralShareMessage(userProfile?.username);
    try {
      AnalyticsService.logFunnelEvent('referral_whatsapp_share_tapped', {
        surface: 'commissions',
        referral_code: normalizeInviteUsername(userProfile?.username),
      }, { sourceType: 'referral_link', channel: 'whatsapp' });
    } catch {
      // never block sharing
    }
    const encoded = encodeURIComponent(message);
    try {
      const scheme = `whatsapp://send?text=${encoded}`;
      await Linking.openURL((await Linking.canOpenURL(scheme)) ? scheme : `https://wa.me/?text=${encoded}`);
    } catch {
      Share.share({ message, title: 'Invitación Confío' }).catch(() => {});
    }
  }, [userProfile?.username]);

  const onRemind = useCallback(async (friend: FeeReferralFriend) => {
    setReminding(friend.referralId);
    try {
      const { data } = await remind({ variables: { referralId: friend.referralId } });
      const result = data?.remindFeeReferralFriend;
      if (result?.success) {
        setBanner({ variant: 'success', message: `Le enviamos un recordatorio a ${friend.displayName}.` });
        // The refetch returns the first page only: let paging continue past it.
        setFriendsDone(false);
        friendsQuery.refetch();
      } else {
        setBanner({ variant: 'error', message: REMIND_ERRORS[result?.error] || 'No pudimos enviar el recordatorio.' });
      }
    } catch {
      setBanner({ variant: 'error', message: 'No pudimos enviar el recordatorio.' });
    } finally {
      setReminding(null);
    }
  }, [remind, friendsQuery]);

  // FlatList pagination (CLAUDE.md): the next page at the end of the active tab.
  const loadMore = useCallback(async () => {
    try {
      if (tab === 'payouts') {
        if (payoutsDone || payoutsQuery.loading || payouts.length < PAGE) return;
        const requestedMonth = selectedMonth;
        await payoutsQuery.fetchMore({
          variables: { limit: PAGE, offset: payouts.length, month: selectedMonth },
          updateQuery: (prev, { fetchMoreResult }) => {
            if (payoutMonth.current !== requestedMonth) return prev;  // month changed meanwhile
            const next: Payout[] = fetchMoreResult?.feeReferralPayouts ?? [];
            if (next.length < PAGE) setPayoutsDone(true);
            const seen = new Set((prev?.feeReferralPayouts ?? []).map((p: Payout) => p.id));
            return { feeReferralPayouts: [...(prev?.feeReferralPayouts ?? []), ...next.filter((p) => !seen.has(p.id))] };
          },
        });
      } else {
        if (friendsDone || friendsQuery.loading || friends.length >= friendsTotal) return;
        const requested = { group, search };
        await friendsQuery.fetchMore({
          variables: { group, search, limit: PAGE, offset: friends.length },
          updateQuery: (prev, { fetchMoreResult }) => {
            const current = friendFilters.current;
            if (current.group !== requested.group || current.search !== requested.search) return prev;
            const next: FeeReferralFriend[] = fetchMoreResult?.feeReferralFriends?.friends ?? [];
            if (next.length < PAGE) setFriendsDone(true);
            const prevPage = prev?.feeReferralFriends;
            const seen = new Set((prevPage?.friends ?? []).map((f: FeeReferralFriend) => f.referralId));
            return {
              feeReferralFriends: {
                ...(fetchMoreResult?.feeReferralFriends ?? prevPage),
                friends: [...(prevPage?.friends ?? []), ...next.filter((f) => !seen.has(f.referralId))],
              },
            };
          },
        });
      }
    } catch {
      // a failed page is retried on the next scroll to the end
    }
  }, [tab, payoutsDone, payoutsQuery, payouts.length, selectedMonth, friendsDone, friendsQuery, friends.length, friendsTotal, group, search]);

  const refresh = useCallback(() => {
    setPayoutsDone(false);
    setFriendsDone(false);
    dashboard.refetch();
    if (tab === 'payouts') payoutsQuery.refetch();
    else friendsQuery.refetch();
  }, [dashboard, tab, payoutsQuery, friendsQuery]);

  const rows: Row[] = useMemo(() => {
    if (tab === 'friends') {
      return friends.map((friend) => ({ kind: 'friend' as const, key: `f-${friend.referralId}`, friend }));
    }
    const out: Row[] = [];
    const today: string = summary?.today ?? '';
    const totals = new Map<string, number>();
    payouts.forEach((p) => totals.set(p.localDate, (totals.get(p.localDate) ?? 0) + (Number(p.amountUsd) || 0)));
    let lastDay = '';
    payouts.forEach((p) => {
      const key = p.localDate;
      if (key !== lastDay) {
        out.push({ kind: 'day', key: `d-${key}`, label: dayLabel(key, today), total: totals.get(key) ?? 0 });
        lastDay = key;
      }
      out.push({ kind: 'payout', key: `p-${p.id}`, payout: p });
    });
    return out;
  }, [tab, friends, payouts, summary?.today]);

  const selectGroup = (next: Group) => {
    setTab('friends');
    setGroup(next);
  };

  const header = (
    <View>
      {/* Hero field, Profile's grammar: house heroField gradient continuing
          the header, coin ring fully inside the field (measured size, keyed
          so the SVG redraws), the member's own money as the big number. */}
      <View
        style={styles.hero}
        onLayout={(e) => {
          const { width, height } = e.nativeEvent.layout;
          setFieldSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
        }}
      >
        <Svg
          key={`commissionsField-${fieldSize.width}x${fieldSize.height}`}
          width={fieldSize.width || '100%'}
          height={fieldSize.height || '100%'}
          style={StyleSheet.absoluteFill}
        >
          <Defs>
            <SvgLinearGradient id="commissionsField" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={colors.heroField} />
              <Stop offset="1" stopColor={colors.heroFieldDark} />
            </SvgLinearGradient>
          </Defs>
          <Rect width="100%" height="100%" fill="url(#commissionsField)" />
          <Circle cx="104%" cy="34%" r="90" stroke={colors.white} strokeWidth="22" strokeOpacity="0.10" fill="none" />
        </Svg>
        <View style={styles.heroInner}>
          <Text style={styles.heroEyebrow}>
            {selectedMonth ? `GANASTE EN ${monthName(selectedMonth).toUpperCase()}` : 'GANASTE ESTE MES'}
          </Text>
          {summary ? (
            <Text style={styles.heroAmount}>
              {selectedMonth
                ? (shownMonthEntry ? usd(shownMonthEntry.amountUsd) : '—')
                : usd(summary.monthTotalUsd)}
            </Text>
          ) : dashboard.loading ? (
            <ActivityIndicator color={colors.white} style={styles.heroLoading} />
          ) : (
            <Text style={styles.heroAmount}>—</Text>
          )}
          <Text style={styles.heroSub}>
            {summary ? `Total ganado ${usd(summary.totalEarnedUsd)} · ` : ''}Tu {sharePct} de cada comisión, al instante en dólares
          </Text>
          {monthly.length ? (
            <>
              <MonthBars monthly={monthly} selected={shownMonth} onSelect={selectMonth} />
              <Text style={styles.barsHint}>
                {selectedMonth ? 'Toca otra vez el mes para volver a este mes' : 'Toca un mes para ver sus comisiones'}
              </Text>
            </>
          ) : null}
        </View>
      </View>

      <View style={styles.body}>
        <View style={styles.statsRow}>
          {[
            { key: '' as Group, value: summary?.friendCount, label: 'Invitados', color: colors.text.primary },
            { key: 'earning' as Group, value: summary?.earningCount, label: 'Ganando', color: colors.successText },
            { key: 'waiting' as Group, value: summary?.waitingCount, label: 'Por verificar', color: colors.warning.text },
          ].map((stat) => (
            <TouchableOpacity
              key={stat.label}
              style={[styles.stat, tab === 'friends' && group === stat.key && styles.statActive]}
              onPress={() => selectGroup(stat.key)}
              accessibilityRole="button"
              accessibilityLabel={`${stat.label}: ${stat.value ?? 0}`}
            >
              <Text style={[styles.statValue, { color: stat.color }]}>
                {stat.value === undefined ? '—' : formatDecimal(stat.value, { decimals: 0 })}
              </Text>
              <Text style={styles.statLabel}>{stat.label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {banner && (
          <InlineBanner
            message={banner.message}
            variant={banner.variant}
            onDismiss={() => setBanner(null)}
            autoHideMs={banner.variant === 'success' ? 2500 : undefined}
          />
        )}

        {summary && !summary.viewerVerified && (
          <TouchableOpacity
            style={styles.verifyCard}
            onPress={() => navigation.navigate('Verification' as never)}
            accessibilityRole="button"
          >
            <Icon name="shield" size={20} color={colors.warning.text} />
            <View style={styles.flex}>
              <Text style={styles.verifyTitle}>Verifica tu identidad para empezar a ganar</Text>
              <Text style={styles.verifyText}>Sin tu verificación, tus invitados no generan comisión.</Text>
            </View>
            <Icon name="chevron-right" size={18} color={colors.warning.text} />
          </TouchableOpacity>
        )}

        {summary && summary.waitingCount > 0 && summary.viewerVerified && (
          <TouchableOpacity style={styles.nudgeCard} onPress={() => selectGroup('waiting')} accessibilityRole="button">
            <Icon name="bell" size={18} color={colors.secondary} />
            <Text style={styles.nudgeText}>
              {summary.waitingCount === 1
                ? '1 invitado aún no verifica su identidad. Recuérdale para empezar a ganar.'
                : `${formatDecimal(summary.waitingCount, { decimals: 0 })} invitados aún no verifican su identidad. Recuérdales para empezar a ganar.`}
            </Text>
            <Icon name="chevron-right" size={18} color={colors.secondary} />
          </TouchableOpacity>
        )}

        <TouchableOpacity style={styles.shareButton} onPress={share} accessibilityRole="button">
          <WhatsAppLogo width={20} height={20} />
          <Text style={styles.shareText}>Invitar por WhatsApp</Text>
        </TouchableOpacity>

        <View style={styles.tabs}>
          {([['payouts', 'Comisiones'], ['friends', 'Invitados']] as [Tab, string][]).map(([key, label]) => (
            <TouchableOpacity
              key={key}
              style={[styles.tab, tab === key && styles.tabActive]}
              onPress={() => setTab(key)}
              accessibilityRole="tab"
              accessibilityState={{ selected: tab === key }}
            >
              <Text style={[styles.tabText, tab === key && styles.tabTextActive]}>{label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {tab === 'payouts' && selectedMonth !== '' && (
          <TouchableOpacity
            style={styles.monthFilter}
            onPress={() => setSelectedMonth('')}
            accessibilityRole="button"
            accessibilityLabel="Ver todas las comisiones"
          >
            <Icon name="calendar" size={14} color={colors.text.primary} />
            <Text style={styles.monthFilterText}>
              Comisiones de {monthName(selectedMonth)} · {usd(shownMonthEntry?.amountUsd ?? 0)}
            </Text>
            <Icon name="x" size={14} color={colors.text.secondary} />
          </TouchableOpacity>
        )}

        {tab === 'friends' && (
          <View style={styles.friendTools}>
            <View style={styles.searchBox}>
              <Icon name="search" size={16} color={colors.text.secondary} />
              <TextInput
                style={styles.searchInput}
                value={searchInput}
                onChangeText={setSearchInput}
                placeholder="Buscar @usuario"
                placeholderTextColor={colors.text.secondary}
                autoCapitalize="none"
                autoCorrect={false}
              />
              {searchInput.length > 0 && (
                <TouchableOpacity onPress={() => setSearchInput('')} accessibilityLabel="Borrar búsqueda">
                  <Icon name="x" size={16} color={colors.text.secondary} />
                </TouchableOpacity>
              )}
            </View>
            <View style={styles.chips}>
              {([
                ['', 'Todos', summary?.friendCount],
                ['earning', 'Ganando', summary?.earningCount],
                ['waiting', 'Por verificar', summary?.waitingCount],
                ['none', 'Sin comisión', summary?.noCommissionCount],
              ] as [Group, string, number | undefined][]).map(([key, label, count]) => (
                <TouchableOpacity
                  key={label}
                  style={[styles.chip, group === key && styles.chipActive]}
                  onPress={() => setGroup(key)}
                  accessibilityRole="button"
                >
                  <Text style={[styles.chipText, group === key && styles.chipTextActive]}>
                    {label}{count !== undefined ? ` ${formatDecimal(count, { decimals: 0 })}` : ''}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
            {search.length > 0 && !friendsQuery.loading && (
              <Text style={styles.resultsText}>
                {friendsTotal === 1 ? '1 resultado' : `${formatDecimal(friendsTotal, { decimals: 0 })} resultados`}
              </Text>
            )}
          </View>
        )}
      </View>
    </View>
  );

  const empty = (
    <View style={styles.empty}>
      {(tab === 'payouts' ? payoutsQuery.loading : friendsQuery.loading) ? (
        <ActivityIndicator color={colors.primaryDark} />
      ) : tab === 'payouts' ? (
        <>
          <View style={styles.emptyIcon}><Icon name="dollar-sign" size={22} color={colors.primaryDark} /></View>
          <Text style={styles.emptyTitle}>
            {selectedMonth ? `Sin comisiones en ${monthName(selectedMonth)}` : 'Aún no recibes comisiones'}
          </Text>
          <Text style={styles.emptyText}>
            {selectedMonth
              ? 'Toca otro mes o vuelve a ver todas tus comisiones.'
              : 'Cuando un invitado recargue, retire o invierta, verás aquí cada comisión en el momento en que llega.'}
          </Text>
        </>
      ) : (
        <>
          <View style={styles.emptyIcon}><Icon name="users" size={22} color={colors.primaryDark} /></View>
          <Text style={styles.emptyTitle}>{search ? 'Sin resultados' : 'Aún no hay invitados aquí'}</Text>
          <Text style={styles.emptyText}>
            {search ? `No encontramos a "${search}" entre tus invitados.` : 'Comparte tu link para invitar a quienes confías.'}
          </Text>
        </>
      )}
    </View>
  );

  const footer = (
    <View style={styles.footer}>
      {(tab === 'payouts' ? payoutsQuery.loading : friendsQuery.loading) && rows.length > 0 && (
        <ActivityIndicator color={colors.primaryDark} style={styles.footerSpinner} />
      )}
      <TouchableOpacity
        style={styles.rulesHeader}
        onPress={() => setShowRules((v) => !v)}
        accessibilityRole="button"
        accessibilityState={{ expanded: showRules }}
      >
        <Icon name="info" size={16} color={colors.text.secondary} />
        <Text style={styles.rulesTitle}>Cómo funciona</Text>
        <Icon name={showRules ? 'chevron-up' : 'chevron-down'} size={16} color={colors.text.secondary} />
      </TouchableOpacity>
      {showRules && (
        <View style={styles.rules}>
          <Text style={styles.ruleItem}>
            • Cuando un invitado recarga o retira dólares, invierte (acciones, oro, Bitcoin o Futuros) o envía a una
            billetera fuera de Confío, paga una comisión de {feePct}. Tú recibes el {sharePct} ({volumePct} de lo que mueve), en dólares y al instante.
          </Text>
          <Text style={styles.ruleItem}>• Empieza cuando tú y tu invitado verifican su identidad. Lo movido antes no cuenta.</Text>
          <Text style={styles.ruleItem}>• {windowRule(terms.windowDays)}.</Text>
          <Text style={styles.ruleItem}>• No aplica a envíos entre usuarios de Confío, Confío Pay ni Comprar.</Text>
          <Text style={styles.ruleItem}>
            • Ejemplo: si tus invitados recargan, retiran o invierten US${formatDecimal(1000, { decimals: 0 })} en un mes,
            recibes US${formatDecimal((1000 * terms.feeBps * terms.shareBps) / 100_000_000, { decimals: 2 })}.
          </Text>
          <Text style={styles.ruleItem}>
            • En la app no te mostramos qué hizo cada invitado. Confío puede cambiar estas condiciones.
          </Text>
        </View>
      )}
    </View>
  );

  const renderRow = ({ item }: { item: Row }) => {
    if (item.kind === 'day') {
      return (
        <View style={styles.dayHeader}>
          <Text style={styles.dayLabel}>{item.label}</Text>
          <Text style={styles.dayTotal}>+{usd(item.total)}</Text>
        </View>
      );
    }
    if (item.kind === 'payout') {
      return (
        <View style={styles.payoutRow}>
          <View style={styles.payoutIcon}><Icon name="arrow-down-left" size={16} color={colors.successText} /></View>
          <View style={styles.flex}>
            <Text style={styles.rowTitle}>Comisión recibida</Text>
            <Text style={styles.rowSub}>{item.payout.localTime}</Text>
          </View>
          <Text style={styles.payoutAmount}>+{usd(item.payout.amountUsd)}</Text>
        </View>
      );
    }
    const friend = item.friend;
    const look = FRIEND_STYLE[friend.status] ?? FRIEND_STYLE.unavailable;
    const initial = friend.displayName.replace(/^@/, '').charAt(0).toUpperCase() || '?';
    return (
      <View style={styles.friendRow}>
        <View style={[styles.avatar, { backgroundColor: look.bg }]}>
          <Text style={[styles.avatarText, { color: look.color }]}>{initial}</Text>
        </View>
        <View style={styles.flex}>
          <Text style={styles.rowTitle} numberOfLines={1}>{friend.displayName}</Text>
          <Text style={[styles.rowSub, { color: look.color }]} numberOfLines={1}>
            {look.label}
            {friend.status === 'earning' && friend.endsAt ? ` · hasta el ${endsLabel(friend.endsAt)}` : ''}
          </Text>
        </View>
        {friend.status === 'needs_friend_verification' && (
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
    );
  };

  return (
    <View style={styles.safeArea}>
      <Header navigation={navigation as any} title="Mis comisiones" backgroundColor={colors.heroField} isLight showBackButton />
      <FlatList
        data={rows}
        keyExtractor={(row) => row.key}
        renderItem={renderRow}
        ListHeaderComponent={header}
        ListEmptyComponent={empty}
        ListFooterComponent={footer}
        onEndReached={loadMore}
        onEndReachedThreshold={0.4}
        initialNumToRender={20}
        maxToRenderPerBatch={10}
        windowSize={21}
        refreshing={dashboard.networkStatus === 4}
        onRefresh={refresh}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={styles.content}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.neutral },
  content: { paddingBottom: 40 },
  flex: { flex: 1 },
  // The stat cards overlap the field by 20px; 60px of bottom padding keeps
  // the last line of the field 40px clear of them.
  hero: { overflow: 'hidden', paddingBottom: 60 },
  heroInner: { paddingHorizontal: 20, paddingTop: 16 },
  heroEyebrow: { color: colors.white, opacity: 0.9, fontSize: 12, fontWeight: '700', letterSpacing: 1 },
  heroAmount: { color: colors.white, fontSize: 40, fontWeight: '800', marginTop: 6 },
  heroLoading: { alignSelf: 'flex-start', marginVertical: 14 },
  heroSub: { color: colors.white, opacity: 0.95, fontSize: 13, marginTop: 8, lineHeight: 19 },
  bars: { flexDirection: 'row', alignItems: 'flex-end', marginTop: 18, gap: 10 },
  barColumn: { flex: 1, alignItems: 'center' },
  barTrack: { height: 44, justifyContent: 'flex-end', width: '100%', alignItems: 'center' },
  bar: { width: '70%', borderRadius: 4, backgroundColor: colors.white },
  barLabel: { color: colors.white, opacity: 0.7, fontSize: 11, marginTop: 6 },
  barLabelCurrent: { opacity: 1, fontWeight: '700' },
  barsHint: { color: colors.white, opacity: 0.8, fontSize: 11, marginTop: 8 },
  monthFilter: {
    flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-start', backgroundColor: colors.white,
    borderRadius: 16, borderWidth: 1, borderColor: colors.border, paddingVertical: 7, paddingHorizontal: 12,
  },
  monthFilterText: { fontSize: 13, fontWeight: '600', color: colors.text.primary },
  body: { paddingHorizontal: 16, marginTop: -20, gap: 12 },
  statsRow: { flexDirection: 'row', gap: 10 },
  stat: {
    flex: 1, backgroundColor: colors.white, borderRadius: 14, paddingVertical: 14, alignItems: 'center',
    borderWidth: 1, borderColor: colors.border, shadowColor: '#000', shadowOpacity: 0.06, shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 }, elevation: 2,
  },
  statActive: { borderColor: colors.primaryDark, borderWidth: 2 },
  statValue: { fontSize: 22, fontWeight: '800' },
  statLabel: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  verifyCard: {
    flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: '#FFFBEB', borderRadius: 14,
    borderWidth: 1, borderColor: colors.warning.border, padding: 14,
  },
  verifyTitle: { fontSize: 14, fontWeight: '700', color: colors.warning.text },
  verifyText: { fontSize: 12, color: colors.warning.text, marginTop: 2 },
  nudgeCard: {
    flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#F5F3FF', borderRadius: 14,
    borderWidth: 1, borderColor: '#DDD6FE', padding: 14,
  },
  nudgeText: { flex: 1, fontSize: 13, lineHeight: 18, color: colors.secondaryDark },
  shareButton: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: '#25D366',
    borderRadius: 14, paddingVertical: 14,
  },
  shareText: { color: colors.white, fontSize: 15, fontWeight: '700' },
  tabs: { flexDirection: 'row', backgroundColor: colors.neutralDark, borderRadius: 12, padding: 4, marginTop: 4 },
  tab: { flex: 1, paddingVertical: 10, borderRadius: 9, alignItems: 'center' },
  tabActive: { backgroundColor: colors.white, shadowColor: '#000', shadowOpacity: 0.06, shadowRadius: 4, elevation: 1 },
  tabText: { fontSize: 14, fontWeight: '600', color: colors.text.secondary },
  tabTextActive: { color: colors.text.primary },
  friendTools: { gap: 10 },
  searchBox: {
    flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: colors.white, borderRadius: 12,
    borderWidth: 1, borderColor: colors.border, paddingHorizontal: 12, height: 44,
  },
  searchInput: { flex: 1, fontSize: 15, color: colors.text.primary, paddingVertical: 0 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { paddingVertical: 7, paddingHorizontal: 12, borderRadius: 16, backgroundColor: colors.white, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.text.primary, borderColor: colors.text.primary },
  chipText: { fontSize: 13, color: colors.text.primary, fontWeight: '600' },
  chipTextActive: { color: colors.white },
  resultsText: { fontSize: 12, color: colors.text.secondary },
  dayHeader: {
    flexDirection: 'row', justifyContent: 'space-between', paddingHorizontal: 20, paddingTop: 18, paddingBottom: 6,
  },
  dayLabel: { fontSize: 13, fontWeight: '700', color: colors.text.secondary },
  dayTotal: { fontSize: 13, fontWeight: '700', color: colors.successText },
  payoutRow: {
    flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: colors.white, marginHorizontal: 16,
    marginTop: 6, borderRadius: 12, paddingVertical: 12, paddingHorizontal: 14,
  },
  payoutIcon: {
    width: 34, height: 34, borderRadius: 17, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center',
  },
  payoutAmount: { fontSize: 15, fontWeight: '700', color: colors.successText },
  rowTitle: { fontSize: 15, color: colors.text.primary, fontWeight: '600' },
  rowSub: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  friendRow: {
    flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: colors.white, marginHorizontal: 16,
    marginTop: 6, borderRadius: 12, paddingVertical: 12, paddingHorizontal: 14,
  },
  avatar: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  avatarText: { fontSize: 16, fontWeight: '800' },
  remindButton: {
    borderWidth: 1, borderColor: colors.primaryDark, borderRadius: 16, paddingVertical: 6, paddingHorizontal: 12,
    minWidth: 96, alignItems: 'center',
  },
  remindText: { fontSize: 13, fontWeight: '700', color: colors.primaryDark },
  remindedText: { fontSize: 12, color: colors.text.secondary },
  empty: { alignItems: 'center', paddingHorizontal: 32, paddingVertical: 28, gap: 8 },
  emptyIcon: {
    width: 48, height: 48, borderRadius: 24, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center',
  },
  emptyTitle: { fontSize: 16, fontWeight: '700', color: colors.text.primary },
  emptyText: { fontSize: 13, lineHeight: 19, color: colors.text.secondary, textAlign: 'center' },
  footer: { paddingHorizontal: 16, marginTop: 20 },
  footerSpinner: { marginBottom: 12 },
  rulesHeader: {
    flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: colors.white, borderRadius: 12,
    paddingVertical: 14, paddingHorizontal: 14, borderWidth: 1, borderColor: colors.border,
  },
  rulesTitle: { flex: 1, fontSize: 14, fontWeight: '600', color: colors.text.primary },
  rules: { backgroundColor: colors.white, borderRadius: 12, padding: 14, marginTop: 6, gap: 8, borderWidth: 1, borderColor: colors.border },
  ruleItem: { fontSize: 13, lineHeight: 19, color: colors.text.secondary },
});

export default FeeReferralCommissionsScreen;
