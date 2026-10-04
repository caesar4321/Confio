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
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { useAccount } from '../contexts/AccountContext';
import type { MainStackParamList } from '../types/navigation';
import { GET_MONTH_SUMMARY, type MonthSummary, type MonthTotals } from '../apollo/monthSummary';
import { AnalyticsService } from '../services/analyticsService';
import {
  capitalize, categoryLabel, currentYearMonth, deviceTimezone, formatUsd, MASK,
  monthName, nextMonth, previousMonth,
} from '../utils/monthSummary';

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
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} hitSlop={12} accessibilityRole="button" accessibilityLabel="Volver">
          <Icon name="arrow-left" size={24} color={colors.text.primary} />
        </TouchableOpacity>
        <Text style={styles.title} numberOfLines={1}>{title}</Text>
        <View style={styles.headerSpacer} />
      </View>

      <View style={styles.monthNav}>
        <TouchableOpacity
          disabled={!canGoBack}
          onPress={() => setPeriod(previousMonth(period.year, period.month))}
          hitSlop={12}
          accessibilityRole="button"
          accessibilityLabel="Mes anterior"
          accessibilityState={{ disabled: !canGoBack }}
        >
          <Icon name="chevron-left" size={22} color={canGoBack ? colors.text.secondary : colors.border} />
        </TouchableOpacity>
        <Text style={styles.monthTitle} accessibilityRole="header">{monthTitle}</Text>
        <TouchableOpacity
          disabled={isCurrent}
          onPress={() => setPeriod(nextMonth(period.year, period.month))}
          hitSlop={12}
          accessibilityRole="button"
          accessibilityLabel="Mes siguiente"
          accessibilityState={{ disabled: isCurrent }}
        >
          <Icon name="chevron-right" size={22} color={isCurrent ? colors.border : colors.text.secondary} />
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
    </SafeAreaView>
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

function money(value: string | number, masked: boolean, whole = false) {
  return masked ? MASK : formatUsd(value, { whole });
}

function MonthBody({ summary, masked, isCurrent, runKey, onOpen, onSend, onReceive }: BodyProps) {
  const cur = summary.current;
  const spending = Number(cur.spendingUsd);
  const income = Number(cur.incomeUsd);
  const shownSpending = useTickSettle(spending, runKey);
  const shownIncome = useTickSettle(income, runKey);
  const monthLabel = monthName(summary.month);
  const prevLabel = monthName(previousMonth(summary.year, summary.month).month);

  const ownRows = ownMoneyRows(cur);
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
  const comparison = summary.previousIsPartial
    ? `Mismo período de ${prevLabel}`
    : `vs ${prevLabel} completo`;
  const maxCategory = Math.max(1, ...cur.spendingByCategory.map((c) => Number(c.amountUsd)));

  return (
    <ScrollView contentContainerStyle={styles.body}>
      <View style={styles.totals}>
        <TouchableOpacity onPress={() => onOpen('spending', 'Salió')} accessibilityRole="button"
          accessibilityLabel={masked ? 'Salió, oculto' : `Salió ${formatUsd(spending)}`} testID="total-spending">
          <Text style={styles.totalLabel}>Salió</Text>
          <Text style={styles.totalBig}>{money(shownSpending, masked, true)}</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => onOpen('income', 'Entró')} accessibilityRole="button"
          accessibilityLabel={masked ? 'Entró, oculto' : `Entró ${formatUsd(income)}`} testID="total-income">
          <Text style={styles.totalLabel}>Entró</Text>
          <Text style={styles.totalSmall}>{money(shownIncome, masked, true)}</Text>
        </TouchableOpacity>
      </View>
      <Text style={styles.note}>Sin contar recargas, retiros ni ahorro.</Text>
      {hasComparison && (
        <Text style={styles.note} testID="month-comparison">
          {comparison}: salió {money(summary.previous.spendingUsd, masked, true)} · entró{' '}
          {money(summary.previous.incomeUsd, masked, true)}
        </Text>
      )}
      {/* Protection / savings-earned slot (design 7B/7C): renders once the
          server provides real values (DT8, protection flag); nothing until then. */}

      {cur.spendingByCategory.length > 0 && (
        <Section title="En qué se fue">
          {cur.spendingByCategory.map((c) => {
            const uncategorized = c.category === 'uncategorized';
            const width = `${Math.max(2, (Number(c.amountUsd) / maxCategory) * 100)}%` as const;
            return (
              <TouchableOpacity
                key={c.category}
                style={styles.categoryRow}
                onPress={() => uncategorized
                  ? onOpen('uncategorized', 'Sin categoría')
                  : onOpen('category', categoryLabel(c.category), c.category)}
                accessibilityRole="button"
                accessibilityLabel={`${categoryLabel(c.category)}, ${masked ? 'oculto' : formatUsd(c.amountUsd)}`}
              >
                <View style={styles.rowBetween}>
                  <Text style={uncategorized ? styles.rowMuted : styles.rowText}>{categoryLabel(c.category)}</Text>
                  <Text style={uncategorized ? styles.rowMuted : styles.rowAmount}>
                    {money(c.amountUsd, masked)}{uncategorized ? ' ›' : ''}
                  </Text>
                </View>
                <View style={styles.barTrack}>
                  <View style={[styles.barFill, uncategorized && styles.barUncategorized, { width }]} />
                </View>
              </TouchableOpacity>
            );
          })}
        </Section>
      )}

      {ownRows.length > 0 && (
        <Section title="Entre tus cuentas">
          {ownRows.map((r) => (
            <TouchableOpacity key={r.label} style={styles.rowBetween} onPress={() => onOpen('own_money', r.label, r.bucket)}
              accessibilityRole="button">
              <Text style={styles.rowMuted}>{r.label}</Text>
              <Text style={styles.rowMuted}>{money(r.amount, masked)}</Text>
            </TouchableOpacity>
          ))}
        </Section>
      )}

      {summary.counterparties.length > 0 && (
        <Section title="Con quién">
          {summary.counterparties.map((c) => (
            <TouchableOpacity key={c.key} style={styles.personRow} onPress={() => onOpen('counterparty', c.name || 'Movimientos', c.key)}
              accessibilityRole="button">
              <Text style={styles.rowText} numberOfLines={1}>{c.name || 'Sin nombre'}</Text>
              <View style={styles.personAmounts}>
                {Number(c.receivedUsd) > 0 && (
                  <Text style={styles.personAmount}>Recibiste <Text style={styles.rowAmount}>{money(c.receivedUsd, masked)}</Text></Text>
                )}
                {Number(c.sentUsd) > 0 && (
                  <Text style={styles.personAmount}>Enviaste <Text style={styles.rowAmount}>{money(c.sentUsd, masked)}</Text></Text>
                )}
              </View>
            </TouchableOpacity>
          ))}
          <TouchableOpacity onPress={() => onOpen('counterparties', 'Con quién')} accessibilityRole="button">
            <Text style={styles.link}>Ver todos</Text>
          </TouchableOpacity>
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle} accessibilityRole="header">{title.toUpperCase()}</Text>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.white },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, paddingTop: 8, paddingBottom: 4, gap: 12 },
  title: { flex: 1, fontSize: 20, fontWeight: '700', color: colors.text.primary },
  headerSpacer: { width: 24 },
  monthNav: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 16, paddingVertical: 10 },
  monthTitle: { fontSize: 16, fontWeight: '600', color: colors.text.primary, minWidth: 140, textAlign: 'center' },
  body: { paddingHorizontal: 20, paddingBottom: 32 },
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
  totals: { flexDirection: 'row', alignItems: 'flex-end', gap: 20, marginTop: 4 },
  totalLabel: { fontSize: 13, color: colors.text.secondary },
  totalBig: { fontSize: 34, fontWeight: '700', color: colors.text.primary, fontVariant: ['tabular-nums'] },
  totalSmall: { fontSize: 22, fontWeight: '700', color: colors.text.primary, fontVariant: ['tabular-nums'] },
  note: { fontSize: 12, color: colors.text.secondary, marginTop: 6, fontVariant: ['tabular-nums'] },
  section: { marginTop: 24 },
  sectionTitle: { fontSize: 12, fontWeight: '700', letterSpacing: 0.6, color: colors.text.secondary, marginBottom: 8 },
  categoryRow: { paddingVertical: 6, minHeight: 44, justifyContent: 'center' },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', minHeight: 40 },
  rowText: { fontSize: 15, color: colors.text.primary, flexShrink: 1 },
  rowMuted: { fontSize: 15, color: colors.text.secondary, fontVariant: ['tabular-nums'] },
  rowAmount: { fontSize: 15, fontWeight: '600', color: colors.text.primary, fontVariant: ['tabular-nums'] },
  barTrack: { height: 6, borderRadius: 999, backgroundColor: colors.surface, overflow: 'hidden', marginTop: 4 },
  barFill: { height: '100%', backgroundColor: colors.primary, borderRadius: 999 },
  barUncategorized: { backgroundColor: colors.border },
  personRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border, gap: 12, minHeight: 44 },
  personAmounts: { alignItems: 'flex-end' },
  personAmount: { fontSize: 12, color: colors.text.secondary },
  link: { fontSize: 14, fontWeight: '600', color: colors.primaryDark, paddingVertical: 12 },
  skeletonRow: { height: 18, borderRadius: 8, backgroundColor: colors.surface, marginTop: 16 },
  skeletonHero: { height: 44, width: '60%' },
  spinner: { marginTop: 24 },
  bottomPad: { height: 16 },
});
