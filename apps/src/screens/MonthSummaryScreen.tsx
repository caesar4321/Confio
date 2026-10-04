// "Tu mes" — the month in one screen (design: docs/designs/cashflow-home-tu-mes.md).
//
// Hierarchy (1D): Salió is the anchor, Entró beside it, plain type on white.
// Sections each have one job (1A/1B): En qué se fue (spending only, by
// category, "Sin categoría" last) · Entre tus cuentas (own money moving) ·
// Con quién (who you received from / sent to). Amounts always US$ (5A),
// masked with the balance (6A). States (2B): skeleton, inline retry (never
// zeros), honest empty month.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AccessibilityInfo,
  ActivityIndicator,
  Animated,
  Easing,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  View,
} from 'react-native';
import { useQuery } from '@apollo/client';
import { useFocusEffect, useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Feather';
import { Header } from '../navigation/Header';
import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { useAccount } from '../contexts/AccountContext';
import type { MainStackParamList } from '../types/navigation';
import {
  GET_MONTH_MOVEMENTS, GET_MONTH_SUMMARY, type CategoryKey, type MonthSummary, type MonthTotals,
} from '../apollo/monthSummary';
import { AnalyticsService } from '../services/analyticsService';
import {
  CATEGORY_META, capitalize, categoryLabel, currentYearMonth, deviceTimezone, formatUsd, MASK,
  monthName, nextMonth, previousMonth,
} from '../utils/monthSummary';
import { useNumberLocale } from '../contexts/NumberLocaleProvider';
import Svg, { Defs, LinearGradient as SvgLinearGradient, Rect, Stop } from 'react-native-svg';

type Nav = NativeStackNavigationProp<MainStackParamList>;
type Route = RouteProp<MainStackParamList, 'MonthSummary'>;

const TICK_MS = 1200;

/** DESIGN.md "tick-settle": money rolls in once and settles; instant with Reduce Motion. */
function useTickSettle(target: number, runKey: string) {
  const anim = useRef(new Animated.Value(0)).current;
  const [value, setValue] = useState(target);
  // A refresh (cache, then network) can change the number mid-roll or after
  // it settled: the roll heads for the latest target, and a settled number
  // jumps straight to it instead of replaying the opening animation.
  const targetRef = useRef(target);
  const settled = useRef(false);
  targetRef.current = target;
  useEffect(() => {
    if (settled.current) setValue(target);
  }, [target]);
  useEffect(() => {
    let cancelled = false;
    settled.current = false;
    const id = anim.addListener(({ value: v }) => setValue(targetRef.current * v));
    const settle = () => {
      if (cancelled) return;
      settled.current = true;
      setValue(targetRef.current);
    };
    AccessibilityInfo.isReduceMotionEnabled().then((reduce) => {
      if (cancelled) return;
      if (reduce) {
        anim.setValue(1);
        settle();
        return;
      }
      anim.setValue(0);
      Animated.timing(anim, { toValue: 1, duration: TICK_MS, easing: Easing.out(Easing.cubic), useNativeDriver: false })
        .start(settle);
    }).catch(settle);
    return () => {
      cancelled = true;
      anim.stopAnimation();
      anim.removeListener(id);
    };
    // runKey: animate on the first open of each month view only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runKey]);
  return value;
}

function monthsBetween(a: { year: number; month: number }, b: { year: number; month: number }) {
  return (b.year - a.year) * 12 + (b.month - a.month);
}

export function MonthSummaryScreen() {
  // Re-render when the user's country (number format) resolves after mount.
  useNumberLocale();
  const navigation = useNavigation<Nav>();
  const route = useRoute<Route>();
  const { activeAccount } = useAccount();
  const masked = Boolean(route.params?.masked);
  const today = currentYearMonth();
  const [period, setPeriod] = useState({
    year: route.params?.year ?? today.year,
    month: route.params?.month ?? today.month,
  });
  const timezone = useMemo(() => deviceTimezone(), []);

  const firstMonth = useMemo(() => {
    const created = activeAccount?.createdAt ? new Date(activeAccount.createdAt) : null;
    return created && !Number.isNaN(created.getTime()) ? currentYearMonth(created) : null;
  }, [activeAccount?.createdAt]);
  const isCurrent = period.year === today.year && period.month === today.month;
  const canGoBack = !firstMonth || monthsBetween(firstMonth, period) > 0;

  const { data, loading, error, refetch } = useQuery<{ monthSummary: MonthSummary | null }>(GET_MONTH_SUMMARY, {
    variables: { year: period.year, month: period.month, timezone },
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'none',
    // A refresh must be a NEW request that supersedes any older one still in
    // flight (whose late, pre-save answer Apollo then ignores).
    context: { queryDeduplication: false },
  });
  const summary = data?.monthSummary ?? null;

  // Back from a movement list where categories may have changed: re-read.
  // (refetch via ref: the effect must run per focus, never per render.)
  const refetchRef = useRef(refetch);
  refetchRef.current = refetch;
  const focusedOnce = useRef(false);
  useFocusEffect(useCallback(() => {
    if (focusedOnce.current) refetchRef.current().catch(() => undefined);
    focusedOnce.current = true;
  }, []));

  useEffect(() => {
    AnalyticsService.logFunnelEvent('tu_mes_opened');
  }, []);

  const title = activeAccount?.type === 'business' && activeAccount?.business?.name
    ? `El mes de ${activeAccount.business.name}`
    : 'Tu mes';
  const monthTitle = `${capitalize(monthName(period.month))} ${period.year}`;

  const openList = (filterBy: MainStackParamList['MonthMovements']['filterBy'], listTitle: string, value?: string) =>
    navigation.navigate('MonthMovements', { year: period.year, month: period.month, filterBy, value, title: listTitle, masked });

  return (
    <View style={styles.safe}>
      {/* The app's shared screen header on the brand field (same as
          Notificaciones and the dollar account you arrive from). */}
      <Header navigation={navigation as any} title={title} backgroundColor={colors.heroField} isLight showBackButton />

      <View style={styles.monthNav}>
        <TouchableOpacity
          disabled={!canGoBack}
          onPress={() => setPeriod(previousMonth(period.year, period.month))}
          style={[styles.navBtn, !canGoBack && styles.navBtnDisabled]}
          accessibilityRole="button"
          accessibilityLabel="Mes anterior"
          accessibilityState={{ disabled: !canGoBack }}
        >
          <Icon name="chevron-left" size={20} color={canGoBack ? colors.text.primary : colors.text.light} />
        </TouchableOpacity>
        <Text style={styles.monthTitle} accessibilityRole="header">{monthTitle}</Text>
        <TouchableOpacity
          disabled={isCurrent}
          onPress={() => setPeriod(nextMonth(period.year, period.month))}
          style={[styles.navBtn, isCurrent && styles.navBtnDisabled]}
          accessibilityRole="button"
          accessibilityLabel="Mes siguiente"
          accessibilityState={{ disabled: isCurrent }}
        >
          <Icon name="chevron-right" size={20} color={isCurrent ? colors.text.light : colors.text.primary} />
        </TouchableOpacity>
      </View>

      {loading && !summary ? (
        <SkeletonState />
      ) : error && !summary ? (
        <View style={styles.center} testID="month-summary-error">
          <Text style={styles.muted}>No pudimos cargar tu mes</Text>
          <TouchableOpacity onPress={() => refetch()} style={styles.retry} accessibilityRole="button">
            <Text style={styles.retryText}>Reintentar</Text>
          </TouchableOpacity>
        </View>
      ) : !summary ? (
        <View style={styles.center}>
          <Text style={styles.muted}>Este resumen no está disponible para tu cuenta.</Text>
        </View>
      ) : (
        <MonthBody
          summary={summary}
          masked={masked}
          isCurrent={isCurrent}
          runKey={`${period.year}-${period.month}`}
          onOpen={openList}
          onSend={() => navigation.navigate('Send')}
          onReceive={() => navigation.navigate('Receive')}
        />
      )}
    </View>
  );
}

function SkeletonState() {
  return (
    <View style={styles.body} testID="month-summary-loading" accessibilityLabel="Cargando tu mes">
      {[0, 1, 2, 3].map((i) => (
        <View key={i} style={[styles.skeletonRow, i === 0 && styles.skeletonHero]} />
      ))}
      <ActivityIndicator color={colors.primary} style={styles.spinner} />
    </View>
  );
}

type BodyProps = {
  summary: MonthSummary;
  masked: boolean;
  isCurrent: boolean;
  runKey: string;
  onOpen: (filterBy: MainStackParamList['MonthMovements']['filterBy'], title: string, value?: string) => void;
  onSend: () => void;
  onReceive: () => void;
};

/** One precision on this screen: whole dollars (design C, 2026-10-04). */
function money(value: string | number, masked: boolean) {
  return masked ? MASK : formatUsd(value, { whole: true });
}

const OWN_ICON: Record<OwnMoneyBucket, string> = {
  top_up: 'arrow-down-circle',
  withdrawal: 'arrow-up-circle',
  savings: 'archive',
  investment: 'trending-up',
};

// Avatar tints (never violet: that hue belongs to $CONFIO only, DESIGN.md).
const AVATAR_TINTS = [
  { bg: '#D1FAE5', fg: '#065F46' },
  { bg: '#DBEAFE', fg: '#1E40AF' },
  { bg: '#FEF3C7', fg: '#92400E' },
  { bg: '#FFE4E6', fg: '#9F1239' },
];
function tintFor(key: string) {
  let h = 0;
  for (let i = 0; i < key.length; i += 1) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return AVATAR_TINTS[h % AVATAR_TINTS.length];
}

// Unknown wallets: the server merges two or more into one 'external' line
// ("Depósitos externos (N)") before its top-5 cut; a single one keeps its
// own address key and the name "Depósito externo".
/** Unknown outside wallet, judged on the RAW server key/name (before any
 *  relabeling), so the flag survives for the icon. */
const isUnknownWallet = (key: string, name: string) =>
  key === 'external' || (key.startsWith('addr:') && (!name || name === 'Depósito externo'));
/** A single unknown wallet is a deposit only if no money went out to it. */
const externalName = (sent: number) => (sent > 0 ? 'Billetera externa' : 'Depósito externo');

function MonthBody({ summary, masked, isCurrent, runKey, onOpen, onSend, onReceive }: BodyProps) {
  const cur = summary.current;
  const spending = Number(cur.spendingUsd);
  const income = Number(cur.incomeUsd);
  const shownSpending = useTickSettle(spending, runKey);
  const shownIncome = useTickSettle(income, runKey);
  const monthLabel = monthName(summary.month);
  const prevLabel = monthName(previousMonth(summary.year, summary.month).month);

  const uncategorized = cur.spendingByCategory.find((c) => c.category === 'uncategorized');
  const categorized = cur.spendingByCategory.filter((c) => c.category !== 'uncategorized');
  // How many payments still need a label: the same list the CTA opens.
  const { data: uncategorizedData, refetch: refetchPending } = useQuery<{ monthMovements: { id: string }[] }>(GET_MONTH_MOVEMENTS, {
    variables: { year: summary.year, month: summary.month, timezone: summary.timezone, filterBy: 'uncategorized', value: null },
    skip: !uncategorized,
    fetchPolicy: 'cache-and-network',
    context: { queryDeduplication: false },
  });
  // Back from a list where payments were labeled: the count must follow
  // the refreshed summary (a stale "Clasifica 3 pagos" after labeling one).
  const refetchPendingRef = useRef(refetchPending);
  refetchPendingRef.current = refetchPending;
  const pendingFocused = useRef(false);
  useFocusEffect(useCallback(() => {
    if (pendingFocused.current) refetchPendingRef.current?.().catch(() => undefined);
    pendingFocused.current = true;
  }, []));
  const pendingCount = uncategorized ? uncategorizedData?.monthMovements.length : 0;

  const ownRows = ownMoneyRows(cur);
  const people = summary.counterparties.map((c) => {
    const unknown = isUnknownWallet(c.key, c.name);
    const sentUsd = Number(c.sentUsd);
    return {
      key: c.key,
      unknown,
      // The server's merged plural label stays; a singleton is named by direction.
      name: c.key === 'external' ? c.name : unknown ? externalName(sentUsd) : c.name || 'Sin nombre',
      receivedUsd: Number(c.receivedUsd),
      sentUsd,
    };
  });
  const isEmpty = cur.movementCount === 0 && ownRows.length === 0;
  if (isEmpty) {
    return (
      <View style={styles.center} testID="month-summary-empty">
        <Text style={styles.emptyTitle}>Todavía no hay movimientos en {monthLabel}.</Text>
        <View style={styles.emptyActions}>
          <TouchableOpacity style={styles.pill} onPress={onSend} accessibilityRole="button">
            <Text style={styles.pillText}>Enviar</Text>
          </TouchableOpacity>
          <TouchableOpacity style={[styles.pill, styles.pillGhost]} onPress={onReceive} accessibilityRole="button">
            <Text style={[styles.pillText, styles.pillGhostText]}>Recibir</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  const hasComparison = summary.previous.movementCount > 0;
  const comparison = summary.previousIsPartial ? `Mismo período de ${prevLabel}` : `vs ${prevLabel}`;
  const total = income + spending;

  return (
    <ScrollView contentContainerStyle={styles.body}>
      {/* In vs out (design A): the two totals, then one proportion bar;
          emerald for money in, sky blue for money out, a faint mint wash. */}
      <View style={styles.card}>
        <Svg style={StyleSheet.absoluteFill} pointerEvents="none">
          <Defs>
            <SvgLinearGradient id="tuMesWash" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={colors.primarySoft} stopOpacity="1" />
              <Stop offset="0.65" stopColor={colors.white} stopOpacity="1" />
            </SvgLinearGradient>
          </Defs>
          <Rect width="100%" height="100%" fill="url(#tuMesWash)" />
        </Svg>
        <View style={styles.totals}>
          <TouchableOpacity onPress={() => onOpen('income', 'Entró')} accessibilityRole="button" style={styles.totalBlock}
            accessibilityLabel={masked ? 'Entró, oculto' : `Entró ${formatUsd(income, { whole: true })}`} testID="total-income">
            <Text style={[styles.totalLabel, styles.totalLabelIn]}>Entró</Text>
            <Text style={[styles.totalAmount, styles.totalIn]} numberOfLines={1} adjustsFontSizeToFit>
              {money(shownIncome, masked)}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => onOpen('spending', 'Salió')} accessibilityRole="button"
            style={[styles.totalBlock, styles.totalBlockEnd]}
            accessibilityLabel={masked ? 'Salió, oculto' : `Salió ${formatUsd(spending, { whole: true })}`} testID="total-spending">
            <Text style={[styles.totalLabel, styles.totalLabelOut]}>Salió</Text>
            <Text style={[styles.totalAmount, styles.totalOut]} numberOfLines={1} adjustsFontSizeToFit>
              {money(shownSpending, masked)}
            </Text>
          </TouchableOpacity>
        </View>
        <View style={styles.ratioTrack} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
          {/* Normalized weights (Yoga floors flex sums below 1) and no
              zero-width segments. */}
          {income > 0 && <View style={[styles.ratioIn, { flex: income / total }]} />}
          {spending > 0 && <View style={[styles.ratioOut, { flex: spending / total }]} />}
        </View>
        <Text style={styles.note}>Sin contar recargas, retiros ni ahorro.</Text>
        {hasComparison && (
          <Text style={styles.noteMuted} testID="month-comparison">
            {comparison}: <Text style={styles.flowOutText}>salió {money(summary.previous.spendingUsd, masked)}</Text>,{' '}
            <Text style={styles.flowInText}>entró {money(summary.previous.incomeUsd, masked)}</Text>
          </Text>
        )}
      </View>
      {/* Protection / savings-earned slot (design 7B/7C): renders once the
          server provides real values (DT8, protection flag); nothing until then. */}

      {cur.spendingByCategory.length > 0 && (
        <Section
          title="En qué se fue"
          aside={uncategorized
            ? `${money(uncategorized.amountUsd, masked)} sin categorizar${pendingCount ? ` (${pendingCount} ${pendingCount === 1 ? 'pago' : 'pagos'})` : ''}`
            : undefined}
        >
          {uncategorized && (
            <TouchableOpacity style={styles.cta} onPress={() => onOpen('uncategorized', 'Sin categoría')}
              accessibilityRole="button" testID="categorize-cta">
              <View style={styles.ctaIcon}><Icon name="tag" size={18} color={colors.successText} /></View>
              <View style={styles.ctaText}>
                <Text style={styles.ctaTitle}>
                  {pendingCount ? `Clasifica ${pendingCount} ${pendingCount === 1 ? 'pago' : 'pagos'}` : 'Clasifica tus pagos'}
                </Text>
                <Text style={styles.ctaSub}>Así podrás ver en qué estás gastando.</Text>
              </View>
              <Icon name="chevron-right" size={20} color={colors.successText} />
            </TouchableOpacity>
          )}
          {categorized.length > 0 && (
            <View style={styles.chips}>
              {categorized.map((c) => {
                const meta = CATEGORY_META[c.category as CategoryKey];
                return (
                  <TouchableOpacity key={c.category} style={styles.chip}
                    onPress={() => onOpen('category', categoryLabel(c.category), c.category)} accessibilityRole="button"
                    accessibilityLabel={`${categoryLabel(c.category)}, ${masked ? 'oculto' : formatUsd(c.amountUsd, { whole: true })}`}>
                    {meta && <Icon name={meta.icon} size={15} color={colors.text.secondary} />}
                    <Text style={styles.chipText}>{categoryLabel(c.category)}</Text>
                    <Text style={styles.chipAmount}>{money(c.amountUsd, masked)}</Text>
                  </TouchableOpacity>
                );
              })}
            </View>
          )}
        </Section>
      )}

      {ownRows.length > 0 && (
        <Section title="Entre tus cuentas">
          <View style={styles.listCard}>
            {ownRows.map((r, i) => (
              <TouchableOpacity key={r.label} style={[styles.listRow, i > 0 && styles.listRowDivider]}
                onPress={() => onOpen('own_money', r.label, r.bucket)} accessibilityRole="button">
                <View style={[styles.avatar, { backgroundColor: colors.primarySoft }]}>
                  <Icon name={OWN_ICON[r.bucket]} size={18} color={colors.successText} />
                </View>
                <Text style={styles.listName} numberOfLines={1}>{r.label}</Text>
                <Text style={styles.listAmount}>{money(r.amount, masked)}</Text>
                <Icon name="chevron-right" size={18} color={colors.text.light} />
              </TouchableOpacity>
            ))}
          </View>
        </Section>
      )}

      {people.length > 0 && (
        <Section title="Con quién">
          <View style={styles.listCard}>
            {people.map((p, i) => {
              const tint = tintFor(p.key);
              const both = p.receivedUsd > 0 && p.sentUsd > 0;
              // Both directions: one line each (a single line truncates on
              // narrow phones and would hide the second amount).
              const subs = both
                ? [`Recibiste ${money(p.receivedUsd, masked)}`, `Enviaste ${money(p.sentUsd, masked)}`]
                : [p.receivedUsd > 0 ? 'Recibiste' : 'Enviaste'];
              const amount = both ? null : money(p.receivedUsd > 0 ? p.receivedUsd : p.sentUsd, masked);
              return (
                <TouchableOpacity key={p.key} style={[styles.listRow, i > 0 && styles.listRowDivider]}
                  onPress={() => onOpen('counterparty', p.name, p.key)}
                  accessibilityRole="button">
                  <View style={[styles.avatar, { backgroundColor: p.unknown ? colors.primarySoft : tint.bg }]}>
                    {p.unknown
                      ? <Icon name={p.sentUsd > 0 ? 'globe' : 'download'} size={17} color={colors.successText} />
                      : <Text style={[styles.avatarText, { color: tint.fg }]}>{p.name.trim().charAt(0).toUpperCase() || '?'}</Text>}
                  </View>
                  <View style={styles.listMain}>
                    <Text style={styles.listName} numberOfLines={1}>{p.name}</Text>
                    {subs.map((line) => (
                      <Text key={line} style={styles.listSub}>{line}</Text>
                    ))}
                  </View>
                  {amount && <Text style={styles.listAmount}>{amount}</Text>}
                  <Icon name="chevron-right" size={18} color={colors.text.light} />
                </TouchableOpacity>
              );
            })}
            <TouchableOpacity style={[styles.listRow, styles.listRowDivider]} onPress={() => onOpen('counterparties', 'Con quién')}
              accessibilityRole="button">
              <Text style={styles.link}>Ver todos</Text>
              <Icon name="chevron-right" size={18} color={colors.successText} />
            </TouchableOpacity>
          </View>
        </Section>
      )}
      {!isCurrent && <View style={styles.bottomPad} />}
    </ScrollView>
  );
}

/** Direction-aware own-money rows (7F): positive amounts, zero rows hidden. */
export type OwnMoneyBucket = 'top_up' | 'withdrawal' | 'savings' | 'investment';

export function ownMoneyRows(t: MonthTotals): { label: string; amount: number; bucket: OwnMoneyBucket }[] {
  const rows: { label: string; amount: number; bucket: OwnMoneyBucket }[] = [];
  const topUps = Number(t.topUpsUsd);
  const withdrawals = Number(t.withdrawalsUsd);
  const savings = Number(t.savingsNetUsd);
  const investment = Number(t.investmentNetUsd);
  if (topUps > 0) rows.push({ label: 'Recargas', amount: topUps, bucket: 'top_up' });
  if (withdrawals > 0) rows.push({ label: 'Retiros', amount: withdrawals, bucket: 'withdrawal' });
  if (savings > 0) rows.push({ label: 'Guardaste', amount: savings, bucket: 'savings' });
  if (savings < 0) rows.push({ label: 'Retiraste del ahorro', amount: -savings, bucket: 'savings' });
  if (investment > 0) rows.push({ label: 'Invertiste', amount: investment, bucket: 'investment' });
  if (investment < 0) rows.push({ label: 'Vendiste acciones', amount: -investment, bucket: 'investment' });
  return rows;
}

function Section({ title, aside, children }: { title: string; aside?: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle} accessibilityRole="header">{title}</Text>
        {aside ? <Text style={styles.sectionAside} numberOfLines={1}>{aside}</Text> : null}
      </View>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  monthNav: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 16, paddingTop: 14, paddingBottom: 14 },
  // Round 40pt icon buttons, the same shape as the header's own buttons.
  navBtn: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.white, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
  navBtnDisabled: { backgroundColor: colors.surface },
  monthTitle: { fontSize: 16, fontWeight: '600', color: colors.text.primary, minWidth: 150, textAlign: 'center' },
  body: { paddingHorizontal: 16, paddingBottom: 40 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  muted: { fontSize: 15, color: colors.text.secondary, textAlign: 'center' },
  retry: { marginTop: 12, paddingHorizontal: 20, minHeight: 44, justifyContent: 'center' },
  retryText: { fontSize: 15, fontWeight: '700', color: colors.primaryDark },
  emptyTitle: { fontSize: 16, color: colors.text.primary, textAlign: 'center' },
  emptyActions: { flexDirection: 'row', gap: 12, marginTop: 16 },
  pill: { backgroundColor: colors.primaryDark, borderRadius: 999, paddingHorizontal: 24, minHeight: 44, justifyContent: 'center' },
  pillGhost: { backgroundColor: colors.white, borderWidth: 1, borderColor: colors.border },
  pillText: { color: colors.white, fontWeight: '700', fontSize: 15 },
  pillGhostText: { color: colors.text.primary },
  card: { backgroundColor: colors.white, borderRadius: 20, padding: 18, borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.primaryMuted, overflow: 'hidden' },
  ratioTrack: { flexDirection: 'row', height: 10, borderRadius: 999, overflow: 'hidden', backgroundColor: colors.surfaceMuted,
    gap: 3, marginTop: 14 },
  ratioIn: { backgroundColor: colors.flowIn.bar, borderRadius: 999 },
  ratioOut: { backgroundColor: colors.flowOut.bar, borderRadius: 999 },
  totals: { flexDirection: 'row', gap: 16 },
  totalBlock: { flex: 1, minHeight: 44 },
  totalBlockEnd: { alignItems: 'flex-end' },
  totalLabel: { fontSize: 14, fontWeight: '600', color: colors.text.secondary },
  totalLabelIn: { color: colors.flowIn.textSmall },
  totalLabelOut: { color: colors.flowOut.text },
  totalAmount: { fontSize: 26, fontWeight: '700', color: colors.text.primary, fontVariant: ['tabular-nums'], marginTop: 2 },
  // Shrink-to-fit can drop below large-text size: use the AA small-text tone.
  totalIn: { color: colors.flowIn.textSmall },
  totalOut: { color: colors.flowOut.text },
  flowInText: { color: colors.flowIn.textSmall },
  flowOutText: { color: colors.flowOut.text },
  note: { fontSize: 13, color: colors.text.primary, marginTop: 12 },
  noteMuted: { fontSize: 13, color: colors.text.secondary, marginTop: 2, fontVariant: ['tabular-nums'] },
  section: { marginTop: 22 },
  sectionHead: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10, gap: 12 },
  sectionTitle: { fontSize: 16, fontWeight: '700', color: colors.text.primary },
  sectionAside: { fontSize: 12, color: colors.text.secondary, flexShrink: 1, fontVariant: ['tabular-nums'] },
  cta: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderRadius: 16,
    backgroundColor: colors.primarySoft, borderWidth: 1, borderColor: colors.primaryMuted, minHeight: 56 },
  ctaIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center' },
  ctaText: { flex: 1 },
  ctaTitle: { fontSize: 15, fontWeight: '700', color: colors.successText },
  ctaSub: { fontSize: 13, color: colors.text.secondary, marginTop: 2 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 10 },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 40, paddingHorizontal: 12, borderRadius: 999,
    backgroundColor: colors.white, borderWidth: 1, borderColor: colors.border },
  chipText: { fontSize: 14, color: colors.text.primary },
  chipAmount: { fontSize: 14, fontWeight: '700', color: colors.text.primary, fontVariant: ['tabular-nums'] },
  listCard: { backgroundColor: colors.white, borderRadius: 16, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border,
    paddingHorizontal: 14 },
  listRow: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 60, paddingVertical: 8 },
  listRowDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  avatar: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  avatarText: { fontSize: 15, fontWeight: '700' },
  listMain: { flex: 1 },
  listName: { flex: 1, fontSize: 15, color: colors.text.primary },
  listSub: { fontSize: 12, color: colors.text.secondary, marginTop: 1, fontVariant: ['tabular-nums'] },
  listAmount: { fontSize: 15, fontWeight: '700', color: colors.text.primary, fontVariant: ['tabular-nums'] },
  link: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.successText },
  skeletonRow: { height: 18, borderRadius: 8, backgroundColor: colors.surfaceMuted, marginTop: 16 },
  skeletonHero: { height: 120, borderRadius: 20 },
  spinner: { marginTop: 24 },
  bottomPad: { height: 16 },
});
